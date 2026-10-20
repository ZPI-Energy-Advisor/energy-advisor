from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


TIMESTAMP_START = "timestamp_start"
KWH = "kwh"
MAX_SKIPPED_EXAMPLES = 10


class FileImportError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class SkippedRow:
    row: int
    reason: str


@dataclass
class ImportReport:
    detected_format: str
    format_label: str
    rows_total: int = 0
    rows_imported: int = 0
    rows_ignored: int = 0
    resolution_minutes: int | None = None
    skipped_count: int = 0
    skipped_examples: list[SkippedRow] = field(default_factory=list)

    def add_skipped(self, rows: pd.Series) -> None:
        self.skipped_count = int(rows.size)
        self.skipped_examples = [
            SkippedRow(row=int(row), reason=reason)
            for row, reason in rows.sort_index().head(MAX_SKIPPED_EXAMPLES).items()
        ]

    def to_dict(self) -> dict:
        return {
            "detected_format": self.detected_format,
            "format_label": self.format_label,
            "rows_total": self.rows_total,
            "rows_imported": self.rows_imported,
            "rows_ignored": self.rows_ignored,
            "resolution_minutes": self.resolution_minutes,
            "skipped_rows": {
                "count": self.skipped_count,
                "examples": [{"row": item.row, "reason": item.reason} for item in self.skipped_examples],
            },
        }


@dataclass
class ParsedEnergyFile:
    data: pd.DataFrame
    resolution_minutes: int
    report: ImportReport


class EnergyFileParser(ABC):
    name: str
    label: str

    @abstractmethod
    def detect(self, table: pd.DataFrame) -> bool: ...

    @abstractmethod
    def parse(self, table: pd.DataFrame) -> ParsedEnergyFile: ...
