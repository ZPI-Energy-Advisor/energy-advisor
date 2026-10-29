from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

import pandas as pd

from app.parsers.device_records import DeviceRecord


TIMESTAMP_START = "timestamp_start"
KWH = "kwh"
MAX_SKIPPED_EXAMPLES = 10
# Jednostka raportu: wiersze pliku CSV albo akcje pliku urządzeń (JSON).
UNIT_ROW = "row"
UNIT_ACTION = "action"


class FileImportError(Exception):
    """Błąd importu. Opcjonalna lista `errors` trafia do UI jako lista; `errors_count` liczy też pominięte."""

    def __init__(self, status_code: int, detail: str, errors: list[dict] | None = None,
                 errors_count: int | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.errors = errors
        self.errors_count = errors_count if errors_count is not None else len(errors or [])

    def http_detail(self) -> str | dict:
        if self.errors is None:
            return self.detail
        return {"message": self.detail, "errors": self.errors, "errors_count": self.errors_count}


@dataclass
class SkippedRow:
    # Numer wiersza CSV albo pozycja akcji w energy_usage (od 1), zależnie od ImportReport.unit.
    row: int
    reason: str
    action_id: str | None = None


@dataclass
class DevicesSummary:
    """Podsumowanie pliku urządzeń w raporcie importu."""

    devices_count: int
    actions_count: int
    categories: list[str]
    consumption_kwh: float
    # Energia wyprodukowana przez PV jako liczba dodatnia; nie pomniejsza zużycia w wycenie.
    pv_production_kwh: float


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
    devices: DevicesSummary | None = None

    def add_skipped(self, rows: pd.Series) -> None:
        self.skipped_count = int(rows.size)
        self.skipped_examples = [
            SkippedRow(row=int(row), reason=reason)
            for row, reason in rows.sort_index().head(MAX_SKIPPED_EXAMPLES).items()
        ]

    def to_dict(self) -> dict:
        report = {
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
        if self.devices is not None:
            report["devices"] = asdict(self.devices)
        return report

    @staticmethod
    def _example(item: SkippedRow) -> dict:
        example = {"row": item.row, "reason": item.reason}
        if item.action_id is not None:
            example["action_id"] = item.action_id
        return example


@dataclass
class ParsedEnergyFile:
    data: pd.DataFrame
    resolution_minutes: int
    report: ImportReport
    # Tylko plik urządzeń: urządzenia z programami i akcjami, obok zagregowanej serii w data.
    devices: list[DeviceRecord] | None = None


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
