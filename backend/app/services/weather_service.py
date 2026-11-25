import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Iterable

from app.models.WeatherObservation import WeatherObservation
from app.providers import weather as weather_provider
from app.providers.prices.base import MARKET_TIMEZONE, expected_intervals, local_day_bounds_utc
from app.providers.weather import Plane, WeatherProviderError
from app.repositories.weather_repository import WeatherRepository
from app.schemas.user_profile import HomeLocation, UserProfile, pv_installation

logger = logging.getLogger(__name__)

QUARTER = timedelta(minutes=15)
FORECAST_DAYS_AHEAD = 2
FORECAST_MAX_AGE = timedelta(hours=3)
FORECAST_PAST_DAYS = 60
FORECAST_RETENTION_DAYS = 100
ARCHIVE_DELAY_DAYS = 6
ARCHIVE_CHUNK_DAYS = 366
FORECAST_CHUNK_DAYS = 31
EARLIEST_DAY = date(2000, 1, 1)
INTERACTIVE_RETRY = timedelta(minutes=5)
ATTEMPTS_LIMIT = 10_000
_attempts: dict[tuple, float] = {}
_attempts_lock = threading.Lock()


def clear_fetch_attempts() -> None:
    with _attempts_lock:
        _attempts.clear()


@dataclass(frozen=True)
class Cell:
    latitude: Decimal
    longitude: Decimal

    @classmethod
    def of(cls, location: HomeLocation) -> "Cell":
        return cls(Decimal(f"{location.latitude:.1f}"), Decimal(f"{location.longitude:.1f}"))


def planes_of(profile: UserProfile) -> list[Plane]:
    installation = pv_installation(profile.pv_config)
    if installation is None:
        return []
    return sorted({Plane.of(array.tilt, array.azimuth) for array in installation.arrays})


@dataclass
class Quarter:
    start: datetime
    source: str | None
    temperature_c: float | None
    cloud_cover_pct: int | None
    ghi_w_m2: float | None
    tilted_w_m2: list[float | None]


@dataclass
class DayWeather:
    day: date
    cell: Cell
    planes: list[Plane]
    quarters: list[Quarter]
    fetched_at: datetime | None

    @property
    def complete(self) -> bool:
        # Komplet do prognozy PV: każdy kwadrans ma GHI i promieniowanie na każdą płaszczyznę paneli z profilu
        # (jak `_usable`). Sama GHI nie wystarcza, bo np. po dodaniu grupy paneli może brakować jej promieniowania.
        return all(
            quarter.ghi_w_m2 is not None and all(value is not None for value in quarter.tilted_w_m2)
            for quarter in self.quarters
        )


class WeatherUnavailableError(Exception):
    pass


def _days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def _ranges(days: Iterable[date], chunk_days: int) -> list[tuple[date, date]]:
    ranges: list[tuple[date, date]] = []
    for day in sorted(set(days)):
        if ranges and day - ranges[-1][1] == timedelta(days=1) and (day - ranges[-1][0]).days < chunk_days:
            ranges[-1] = (ranges[-1][0], day)
        else:
            ranges.append((day, day))
    return ranges


def _quarters(day: date) -> list[datetime]:
    start, _ = local_day_bounds_utc(day)
    return [start + QUARTER * index for index in range(expected_intervals(day))]


def _by_quarter(rows: Iterable[WeatherObservation]) -> dict[datetime, WeatherObservation]:
    covered = {}
    for row in rows:
        start = row.interval_start.astimezone(timezone.utc)
        for index in range(row.interval_minutes // 15):
            covered[start + QUARTER * index] = row
    return covered


def _settled_at(day: date) -> datetime:
    _, end = local_day_bounds_utc(day)
    return end + timedelta(days=ARCHIVE_DELAY_DAYS)


def _usable(row: WeatherObservation, planes: list[Plane]) -> bool:
    return row.ghi_w_m2 is not None and all(plane.key in (row.tilted_w_m2 or {}) for plane in planes)


def _number(value) -> float | None:
    return float(value) if value is not None else None


class WeatherService:
    def __init__(
        self,
        repository: WeatherRepository,
        client=None,
        now: Callable[[], datetime] | None = None,
        interactive: bool = False,
    ):
        self.repository = repository
        self._client = client
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.interactive = interactive

    @property
    def client(self):
        if self._client is None:
            factory = weather_provider.interactive_client if self.interactive else weather_provider.default_client
            self._client = factory()
        return self._client

    def today(self) -> date:
        return self.now().astimezone(MARKET_TIMEZONE).date()

    def latest_day(self) -> date:
        return self.today() + timedelta(days=FORECAST_DAYS_AHEAD)

    def day(self, cell: Cell, day: date, planes: list[Plane]) -> DayWeather:
        rows = self._rows(cell, day, day)
        if self._needs_fetch(day, rows, planes) and self._may_fetch(cell, *self._fetch_window(day), planes):
            first, last = self._fetch_window(day)
            try:
                self.fetch(cell, first, last, planes)
                rows = self._rows(cell, day, day)
            except WeatherProviderError as error:
                logger.warning("Nie udało się pobrać pogody na %s: %s", day, error)
        result = self._assemble(cell, day, planes, rows)
        if all(quarter.source is None for quarter in result.quarters):
            raise WeatherUnavailableError(f"Brak pogody na {day}")
        return result

    def _may_fetch(self, cell: Cell, first: date, last: date, planes: list[Plane]) -> bool:
        """Zapytanie użytkownika pobiera ten sam zakres najwyżej raz na INTERACTIVE_RETRY. Bez tego dzień, którego
        Open-Meteo jeszcze nie ma (np. archiwum sprzed kilku dni), pytałby o niego przy każdym kliknięciu."""
        if not self.interactive:
            return True
        key = (cell, first, last, tuple(planes))
        now = time.monotonic()
        with _attempts_lock:
            last_attempt = _attempts.get(key)
            if last_attempt is not None and now - last_attempt < INTERACTIVE_RETRY.total_seconds():
                return False
            _attempts[key] = now
            if len(_attempts) > ATTEMPTS_LIMIT:
                for stale in [k for k, at in _attempts.items() if now - at >= INTERACTIVE_RETRY.total_seconds()]:
                    del _attempts[stale]
        return True

    def stored_days(self, cell: Cell, days: Iterable[date], planes: list[Plane]) -> dict[date, DayWeather]:
        days = sorted(set(days))
        if not days:
            return {}
        start, _ = local_day_bounds_utc(days[0])
        _, end = local_day_bounds_utc(days[-1])
        by_day: dict[date, list[WeatherObservation]] = {day: [] for day in days}
        for row in self.repository.between(cell.latitude, cell.longitude, start, end):
            day = row.interval_start.astimezone(MARKET_TIMEZONE).date()
            if day in by_day:
                by_day[day].append(row)
        return {day: self._assemble(cell, day, planes, rows) for day, rows in by_day.items()}

    def _fetch_window(self, day: date) -> tuple[date, date]:
        today = self.today()
        if day >= today:
            return today, self.latest_day()
        first = day.replace(day=1)
        last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return first, min(last, today - timedelta(days=1))

    def refresh_forecast(self, cell: Cell, planes: list[Plane]) -> int:
        return self.fetch(cell, self.today(), self.latest_day(), planes)

    def ensure_forecast(self, cell: Cell, planes: list[Plane]) -> int:
        rows = self._rows(cell, self.today(), self.latest_day())
        if not any(self._needs_fetch(day, rows, planes) for day in _days(self.today(), self.latest_day())):
            return 0
        return self.refresh_forecast(cell, planes)

    def ensure_history(self, cell: Cell, days: Iterable[date], planes: list[Plane]) -> int:
        today = self.today()
        past = sorted({day for day in days if EARLIEST_DAY <= day < today})
        if not past:
            return 0
        archive, forecast = self._split(self._rows(cell, past[0], past[-1]))
        needed = []
        for day in past:
            settled = self.now() >= _settled_at(day)
            if self._complete(archive, day, planes):
                if settled and not self._final(archive, day):
                    needed.append(day)
            elif settled or not self._complete(forecast, day, planes):
                needed.append(day)
        return sum(self.fetch(cell, first, last, planes) for first, last in _ranges(needed, ARCHIVE_CHUNK_DAYS))

    def fetch(self, cell: Cell, first: date, last: date, planes: list[Plane]) -> int:
        today = self.today()
        first = max(first, EARLIEST_DAY)
        last = min(last, self.latest_day())
        if first > last:
            return 0
        stored = 0
        past_last = min(last, today - timedelta(days=1))
        if first <= past_last:
            for start, end in _ranges(_days(first, past_last), ARCHIVE_CHUNK_DAYS):
                stored += self._store(cell, WeatherObservation.SOURCE_ARCHIVE, start, end, planes)
            archive, forecast = self._split(self._rows(cell, first, past_last))
            fallback = [
                day for day in _days(max(first, today - timedelta(days=FORECAST_PAST_DAYS)), past_last)
                if not self._complete(archive, day, planes) and not self._complete(forecast, day, planes)
            ]
            for start, end in _ranges(fallback, FORECAST_CHUNK_DAYS):
                stored += self._store(cell, WeatherObservation.SOURCE_FORECAST, start, end, planes)
        if last >= today:
            stored += self._store(cell, WeatherObservation.SOURCE_FORECAST, max(first, today), last, planes)
        return stored

    def prune(self) -> int:
        start, _ = local_day_bounds_utc(self.today() - timedelta(days=FORECAST_RETENTION_DAYS))
        return self.repository.delete_forecasts_before(start)

    def _store(self, cell: Cell, source: str, first: date, last: date, planes: list[Plane]) -> int:
        fetch = self.client.archive if source == WeatherObservation.SOURCE_ARCHIVE else self.client.forecast
        fetched_at = self.now()
        points = fetch(float(cell.latitude), float(cell.longitude), first - timedelta(days=1), last, planes)
        start, _ = local_day_bounds_utc(first)
        _, end = local_day_bounds_utc(last)
        points = [point for point in points if start <= point.interval_start < end]
        return self.repository.upsert(cell.latitude, cell.longitude, source, points, fetched_at)

    def _rows(self, cell: Cell, first: date, last: date) -> list[WeatherObservation]:
        start, _ = local_day_bounds_utc(first)
        _, end = local_day_bounds_utc(last)
        return self.repository.between(cell.latitude, cell.longitude, start, end)

    @staticmethod
    def _split(rows: list[WeatherObservation]) -> tuple[dict, dict]:
        return (
            _by_quarter(row for row in rows if row.source == WeatherObservation.SOURCE_ARCHIVE),
            _by_quarter(row for row in rows if row.source == WeatherObservation.SOURCE_FORECAST),
        )

    @staticmethod
    def _complete(covered: dict[datetime, WeatherObservation], day: date, planes: list[Plane]) -> bool:
        return all(quarter in covered and _usable(covered[quarter], planes) for quarter in _quarters(day))

    @staticmethod
    def _final(archive: dict[datetime, WeatherObservation], day: date) -> bool:
        return all(archive[quarter].fetched_at >= _settled_at(day) for quarter in _quarters(day))

    def _needs_fetch(self, day: date, rows: list[WeatherObservation], planes: list[Plane]) -> bool:
        archive, forecast = self._split(rows)
        if day < self.today():
            return not (self._complete(archive, day, planes) or self._complete(forecast, day, planes))
        if not self._complete(forecast, day, planes):
            return True
        oldest = min(row.fetched_at for row in rows if row.source == WeatherObservation.SOURCE_FORECAST)
        return self.now() - oldest > FORECAST_MAX_AGE

    def _assemble(self, cell: Cell, day: date, planes: list[Plane], rows: list[WeatherObservation]) -> DayWeather:
        archive, forecast = self._split(rows)
        preferred, other = (archive, forecast) if day < self.today() else (forecast, archive)
        keys = [plane.key for plane in planes]
        values: dict[int, tuple] = {}

        def read(row) -> tuple:
            cached = values.get(id(row))
            if cached is None:
                tilted = row.tilted_w_m2 or {}
                cached = values[id(row)] = (
                    row.ghi_w_m2 is not None and all(key in tilted for key in keys),
                    _number(row.temperature_c),
                    _number(row.ghi_w_m2),
                    [_number(tilted.get(key)) for key in keys],
                )
            return cached

        quarters, fetched = [], []
        for start in _quarters(day):
            first, second = preferred.get(start), other.get(start)
            row = first if first is not None and read(first)[0] else second if second is not None and read(second)[0] else first or second
            if row is None:
                quarters.append(Quarter(start, None, None, None, None, [None] * len(planes)))
                continue
            if row.source == WeatherObservation.SOURCE_FORECAST:
                fetched.append(row.fetched_at)
            _, temperature, ghi, tilted = read(row)
            quarters.append(Quarter(start, row.source, temperature, row.cloud_cover_pct, ghi, list(tilted)))
        return DayWeather(day, cell, planes, quarters, min(fetched) if fetched else None)
