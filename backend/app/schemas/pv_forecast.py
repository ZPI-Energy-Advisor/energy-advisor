from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class PvForecastQuarter(BaseModel):
    start: datetime
    kwh: float
    basis: Literal["weather", "recent_days"] | None


class PvCalibrationOut(BaseModel):
    coefficient: float
    source: Literal["history", "default"]
    days: int
    mape: float | None


class PvForecastResponse(BaseModel):
    date: date
    total_kwh: float
    complete: bool
    basis: Literal["weather", "recent_days", "mixed"]
    calibration: PvCalibrationOut
    inverter_kw: float | None
    estimated_installation: bool
    approximate_location: bool
    weather_fetched_at: datetime | None
    notes: list[str]
    interval_minutes: int = 15
    intervals: list[PvForecastQuarter]
