from datetime import date, datetime

from pydantic import BaseModel


class WeatherPlane(BaseModel):
    tilt: int
    azimuth: int


class WeatherInterval(BaseModel):
    start: datetime
    source: str | None
    temperature_c: float | None
    cloud_cover_pct: int | None
    ghi_w_m2: float | None
    tilted_w_m2: list[float | None]


class WeatherDayResponse(BaseModel):
    date: date
    latitude: float
    longitude: float
    location_approximate: bool
    interval_minutes: int = 15
    planes: list[WeatherPlane]
    fetched_at: datetime | None
    complete: bool
    intervals: list[WeatherInterval]
