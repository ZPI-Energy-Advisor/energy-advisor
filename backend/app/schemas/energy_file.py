from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, computed_field


ALL_FILES_SOURCE_ID = "all"
ALL_FILES_SOURCE_NAME = "Wszystkie pliki"
ALL_DEVICE_FILES_SOURCE_ID = "all-devices"
ALL_DEVICE_FILES_SOURCE_NAME = "Wszystkie pliki urządzeń"

AggregateSourceId = Literal["all", "all-devices"]


class _DateRangeMixin(BaseModel):
    file_name: str
    data_start: date | None = None
    data_end: date | None = None

    @computed_field
    @property
    def days_count(self) -> int | None:
        if self.data_start is None or self.data_end is None:
            return None
        return (self.data_end - self.data_start).days + 1

    @computed_field
    @property
    def label(self) -> str:
        if self.data_start is None or self.data_end is None:
            return self.file_name
        return f"{self.file_name} ({self.data_start:%d.%m.%Y} – {self.data_end:%d.%m.%Y})"


class EnergyDataFileOut(_DateRangeMixin):
    id: UUID
    uploaded_at: datetime
    records_count: int | None = None
    source_type: str
    status: str
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AggregateSourceSummary(_DateRangeMixin):
    """Wirtualne źródło zbiorcze na liście plików - zakres to suma zakresów plików jednego typu."""

    id: AggregateSourceId
    source_type: str
    files_count: int


class AggregateSourceFile(BaseModel):
    id: UUID
    file_name: str
    uploaded_at: datetime
    data_start: date | None = None
    data_end: date | None = None
    # Ile dni / kwadransów w danych zbiorczych pochodzi z tego pliku po rozstrzygnięciu nakładań.
    days_used: int
    slots_used: int


class AggregateSourceOut(_DateRangeMixin):
    id: AggregateSourceId
    source_type: str
    status: str = "completed"
    records_count: int
    files_count: int
    # Pliki, z których składa się źródło zbiorcze, od najstarszego uploadu.
    files: list[AggregateSourceFile]
    # Pliki wgrane przed zapisywaniem serii 15-minutowych - nie da się ich scalić.
    skipped_files: list[AggregateSourceFile] = []


class EnergyDataFileListResponse(BaseModel):
    items: list[EnergyDataFileOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    # "Wszystkie pliki" (pliki licznika) i "Wszystkie pliki urządzeń"; None, gdy brak gotowych plików tego typu.
    aggregate: AggregateSourceSummary | None = None
    devices_aggregate: AggregateSourceSummary | None = None


class EnergyDataFileDataResponse(BaseModel):
    status: str
    file: EnergyDataFileOut | AggregateSourceOut
    # Źródło zbiorcze nie ma jednej symulacji - jest liczone z symulacji wszystkich plików.
    simulation_id: str | None = None
    created_at: datetime | None = None
    # Zakres dat, którego dotyczą wyniki (oba końce włącznie).
    date_from: date | None = None
    date_to: date | None = None
    import_report: dict[str, Any] | None = None
    results: dict[str, Any]
