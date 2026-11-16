"""Przebieg planu dnia w symulacji Smart Home"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.smart_home import HomeReplay, HubCommandStatus


class PlanRunRequest(BaseModel):
    plan_id: UUID


class PlanRunActionOut(BaseModel):
    """Pozycja planu wysłana do huba i wynik jej komendy (`rejected` z powodem w `code` i `detail`)."""

    action_id: str
    device_id: str
    device_name: str
    kind: str
    label: str | None = None
    start: datetime
    end: datetime
    energy_kwh: float
    status: HubCommandStatus
    code: str | None = None
    detail: str | None = None


class PlanRunDeviceOut(BaseModel):
    """Urządzenie z planu: energia według planu i zużyta w symulacji od początku planu do `sim_time`."""

    device_id: str
    device_name: str
    kind: str
    planned_kwh: float
    actual_kwh: float
    actions: list[PlanRunActionOut]


class PlanRunErrorOut(BaseModel):
    """Awaria urządzenia w trakcie przebiegu, np. komenda, której urządzenie nie wykonało o `start_at`."""

    device_id: str
    device_name: str
    sim_time: datetime
    code: str
    message: str


class PlanRunOut(BaseModel):
    id: UUID
    plan_id: UUID
    plan_date: date
    status: Literal["running", "completed", "ended", "superseded"]
    simulation_id: str
    started_at: datetime
    ended_at: datetime | None = None
    # Bieżący czas symulacji przebiegu, a po jego końcu chwila, w której się skończył.
    sim_time: datetime | None = None
    horizon_start: datetime
    horizon_end: datetime
    # Pompa ciepła i bojler odznaczone w planie pracują jak w tym dniu historii; None, gdy nie ma czego odtwarzać.
    history_day: date | None = None
    replay: HomeReplay
    # Urządzenia spoza planu, które odtwarzają historię (device_id): ekran pokazuje je obok urządzeń planu.
    replayed_devices: list[str] = []
    planned_kwh: float
    actual_kwh: float
    devices: list[PlanRunDeviceOut]
    # Najnowsze najpierw, najwyżej kilkadziesiąt.
    errors: list[PlanRunErrorOut] = []
