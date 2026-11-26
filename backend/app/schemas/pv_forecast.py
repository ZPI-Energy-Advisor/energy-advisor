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
    candidate_days: int = 0


class PvDataPeriodOut(BaseModel):
    first_day: date
    last_day: date


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


class PvArrayOut(BaseModel):
    kwp: float
    tilt: int
    azimuth: int


class PvInstallationOut(BaseModel):
    total_kwp: float
    arrays: list[PvArrayOut]
    inverter_kw: float | None
    estimated: bool
    settlement: Literal["net_billing", "net_metering"]
    price_type: Literal["RCE", "RCEm"] | None
    k_factor: float | None


class PvDaySummaryOut(BaseModel):
    date: date
    available: bool
    total_kwh: float | None
    cloud_cover_pct: int | None
    temperature_min_c: float | None
    temperature_max_c: float | None
    basis: Literal["weather", "recent_days", "mixed"] | None
    complete: bool


class PvOverviewResponse(BaseModel):
    installation: PvInstallationOut
    location_label: str | None
    approximate_location: bool
    calibration: PvCalibrationOut
    days: list[PvDaySummaryOut]
    first_data_day: date | None
    last_data_day: date | None
    data_periods: list[PvDataPeriodOut]
    today: date
    latest_day: date


class PvIntervalOut(BaseModel):
    start: datetime
    model_kwh: float | None
    actual_kwh: float | None
    consumption_kwh: float | None
    cloud_cover_pct: int | None
    temperature_c: float | None


class PvValueOut(BaseModel):
    self_pln: float
    export_pln: float
    purchase_price: float | None
    export_price: float | None
    export_price_estimated: bool


class PvBalanceOut(BaseModel):
    production_kwh: float
    consumption_kwh: float
    self_kwh: float
    export_kwh: float
    import_kwh: float
    value: PvValueOut | None


class PvTypicalOut(BaseModel):
    days: int
    first_day: date
    last_day: date
    kind: Literal["workday", "weekend", "all"]


class PvDayResponse(BaseModel):
    date: date
    kind: Literal["past", "today", "future"]
    model_kwh: float | None
    actual_kwh: float | None
    consumption_kwh: float | None
    consumption_source: Literal["devices", "meter", "meter_without_pv", "typical"] | None
    weather_source: str | None
    weather_fetched_at: datetime | None
    basis: Literal["weather", "recent_days", "mixed"] | None
    balance: PvBalanceOut | None
    typical: PvTypicalOut | None
    notes: list[str]
    interval_minutes: int = 15
    intervals: list[PvIntervalOut]


class PvAccuracyDayOut(BaseModel):
    date: date
    actual_kwh: float
    model_kwh: float


class PvAccuracyResponse(BaseModel):
    calibration: PvCalibrationOut
    days: list[PvAccuracyDayOut]
    days_without_weather: int
