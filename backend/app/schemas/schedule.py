from datetime import date, datetime

from pydantic import BaseModel


class ScheduledActionOut(BaseModel):
    action_id: str
    device_id: str
    device_name: str
    program_name: str | None = None
    original_start: datetime
    original_end: datetime
    start: datetime
    end: datetime
    energy_kwh: float
    cost_before: float | None = None
    cost_after: float | None = None
    status: str
    reason: str | None = None


class SchedulePriceOut(BaseModel):
    start: datetime
    price_pln_kwh: float


class ScheduleResponse(BaseModel):
    date_from: date
    date_to: date
    cost_before: float
    cost_after: float
    actions: list[ScheduledActionOut]
    prices: list[SchedulePriceOut]
