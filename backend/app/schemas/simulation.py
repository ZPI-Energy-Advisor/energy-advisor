from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict

from app.schemas.smart_home import HomeSync



class SimulationResultResponse(BaseModel):
    status: str
    simulation_id: str | None = None
    created_at: datetime | None = None
    results: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class UploadSimulationResponse(BaseModel):
    status: str
    simulation_id: str
    file_id: str
    file_name: str
    summary: dict[str, Any]
    import_report: dict[str, Any] | None = None
    # Wysyłka rejestru do huba, gdy plik wgrał właściciel podłączonego domu.
    home_sync: HomeSync | None = None
    message: str
