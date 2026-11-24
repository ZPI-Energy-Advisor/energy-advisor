import logging
import statistics
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.providers.prices.base import MARKET_TIMEZONE, local_day_bounds_utc
from app.providers.weather import Plane
from app.repositories.device_repository import DeviceRepository
from app.schemas.user_profile import PVInstallation, UserProfile, pv_installation
from app.services.weather_service import Cell, DayWeather, WeatherService, WeatherUnavailableError

logger = logging.getLogger(__name__)

QUARTER_HOURS = 0.25
DEFAULT_COEFFICIENT = 0.8
COEFFICIENT_RANGE = (0.4, 1.1)
TEMPERATURE_COEFFICIENT = -0.004
CELL_HEATING_PER_W_M2 = 0.03
MIN_CALIBRATION_DAYS = 3
MIN_DAY_KWH = 0.5
OUTLIER_RANGE = (0.5, 1.5)
CLIPPED_SHARE = 0.98
FALLBACK_DAYS = 7
CALIBRATION_CACHE_SIZE = 256
_calibrations: OrderedDict = OrderedDict()
_calibrations_lock = threading.Lock()


@dataclass(frozen=True)
class PvArray:
    kwp: float
    plane: Plane


@dataclass
class Calibration:
    coefficient: float
    source: str
    days: int = 0
    mape: float | None = None
    note: str | None = None


@dataclass
class PvQuarter:
    start: datetime
    kwh: float
    basis: str | None


@dataclass
class PvForecast:
    day: date
    quarters: list[PvQuarter]
    calibration: Calibration
    inverter_kw: float | None
    estimated_installation: bool
    approximate_location: bool
    weather_fetched_at: datetime | None
    notes: list[str] = field(default_factory=list)
    weather: DayWeather | None = None

    @property
    def total_kwh(self) -> float:
        return round(sum(quarter.kwh for quarter in self.quarters), 2)

    @property
    def complete(self) -> bool:
        return all(quarter.basis is not None for quarter in self.quarters)

    @property
    def basis(self) -> str:
        sources = {quarter.basis for quarter in self.quarters if quarter.basis}
        if sources == {"weather"}:
            return "weather"
        return "recent_days" if sources == {"recent_days"} else "mixed"


class NoPvInstallationError(Exception):
    pass


class PvForecastUnavailableError(Exception):
    pass


def arrays_of(installation: PVInstallation) -> list[PvArray]:
    return [PvArray(array.power_kwp, Plane.of(array.tilt, array.azimuth)) for array in installation.arrays]


def planes_of_arrays(arrays: list[PvArray]) -> list[Plane]:
    return sorted({array.plane for array in arrays})


def dc_kw(arrays: list[PvArray], planes: list[Plane], tilted: list[float | None], temperature: float | None) -> float | None:
    by_plane = dict(zip(planes, tilted))
    power = 0.0
    for array in arrays:
        irradiance = by_plane.get(array.plane)
        if irradiance is None:
            return None
        if irradiance <= 0:
            continue
        thermal = 1.0
        if temperature is not None:
            thermal = 1 + TEMPERATURE_COEFFICIENT * (temperature + CELL_HEATING_PER_W_M2 * irradiance - 25)
        power += array.kwp * irradiance / 1000 * thermal
    return power


def ac_kwh(dc: float, coefficient: float, inverter_kw: float | None) -> float:
    power = dc * coefficient
    if inverter_kw:
        power = min(power, inverter_kw)
    return power * QUARTER_HOURS


def calibrate(
    arrays: list[PvArray],
    planes: list[Plane],
    production: dict[datetime, float],
    weather: dict[date, DayWeather],
    inverter_kw: float | None,
) -> Calibration:
    """Współczynnik sprawności z produkcji falownika: suma produkcji / suma modelu bez współczynnika, z dni
    z pełną pogodą. Dni z produkcją odstającą od mediany (śnieg, awaria) i kwadranse na limicie falownika
    są pomijane. Błąd (MAPE) liczymy metodą „bez jednego dnia”: dzień nie uczy współczynnika, którym go oceniamy."""
    if not production:
        return Calibration(DEFAULT_COEFFICIENT, "default", note="Brak pliku urządzeń z produkcją falownika.")
    limit = inverter_kw * QUARTER_HOURS * CLIPPED_SHARE if inverter_kw else None
    days: dict[date, list[float]] = {}
    for day, day_weather in weather.items():
        actual = model = 0.0
        usable = True
        for quarter in day_weather.quarters:
            dc = dc_kw(arrays, planes, quarter.tilted_w_m2, quarter.temperature_c)
            if dc is None:
                usable = False
                break
            produced = production.get(quarter.start, 0.0)
            if limit is not None and produced >= limit:
                continue
            actual += produced
            model += dc * QUARTER_HOURS
        if usable and model >= MIN_DAY_KWH and actual > 0:
            days[day] = [actual, model]
    if not days:
        return Calibration(DEFAULT_COEFFICIENT, "default",
                           note="Brak pogody dla dni z produkcją z pliku; pobierze się w tle.")
    median = statistics.median(actual / model for actual, model in days.values())
    kept = {day: values for day, values in days.items()
            if OUTLIER_RANGE[0] * median <= values[0] / values[1] <= OUTLIER_RANGE[1] * median}
    if len(kept) < MIN_CALIBRATION_DAYS:
        return Calibration(DEFAULT_COEFFICIENT, "default", days=len(kept),
                           note=f"Za mało dni z produkcją i pogodą do kalibracji ({len(kept)}, potrzeba {MIN_CALIBRATION_DAYS}).")
    total_actual = sum(actual for actual, _ in kept.values())
    total_model = sum(model for _, model in kept.values())
    errors = [
        abs((total_actual - actual) / (total_model - model) * model - actual) / actual
        for actual, model in kept.values()
    ]
    coefficient = total_actual / total_model
    note = None
    low, high = COEFFICIENT_RANGE
    if not low <= coefficient <= high:
        note = (f"Produkcja z pliku nie pasuje do paneli z profilu (współczynnik {coefficient:.2f}). "
                "Sprawdź moc, kierunek i nachylenie paneli.")
        coefficient = min(max(coefficient, low), high)
    return Calibration(round(coefficient, 3), "history", days=len(kept), mape=round(sum(errors) / len(errors), 3), note=note)


def _wall_clock(moment: datetime) -> tuple[int, int]:
    local = moment.astimezone(MARKET_TIMEZONE)
    return local.hour, local.minute


def recent_profile(weather: dict[date, DayWeather], arrays: list[PvArray], planes: list[Plane]) -> dict[tuple[int, int], float]:
    """Średnia moc DC z ostatnich dni dla każdej godziny zegarowej: zapas, gdy pogody na dany dzień nie ma."""
    sums: dict[tuple[int, int], list[float]] = defaultdict(list)
    for day_weather in weather.values():
        for quarter in day_weather.quarters:
            dc = dc_kw(arrays, planes, quarter.tilted_w_m2, quarter.temperature_c)
            if dc is not None:
                sums[_wall_clock(quarter.start)].append(dc)
    return {clock: sum(values) / len(values) for clock, values in sums.items()}


def clear_calibrations() -> None:
    with _calibrations_lock:
        _calibrations.clear()


class PvForecastService:
    def __init__(self, weather: WeatherService, devices: DeviceRepository):
        self.weather = weather
        self.devices = devices

    def forecast(self, user_id, profile: UserProfile, day: date) -> PvForecast:
        installation = pv_installation(profile.pv_config)
        if installation is None:
            raise NoPvInstallationError("Profil nie ma instalacji PV.")
        location = profile.base_info.location
        if location is None:
            raise PvForecastUnavailableError("Profil nie ma lokalizacji domu.")
        cell = Cell.of(location)
        arrays = arrays_of(installation)
        planes = planes_of_arrays(arrays)
        inverter_kw = installation.inverter_power_kw or self.devices.pv_inverter_kw(user_id)
        notes = []

        try:
            day_weather = self.weather.day(cell, day, planes)
        except WeatherUnavailableError:
            day_weather = None

        fallback = None
        if day_weather is None or not all(
            dc_kw(arrays, planes, q.tilted_w_m2, q.temperature_c) is not None for q in day_weather.quarters
        ):
            recent_days = [day - timedelta(days=offset) for offset in range(1, FALLBACK_DAYS + 1)]
            fallback = recent_profile(self.weather.stored_days(cell, recent_days, planes), arrays, planes)
            if not fallback and day_weather is None:
                raise PvForecastUnavailableError(f"Brak pogody na {day} i na {FALLBACK_DAYS} dni wcześniej.")
            notes.append(
                "Brak części pogody na ten dzień: brakujące kwadranse są średnią z ostatnich dni."
                if fallback else "Brak części pogody na ten dzień: brakujących kwadransów nie liczymy."
            )

        calibration = self._calibration(user_id, cell, arrays, planes, inverter_kw)
        quarters = []
        start, end = local_day_bounds_utc(day)
        weather_quarters = {q.start: q for q in day_weather.quarters} if day_weather else {}
        moment = start
        while moment < end:
            quarter = weather_quarters.get(moment)
            dc = dc_kw(arrays, planes, quarter.tilted_w_m2, quarter.temperature_c) if quarter else None
            basis = "weather"
            if dc is None:
                dc = (fallback or {}).get(_wall_clock(moment))
                basis = "recent_days" if dc is not None else None
            kwh = ac_kwh(dc, calibration.coefficient, inverter_kw) if dc is not None else 0.0
            quarters.append(PvQuarter(moment, round(kwh, 4), basis))
            moment += timedelta(minutes=15)

        if installation.estimated:
            notes.append("Parametry paneli są szacunkowe, więc prognoza jest orientacyjna.")
        if location.approximate:
            notes.append("Lokalizacja domu jest przybliżona do regionu pocztowego; pogoda może się różnić.")
        if calibration.note:
            notes.append(calibration.note)
        return PvForecast(
            day=day,
            quarters=quarters,
            calibration=calibration,
            inverter_kw=inverter_kw,
            estimated_installation=installation.estimated,
            approximate_location=location.approximate,
            weather_fetched_at=day_weather.fetched_at if day_weather else None,
            notes=notes,
            weather=day_weather,
        )

    def _calibration(self, user_id, cell: Cell, arrays: list[PvArray], planes: list[Plane],
                     inverter_kw: float | None) -> Calibration:
        hour = self.weather.now().replace(minute=0, second=0, microsecond=0)
        key = (user_id, cell, tuple(arrays), inverter_kw, self.devices.completed_file_ids(user_id), hour)
        with _calibrations_lock:
            if key in _calibrations:
                _calibrations.move_to_end(key)
                return _calibrations[key]
        calibration = self._calibrate(user_id, cell, arrays, planes, inverter_kw)
        if calibration.source != "history":
            return calibration
        with _calibrations_lock:
            _calibrations[key] = calibration
            while len(_calibrations) > CALIBRATION_CACHE_SIZE:
                _calibrations.popitem(last=False)
        return calibration

    def _calibrate(self, user_id, cell: Cell, arrays: list[PvArray], planes: list[Plane],
                   inverter_kw: float | None) -> Calibration:
        production = self.devices.pv_production(user_id)
        days = {moment.astimezone(MARKET_TIMEZONE).date() for moment in production}
        days = {day for day in days if day < self.weather.today()}
        weather = self.weather.stored_days(cell, days, planes) if days else {}
        return calibrate(arrays, planes, production, weather, inverter_kw)

    def setup(self, user_id, profile: UserProfile) -> "PvSetup":
        installation = pv_installation(profile.pv_config)
        if installation is None:
            raise NoPvInstallationError("Profil nie ma instalacji PV.")
        location = profile.base_info.location
        if location is None:
            raise PvForecastUnavailableError("Profil nie ma lokalizacji domu.")
        arrays = arrays_of(installation)
        planes = planes_of_arrays(arrays)
        cell = Cell.of(location)
        inverter_kw = installation.inverter_power_kw or self.devices.pv_inverter_kw(user_id)
        calibration = self._calibration(user_id, cell, arrays, planes, inverter_kw)
        return PvSetup(installation, cell, arrays, planes, inverter_kw, calibration)

    def modeled(self, setup: "PvSetup", days) -> dict[date, dict[datetime, float]]:
        """Produkcja z modelu z pogody zapisanej w bazie (bez pobierania), dla dni z pełną pogodą."""
        result = {}
        for day, day_weather in self.weather.stored_days(setup.cell, days, setup.planes).items():
            quarters = {}
            for quarter in day_weather.quarters:
                dc = dc_kw(setup.arrays, setup.planes, quarter.tilted_w_m2, quarter.temperature_c)
                if dc is None:
                    break
                quarters[quarter.start] = ac_kwh(dc, setup.calibration.coefficient, setup.inverter_kw)
            else:
                result[day] = quarters
        return result

    def accuracy(self, user_id, setup: "PvSetup") -> list[tuple[date, float, float]]:
        """Dni z produkcją falownika z plików: (dzień, produkcja z pliku, produkcja z modelu) w kWh."""
        production = self.devices.pv_production(user_id)
        actual: dict[date, float] = defaultdict(float)
        for moment, kwh in production.items():
            actual[moment.astimezone(MARKET_TIMEZONE).date()] += kwh
        days = [day for day in actual if day < self.weather.today()]
        modeled = self.modeled(setup, days)
        return [
            (day, round(actual[day], 2), round(sum(modeled[day].values()), 2))
            for day in sorted(modeled)
        ]


@dataclass
class PvSetup:
    installation: PVInstallation
    cell: Cell
    arrays: list[PvArray]
    planes: list[Plane]
    inverter_kw: float | None
    calibration: Calibration
