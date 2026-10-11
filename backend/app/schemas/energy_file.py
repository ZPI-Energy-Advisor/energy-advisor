from datetime import date, datetime
from typing import Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, computed_field



class EnergyDataFileOut(BaseModel):
    id: UUID
    file_name: str
    uploaded_at: datetime
    data_start: date | None = None
    data_end: date | None = None
    records_count: int | None = None
    status: str
    error_message: str | None = None

    model_config = ConfigDict(from_attributes=True)

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


class EnergyDataFileListResponse(BaseModel):
    items: list[EnergyDataFileOut]
    page: int
    page_size: int
    total: int
    total_pages: int


class EnergyDataFileDataResponse(BaseModel):
    status: str
    file: EnergyDataFileOut
    simulation_id: str
    created_at: datetime | None = None
    # Zakres dat, którego dotyczą wyniki (oba końce włącznie).
    date_from: date | None = None
    date_to: date | None = None
    results: dict[str, Any]
