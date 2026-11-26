"""Dane ekranu „Fotowoltaika” (ZP-150): najbliższe dni, szczegóły doby (także z przeszłości) i trafność prognozy.

Doba łączy prognozę albo model z pogody (ZP-118), produkcję i zużycie domu z plików oraz podział produkcji
na autokonsumpcję i oddanie do sieci. Operator bilansuje pobór i oddanie w każdej godzinie, więc dzielimy
w godzinach. Wartość autokonsumpcji to cena z sieci (energia, dystrybucja zmienna, opłaty, VAT), a oddania:
net-billing RCE albo RCEm × 1,23 do depozytu (ujemna cena = 0), net-metering opust × cena z sieci.

Pliki są zawsze łączone: urządzenia jak „Wszystkie pliki urządzeń” (kwadrans urządzenia z najnowszego pliku),
licznik jak „Wszystkie pliki” (przy nakładaniu wygrywa nowszy plik). Dzień z plikiem urządzeń bierze dane
z urządzeń, a pozostałe z licznika.
"""

import logging
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app.models.EnergyDataFile import EnergyDataFile
from app.providers.prices.base import MARKET_TIMEZONE, local_day_bounds_utc
from app.schemas.user_profile import UserProfile
from app.services.pv_forecast import (
    PvForecastService,
    PvForecastUnavailableError,
    PvSetup,
)
from app.services.prosumer import PRICE_LOOKBACK_DAYS, ExportValuation
from app.services.weather_service import DayWeather

logger = logging.getLogger(__name__)

QUARTER = timedelta(minutes=15)
FORECAST_DAYS = 3
TYPICAL_DAYS = 28
TYPICAL_MAX_AGE_DAYS = 60
DAYLIGHT_W_M2 = 1.0
TYPICAL_CACHE_SIZE = 256
NO_DEVICE_DATA = (0.0, 0.0)
_typical_profiles: OrderedDict = OrderedDict()
_typical_lock = threading.Lock()


def clear_typical_profiles() -> None:
    with _typical_lock:
        _typical_profiles.clear()


@dataclass
class DaySummary:
    day: date
    total_kwh: float | None = None
    cloud_cover_pct: int | None = None
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None
    basis: str | None = None
    complete: bool = False
    available: bool = True


@dataclass
class Interval:
    start: datetime
    model_kwh: float | None
    actual_kwh: float | None
    consumption_kwh: float | None
    cloud_cover_pct: int | None
    temperature_c: float | None


@dataclass
class Value:
    self_pln: float
    export_pln: float
    purchase_price: float | None
    export_price: float | None
    export_price_estimated: bool


@dataclass
class Balance:
    production_kwh: float
    consumption_kwh: float
    self_kwh: float
    export_kwh: float
    import_kwh: float
    value: Value | None = None


@dataclass
class Typical:
    days: int
    first_day: date
    last_day: date
    kind: str
    by_clock: dict[tuple[int, int], float]


@dataclass
class DayData:
    consumption: dict[datetime, float]
    actual: dict[datetime, float] | None
    source: str


@dataclass
class DayDetail:
    day: date
    kind: str
    model_kwh: float | None
    actual_kwh: float | None
    consumption_kwh: float | None
    consumption_source: str | None
    weather_source: str | None
    weather_fetched_at: datetime | None
    basis: str | None
    intervals: list[Interval]
    balance: Balance | None
    typical: Typical | None = None
    notes: list[str] = field(default_factory=list)


def _quarters(day: date) -> list[datetime]:
    start, end = local_day_bounds_utc(day)
    count = int((end - start) / QUARTER)
    return [start + QUARTER * index for index in range(count)]


def _naive_local(moment: datetime) -> datetime:
    return moment.astimezone(MARKET_TIMEZONE).replace(tzinfo=None)


def _local_day(moment: datetime) -> date:
    return moment.astimezone(MARKET_TIMEZONE).date()


def _clock(moment: datetime) -> tuple[int, int]:
    local = moment.astimezone(MARKET_TIMEZONE)
    return local.hour, local.minute


def _weather_summary(weather: DayWeather | None) -> tuple[int | None, float | None, float | None]:
    if weather is None:
        return None, None, None
    temperatures = [q.temperature_c for q in weather.quarters if q.temperature_c is not None]
    daylight = [q.cloud_cover_pct for q in weather.quarters
                if q.cloud_cover_pct is not None and (q.ghi_w_m2 or 0) > DAYLIGHT_W_M2]
    cloud = round(sum(daylight) / len(daylight)) if daylight else None
    return (cloud, min(temperatures) if temperatures else None, max(temperatures) if temperatures else None)


def _weather_source(weather: DayWeather | None) -> str | None:
    sources = {q.source for q in weather.quarters if q.source} if weather else set()
    if not sources:
        return None
    return sources.pop() if len(sources) == 1 else "mixed"


def hourly_balance(production: dict[datetime, float], consumption: dict[datetime, float]) -> list[tuple[datetime, float, float, float]]:
    """Bilans godzin jak u operatora: (godzina, autokonsumpcja, oddanie, pobór) w kWh."""
    hours: dict[datetime, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for moment, kwh in production.items():
        hours[moment.replace(minute=0)][0] += kwh
    for moment, kwh in consumption.items():
        hours[moment.replace(minute=0)][1] += kwh
    result = []
    for hour in sorted(hours):
        produced, used = hours[hour]
        own = min(produced, used)
        result.append((hour, own, produced - own, used - own))
    return result


def _kind_of(days: list[date]) -> str:
    kinds = {d.weekday() >= 5 for d in days}
    return "all" if len(kinds) > 1 else "weekend" if True in kinds else "workday"


def device_day(quarters: list[datetime], slots: dict[datetime, tuple[float, float]], inverter_in_file: bool) -> DayData:
    """Doba z pliku urządzeń: zużycie to suma urządzeń poza falownikiem. Gdy falownik jest w pliku, kwadranse bez
    jego wpisu to zero produkcji; bez falownika produkcję bierzemy z modelu."""
    consumption = {q: max(slots.get(q, NO_DEVICE_DATA)[0], 0.0) for q in quarters}
    has_inverter = inverter_in_file or any(produced > 0 for _, produced in slots.values())
    actual = {q: slots.get(q, NO_DEVICE_DATA)[1] for q in quarters} if has_inverter else None
    return DayData(consumption, actual, "devices")


def meter_day(
    quarters: list[datetime],
    readings: dict[datetime, tuple[float, float, object]],
    model: dict[datetime, float],
    files_with_export: set,
) -> DayData | None:
    """Doba z licznika: zużycie = pobór − oddanie + produkcja z modelu, nie mniej niż pobór. Plik, który w całym
    okresie nie ma oddania do sieci, pochodzi sprzed paneli: zużycie to wtedy sam pobór. Godzina powtórzona
    przy zmianie czasu ma w odczytach jeden zsumowany kwadrans, który dzielimy po równo."""
    local = [_naive_local(moment) for moment in quarters]
    found = [readings[moment] for moment in local if moment in readings]
    if not found:
        return None
    without_pv = all(file_id not in files_with_export for _, _, file_id in found)
    counts: dict[datetime, int] = defaultdict(int)
    for moment in local:
        counts[moment] += 1
    consumption = {}
    for moment, naive in zip(quarters, local):
        used, exported, _ = readings.get(naive, (0.0, 0.0, None))
        used, exported = used / counts[naive], exported / counts[naive]
        consumption[moment] = used if without_pv else max(used, used - exported + model.get(moment, 0.0))
    return DayData(consumption, None, "meter_without_pv" if without_pv else "meter")


class PvInsightsService:
    def __init__(self, forecasts: PvForecastService, readings, files, prices, market):
        self.forecasts = forecasts
        self.readings = readings
        self.files = files
        self.prices = prices
        self.market = market

    @property
    def weather(self):
        return self.forecasts.weather

    @property
    def devices(self):
        return self.forecasts.devices

    def setup(self, user_id, profile: UserProfile) -> PvSetup:
        return self.forecasts.setup(user_id, profile)

    def data_periods(self, user_id) -> list[tuple[date, date]]:
        """Okresy, które obejmują pliki użytkownika: zakresy plików połączone, gdy nachodzą na siebie albo się stykają.
        Między okresami plików nie ma (np. pliki z czerwca i z października to dwa okresy)."""
        spans = sorted((f.data_start, f.data_end) for f in self._files(user_id) if f.data_start and f.data_end)
        periods: list[tuple[date, date]] = []
        for start, end in spans:
            if periods and start <= periods[-1][1] + timedelta(days=1):
                periods[-1] = (periods[-1][0], max(periods[-1][1], end))
            else:
                periods.append((start, end))
        return periods

    def days(self, user_id, profile: UserProfile) -> list[DaySummary]:
        today = self.weather.today()
        summaries = []
        for offset in range(FORECAST_DAYS):
            day = today + timedelta(days=offset)
            try:
                forecast = self.forecasts.forecast(user_id, profile, day)
            except PvForecastUnavailableError:
                summaries.append(DaySummary(day, available=False))
                continue
            cloud, low, high = _weather_summary(forecast.weather)
            summaries.append(DaySummary(
                day=day,
                total_kwh=forecast.total_kwh,
                cloud_cover_pct=cloud,
                temperature_min_c=low,
                temperature_max_c=high,
                basis=forecast.basis,
                complete=forecast.complete,
            ))
        return summaries

    def day(self, user_id, profile: UserProfile, setup: PvSetup, day: date) -> DayDetail:
        today = self.weather.today()
        kind = "past" if day < today else "today" if day == today else "future"
        quarters = _quarters(day)
        notes: list[str] = []

        forecast = None
        try:
            forecast = self.forecasts.forecast(user_id, profile, day)
            notes.extend(forecast.notes)
        except PvForecastUnavailableError:
            notes.append("Nie ma pogody na ten dzień, więc nie ma produkcji z modelu.")
        model = {q.start: q.kwh for q in forecast.quarters if q.basis} if forecast else {}

        files = self._files(user_id)
        measured = self._measured(user_id, files, day, quarters, model) if kind == "past" and files else None
        actual = measured.actual if measured else None
        if forecast is None and actual is None:
            raise PvForecastUnavailableError(f"Brak pogody i produkcji z pliku na {day}.")

        typical = None
        consumption = consumption_source = None
        if measured is not None:
            consumption, consumption_source = measured.consumption, measured.source
            if consumption_source == "meter_without_pv":
                notes.append("Plik z licznika z tego okresu nie ma oddania do sieci, więc panele chyba jeszcze nie "
                             "działały: zużycie domu to pobór z sieci, a produkcja i bilans pokazują, ile dałyby panele.")
        elif kind != "past" and files:
            typical = self._typical(user_id, setup, files, day)
            if typical is not None:
                consumption = {q: typical.by_clock[_clock(q)] for q in quarters if _clock(q) in typical.by_clock}
                consumption_source = "typical"

        weather = forecast.weather if forecast else None
        weather_by_quarter = {q.start: q for q in weather.quarters} if weather else {}
        production = actual if actual is not None else model
        balance = None
        if consumption and production:
            balance = self._balance(user_id, profile, day, production, consumption, notes)

        intervals = []
        for moment in quarters:
            quarter_weather = weather_by_quarter.get(moment)
            intervals.append(Interval(
                start=moment,
                model_kwh=round(model[moment], 4) if moment in model else None,
                actual_kwh=round(actual[moment], 4) if actual is not None else None,
                consumption_kwh=round(consumption[moment], 4) if consumption and moment in consumption else None,
                cloud_cover_pct=quarter_weather.cloud_cover_pct if quarter_weather else None,
                temperature_c=quarter_weather.temperature_c if quarter_weather else None,
            ))
        return DayDetail(
            day=day,
            kind=kind,
            model_kwh=round(sum(model.values()), 2) if model else None,
            actual_kwh=round(sum(actual.values()), 2) if actual is not None else None,
            consumption_kwh=round(sum(consumption.values()), 2) if consumption else None,
            consumption_source=consumption_source,
            weather_source=_weather_source(weather),
            weather_fetched_at=forecast.weather_fetched_at if forecast else None,
            basis=forecast.basis if forecast else None,
            intervals=intervals,
            balance=balance,
            typical=typical,
            notes=notes,
        )

    def _files(self, user_id) -> list[EnergyDataFile]:
        files = [
            energy_file
            for source in (EnergyDataFile.SOURCE_METER, EnergyDataFile.SOURCE_DEVICES)
            for energy_file in self.files.list_completed_by_user_id(user_id, source)
        ]
        return sorted(files, key=lambda f: (f.uploaded_at, str(f.id)))

    @staticmethod
    def _meter_ids(files: list[EnergyDataFile]) -> list:
        return [f.id for f in files if f.source_type == EnergyDataFile.SOURCE_METER]

    def _meter_readings(self, meter_ids: list, first: date, end: date) -> dict[datetime, tuple[float, float, object]]:
        start_local = _naive_local(local_day_bounds_utc(first)[0])
        end_local = _naive_local(local_day_bounds_utc(end)[0])
        return {
            measured_at: (used, exported, file_id)
            for measured_at, used, exported, file_id in self.readings.merged_with_file(meter_ids, start_local, end_local)
        }

    def _measured(self, user_id, files: list[EnergyDataFile], day: date, quarters: list[datetime], model) -> DayData | None:
        slots = self.devices.home_quarters(user_id, quarters[0], quarters[-1] + QUARTER)
        if slots:
            spans = self.devices.pv_inverter_file_spans(user_id)
            return device_day(quarters, slots, any(first <= day <= last for first, last in spans))
        meter_ids = self._meter_ids(files)
        if not meter_ids:
            return None
        readings = self._meter_readings(meter_ids, day, day + timedelta(days=1))
        return meter_day(quarters, readings, model, self.readings.files_with_export(meter_ids))

    def _typical(self, user_id, setup: PvSetup, files: list[EnergyDataFile], day: date) -> Typical | None:
        end_day = min(day, self.weather.today())
        weekend = day.weekday() >= 5
        hour = self.weather.now().replace(minute=0, second=0, microsecond=0)
        key = (user_id, tuple(f.id for f in files), tuple(setup.arrays), setup.calibration.coefficient,
               weekend, end_day, hour)
        with _typical_lock:
            if key in _typical_profiles:
                return _typical_profiles[key]
        typical = self._typical_profile(user_id, setup, files, weekend, end_day)
        with _typical_lock:
            _typical_profiles[key] = typical
            while len(_typical_profiles) > TYPICAL_CACHE_SIZE:
                _typical_profiles.popitem(last=False)
        return typical

    def _typical_profile(self, user_id, setup: PvSetup, files: list[EnergyDataFile], weekend: bool, end_day: date) -> Typical | None:
        """Typowe zużycie: średnia z tej samej godziny zegarowej z ostatnich (do 28) dni z odczytami, nie starszych
        niż 60 dni, najpierw z dni tego samego rodzaju (robocze albo weekend)."""
        first = end_day - timedelta(days=TYPICAL_MAX_AGE_DAYS)
        slots = self.devices.home_quarters(user_id, local_day_bounds_utc(first)[0], local_day_bounds_utc(end_day)[0])
        device_slots: dict[date, dict[datetime, tuple[float, float]]] = defaultdict(dict)
        for moment, values in slots.items():
            device_slots[_local_day(moment)][moment] = values
        meter_ids = self._meter_ids(files)
        readings = self._meter_readings(meter_ids, first, end_day) if meter_ids else {}
        meter_days = {moment.date() for moment in readings} - set(device_slots)

        available = sorted(set(device_slots) | meter_days)
        same_kind = [d for d in available if (d.weekday() >= 5) == weekend]
        candidates = (same_kind if len(same_kind) >= 3 else available)[-TYPICAL_DAYS:]
        if not candidates:
            return None
        modeled = self.forecasts.modeled(setup, [d for d in candidates if d in meter_days])
        spans = self.devices.pv_inverter_file_spans(user_id) if device_slots else []
        with_export = self.readings.files_with_export(meter_ids) if meter_days else set()

        sums: dict[tuple[int, int], list[float]] = defaultdict(list)
        used_days = []
        for candidate in candidates:
            quarters = _quarters(candidate)
            if candidate in device_slots:
                data = device_day(quarters, device_slots[candidate], any(a <= candidate <= b for a, b in spans))
            else:
                data = meter_day(quarters, readings, modeled.get(candidate, {}), with_export)
            if data is None:
                continue
            used_days.append(candidate)
            for moment, kwh in data.consumption.items():
                sums[_clock(moment)].append(kwh)
        if not used_days:
            return None
        return Typical(
            days=len(used_days),
            first_day=used_days[0],
            last_day=used_days[-1],
            kind=_kind_of(used_days),
            by_clock={clock: sum(values) / len(values) for clock, values in sums.items()},
        )

    def _balance(self, user_id, profile: UserProfile, day: date, production, consumption, notes) -> Balance:
        hours = hourly_balance(production, consumption)
        balance = Balance(
            production_kwh=round(sum(production.values()), 2),
            consumption_kwh=round(sum(consumption.values()), 2),
            self_kwh=round(sum(own for _, own, _, _ in hours), 2),
            export_kwh=round(sum(exported for _, _, exported, _ in hours), 2),
            import_kwh=round(sum(imported for _, _, _, imported in hours), 2),
        )
        try:
            start, end = local_day_bounds_utc(day)
            prices = self.prices.for_user(user_id, start, end).prices
        except HTTPException as error:
            notes.append(f"Bez wyceny w złotówkach: {error.detail if isinstance(error.detail, str) else 'brak stawek taryfy'}")
            return balance
        except ValueError:
            notes.append("Bez wyceny w złotówkach: brak cen rynkowych do taryfy.")
            return balance

        valuation = ExportValuation(self.market, profile)
        estimated = missing = False
        unpriced_kwh = 0.0
        self_value = export_value = 0.0
        own_total = exported_total = 0.0
        for hour, own, exported, _ in hours:
            hour_prices = [prices[q] for q in (hour + QUARTER * index for index in range(4)) if q in prices]
            if not hour_prices:
                unpriced_kwh += own + exported
                continue
            price = sum(hour_prices) / len(hour_prices)
            self_value += own * price
            own_total += own
            if exported <= 0:
                continue
            export_price, guessed = valuation.hour_price(hour, price)
            if export_price is None:
                missing = True
                continue
            estimated = estimated or guessed
            export_value += exported * export_price
            exported_total += exported
        if unpriced_kwh > 0:
            notes.append(f"Bez ceny z sieci dla części godzin ({unpriced_kwh:.1f} kWh z paneli)".replace(".", ",")
                         + ": przy umowie z ceną dynamiczną ceny na kolejny dzień są po publikacji RCE.")
        if missing:
            notes.append("Brak cen RCE z tego okresu, więc energii oddanej do sieci nie wyceniamy.")
        elif estimated:
            reason = ("RCEm za ten miesiąc nie jest jeszcze opublikowana, a cen RCE z tego dnia też nie ma"
                      if valuation.rcem_replaced(day) else "Brak cen RCE z tego dnia")
            notes.append(f"{reason}: wartość oddania to średnia RCE z tych samych godzin z {PRICE_LOOKBACK_DAYS} "
                         "poprzednich dni.")
        elif exported_total > 0 and valuation.rcem_replaced(day):
            # PSE publikuje RCEm ok. 10. dnia następnego miesiąca; do tego czasu resolver wycenia oddanie po RCE.
            notes.append("RCEm za ten miesiąc nie jest jeszcze opublikowana, więc oddanie wyceniamy cenami RCE "
                         "z poszczególnych godzin. Po publikacji wartość może się zmienić.")
        purchase = self_value / own_total if own_total else None
        export = export_value / exported_total if exported_total else None
        balance.value = Value(
            self_pln=round(self_value, 2),
            export_pln=round(export_value, 2),
            purchase_price=round(purchase, 3) if purchase is not None else None,
            export_price=round(export, 3) if export is not None else None,
            export_price_estimated=estimated and not missing,
        )
        return balance
