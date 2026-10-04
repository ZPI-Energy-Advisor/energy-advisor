from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict



class SimulationResultResponse(BaseModel):
    status: str
    simulation_id: str | None = None
    created_at: datetime | None = None
    results: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class UploadSimulationResponse(BaseModel):
    status: str
    simulation_id: str
    file_name: str
    summary: dict[str, Any]
    message: str
