from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


TIMESTAMP_START = "timestamp_start"
KWH = "kwh"
MAX_SKIPPED_EXAMPLES = 10
# Jednostka raportu: wiersze pliku CSV albo akcje pliku urządzeń (JSON).
UNIT_ROW = "row"
UNIT_ACTION = "action"


class FileImportError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class SkippedRow:
    # Numer wiersza CSV albo pozycja akcji w energy_usage (od 1), zależnie od ImportReport.unit.
    row: int
    reason: str
    action_id: str | None = None


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
    unit: str = UNIT_ROW

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
            "unit": self.unit,
            "skipped_rows": {
                "count": self.skipped_count,
                "examples": [self._example(item) for item in self.skipped_examples],
            },
        }

    @staticmethod
    def _example(item: SkippedRow) -> dict:
        example = {"row": item.row, "reason": item.reason}
        if item.action_id is not None:
            example["action_id"] = item.action_id
        return example


@dataclass
class DeviceData:
    """Urządzenia i akcje z pliku urządzeń, przekazywane obok zagregowanej serii zużycia."""

    devices: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)


@dataclass
class ParsedEnergyFile:
    data: pd.DataFrame
    resolution_minutes: int
    report: ImportReport
    devices: DeviceData | None = None


class EnergyFileParser(ABC):
    name: str
    label: str

    @abstractmethod
    def detect(self, table: pd.DataFrame) -> bool: ...

    @abstractmethod
    def parse(self, table: pd.DataFrame) -> ParsedEnergyFile: ...


class DocumentParser(ABC):
    """Parser plików-dokumentów (JSON), które nie są tabelą wierszy jak CSV."""

    name: str
    label: str

    @abstractmethod
    def detect(self, document: dict) -> bool: ...

    @abstractmethod
    def parse(self, document: dict) -> ParsedEnergyFile: ...
