import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

FORECAST_URL = os.getenv("OPEN_METEO_FORECAST_URL") or "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = os.getenv("OPEN_METEO_ARCHIVE_URL") or "https://archive-api.open-meteo.com/v1/archive"
TIMEOUT_SECONDS = 15.0
INTERACTIVE_TIMEOUT_SECONDS = 8.0
BASE_VARIABLES = ("shortwave_radiation", "temperature_2m", "cloud_cover")
TILTED_VARIABLE = "global_tilted_irradiance"


@dataclass(frozen=True, order=True)
class Plane:
    tilt: int
    azimuth: int

    @classmethod
    def of(cls, tilt: int, azimuth: int) -> "Plane":
        if tilt == 0:
            return cls(0, 0)
        return cls(tilt, 180 if azimuth == -180 else azimuth)

    @property
    def key(self) -> str:
        return f"{self.tilt}/{self.azimuth}"


@dataclass
class WeatherPoint:
    interval_start: datetime
    interval_minutes: int
    temperature_c: float | None = None
    cloud_cover_pct: int | None = None
    ghi_w_m2: float | None = None
    tilted: dict[str, float] = field(default_factory=dict)


class WeatherProviderError(Exception):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class WeatherLimitError(WeatherProviderError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class OpenMeteoClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        forecast_url: str = FORECAST_URL,
        archive_url: str = ARCHIVE_URL,
        max_attempts: int = 3,
        base_delay_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self.forecast_url = forecast_url
        self.archive_url = archive_url
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.sleep = sleep

    def forecast(self, latitude: float, longitude: float, start: date, end: date, planes: list[Plane]) -> list[WeatherPoint]:
        return self._fetch(self.forecast_url, "minutely_15", 15, latitude, longitude, start, end, planes)

    def archive(self, latitude: float, longitude: float, start: date, end: date, planes: list[Plane]) -> list[WeatherPoint]:
        return self._fetch(self.archive_url, "hourly", 60, latitude, longitude, start, end, planes)

    def _fetch(self, url, resolution, minutes, latitude, longitude, start, end, planes) -> list[WeatherPoint]:
        requests = [(plane, index == 0) for index, plane in enumerate(planes or [None])]

        def load(request):
            plane, with_base = request
            variables = (BASE_VARIABLES if with_base else ()) + ((TILTED_VARIABLE,) if plane else ())
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": "GMT",
                resolution: ",".join(variables),
            }
            if plane:
                params |= {"tilt": plane.tilt, "azimuth": plane.azimuth}
            return self._parse(self._get(url, params), resolution, minutes, plane)

        if len(requests) == 1:
            responses = [load(requests[0])]
        else:
            with ThreadPoolExecutor(max_workers=len(requests)) as pool:
                responses = list(pool.map(load, requests))
        merged: dict[datetime, WeatherPoint] = {}
        for points in responses:
            for point in points:
                known = merged.setdefault(point.interval_start, point)
                if known is not point:
                    known.tilted |= point.tilted
        return sorted(merged.values(), key=lambda point: point.interval_start)

    def _get(self, url: str, params: dict) -> dict:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self._request(url, params)
            except WeatherProviderError as error:
                if not error.retryable or attempt == self.max_attempts:
                    raise
                delay = self.base_delay_seconds * 2 ** (attempt - 1)
                logger.warning("Próba %d/%d pobrania pogody nieudana: %s. Ponawiam za %.1fs", attempt, self.max_attempts, error, delay)
                self.sleep(delay)
        raise AssertionError("unreachable")

    def _request(self, url: str, params: dict) -> dict:
        try:
            response = self.client.get(url, params=params)
        except httpx.HTTPError as error:
            raise WeatherProviderError(f"Open-Meteo nie odpowiada: {error}") from error
        if response.status_code == 429:
            raise WeatherLimitError("Przekroczony limit zapytań Open-Meteo")
        if response.status_code >= 500:
            raise WeatherProviderError(f"Open-Meteo zwróciło HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise WeatherProviderError("Open-Meteo zwróciło niepoprawny JSON", retryable=False) from error
        if response.status_code != 200 or not isinstance(payload, dict) or payload.get("error"):
            reason = payload.get("reason") if isinstance(payload, dict) else None
            raise WeatherProviderError(f"Open-Meteo odrzuciło zapytanie: {reason or response.status_code}", retryable=False)
        return payload

    @staticmethod
    def _parse(payload: dict, resolution: str, minutes: int, plane: Plane | None) -> list[WeatherPoint]:
        block = payload.get(resolution)
        if not isinstance(block, dict) or not isinstance(block.get("time"), list):
            raise WeatherProviderError("Odpowiedź Open-Meteo bez danych pogody", retryable=False)
        try:
            times = [datetime.fromisoformat(value).replace(tzinfo=timezone.utc) for value in block["time"]]
        except (TypeError, ValueError) as error:
            raise WeatherProviderError("Open-Meteo zwróciło niepoprawny czas", retryable=False) from error
        index = {moment: position for position, moment in enumerate(times)}
        step = timedelta(minutes=minutes)

        def value(variable: str, moment: datetime) -> float | None:
            series = block.get(variable)
            position = index.get(moment)
            if not isinstance(series, list) or position is None or position >= len(series):
                return None
            number = series[position]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or number != number:
                return None
            return float(number)

        points = []
        for moment in times:
            radiation_at = moment + step
            ghi = value("shortwave_radiation", radiation_at)
            tilted = value(TILTED_VARIABLE, radiation_at) if plane else None
            temperature = value("temperature_2m", moment)
            cloud_cover = value("cloud_cover", moment)
            if ghi is None and temperature is None and tilted is None:
                continue
            points.append(
                WeatherPoint(
                    interval_start=moment,
                    interval_minutes=minutes,
                    temperature_c=temperature,
                    cloud_cover_pct=round(cloud_cover) if cloud_cover is not None else None,
                    ghi_w_m2=ghi,
                    tilted={plane.key: tilted} if plane and tilted is not None else {},
                )
            )
        return points


@lru_cache(maxsize=1)
def default_client() -> OpenMeteoClient:
    return OpenMeteoClient()


@lru_cache(maxsize=1)
def interactive_client() -> OpenMeteoClient:
    return OpenMeteoClient(httpx.Client(timeout=INTERACTIVE_TIMEOUT_SECONDS), max_attempts=1)
