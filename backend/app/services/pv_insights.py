"""Dane ekranu „Fotowoltaika” (ZP-150): najbliższe dni, szczegóły doby (także z przeszłości) i trafność prognozy.

Doba łączy prognozę albo model z pogody (ZP-118), produkcję falownika z pliku urządzeń, zużycie domu z plików
oraz podział produkcji na autokonsumpcję i oddanie do sieci. Operator bilansuje pobór i oddanie w każdej godzinie,
więc dzielimy w godzinach. Wartość autokonsumpcji to cena z sieci (energia, dystrybucja zmienna, opłaty, VAT),
a oddania: net-billing RCE albo RCEm × 1,23 do depozytu (ujemna cena = 0), net-metering opust × cena z sieci.
"""

import logging
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException

from app.models.EnergyDataFile import EnergyDataFile
from app.providers.prices.base import MARKET_TIMEZONE, local_day_bounds_utc
from app.schemas.other import TypeOfMarketEnergyEnum
from app.schemas.user_profile import UserProfile
from app.services.pv_forecast import (
    PvForecastService,
    PvForecastUnavailableError,
    PvSetup,
)
from app.services.pv_service import PVBalancingEngine
from app.services.weather_service import DayWeather

logger = logging.getLogger(__name__)

QUARTER = timedelta(minutes=15)
HOUR = timedelta(hours=1)
FORECAST_DAYS = 3
TYPICAL_DAYS = 28
TYPICAL_LOOKBACK_DAYS = 365
PRICE_LOOKBACK_DAYS = 14
PEAK_SHARE = 0.6
MIN_SURPLUS_KWH = 0.02
DAYLIGHT_W_M2 = 1.0
EARLIEST_READINGS = datetime(2000, 1, 1)
TYPICAL_CACHE_SIZE = 256
_typical_profiles: OrderedDict = OrderedDict()
_typical_lock = threading.Lock()


def clear_typical_profiles() -> None:
    with _typical_lock:
        _typical_profiles.clear()


@dataclass
class Window:
    start: datetime
    end: datetime


@dataclass
class DaySummary:
    day: date
    total_kwh: float | None = None
    peak: Window | None = None
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
    peak: Window | None
    notes: list[str] = field(default_factory=list)


def _quarters(day: date) -> list[datetime]:
    start, end = local_day_bounds_utc(day)
    count = int((end - start) / QUARTER)
    return [start + QUARTER * index for index in range(count)]


def _naive_local(moment: datetime) -> datetime:
    return moment.astimezone(MARKET_TIMEZONE).replace(tzinfo=None)


def _window(values: dict[datetime, float]) -> Window | None:
    """Godziny, w których wartość jest blisko szczytu: najdłuższy ciągły przedział wokół maksimum
    z wartościami co najmniej 60% maksimum."""
    if not values:
        return None
    ordered = sorted(values)
    peak_at = max(ordered, key=lambda moment: values[moment])
    peak = values[peak_at]
    if peak <= MIN_SURPLUS_KWH:
        return None
    index = ordered.index(peak_at)
    first = last = index
    while first > 0 and values[ordered[first - 1]] >= PEAK_SHARE * peak:
        first -= 1
    while last < len(ordered) - 1 and values[ordered[last + 1]] >= PEAK_SHARE * peak:
        last += 1
    return Window(ordered[first], ordered[last] + QUARTER)


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

    def setup(self, user_id, profile: UserProfile) -> PvSetup:
        return self.forecasts.setup(user_id, profile)

    def first_data_day(self, user_id) -> date | None:
        starts = [
            energy_file.data_start
            for source in (EnergyDataFile.SOURCE_METER, EnergyDataFile.SOURCE_DEVICES)
            for energy_file in self.files.list_completed_by_user_id(user_id, source)
            if energy_file.data_start
        ]
        return min(starts) if starts else None

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
                peak=_window({q.start: q.kwh for q in forecast.quarters}),
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

        production_all = self.forecasts.devices.pv_production(user_id) if kind == "past" else {}
        actual = {q: production_all.get(q, 0.0) for q in quarters} if any(q in production_all for q in quarters) else None
        if forecast is None and actual is None:
            raise PvForecastUnavailableError(f"Brak pogody i produkcji z pliku na {day}.")

        consumption, consumption_source = self._consumption(user_id, setup, day, quarters, model, actual, kind)
        weather = forecast.weather if forecast else None
        weather_by_quarter = {q.start: q for q in weather.quarters} if weather else {}

        production = actual if actual is not None else model
        balance = None
        if consumption is not None and production:
            balance = self._balance(user_id, profile, day, production, consumption, notes)

        intervals = []
        for moment in quarters:
            quarter_weather = weather_by_quarter.get(moment)
            intervals.append(Interval(
                start=moment,
                model_kwh=round(model[moment], 4) if moment in model else None,
                actual_kwh=round(actual[moment], 4) if actual is not None else None,
                consumption_kwh=round(consumption[moment], 4) if consumption is not None and moment in consumption else None,
                cloud_cover_pct=quarter_weather.cloud_cover_pct if quarter_weather else None,
                temperature_c=quarter_weather.temperature_c if quarter_weather else None,
            ))
        return DayDetail(
            day=day,
            kind=kind,
            model_kwh=round(sum(model.values()), 2) if model else None,
            actual_kwh=round(sum(actual.values()), 2) if actual is not None else None,
            consumption_kwh=round(sum(consumption.values()), 2) if consumption is not None else None,
            consumption_source=consumption_source,
            weather_source=_weather_source(weather),
            weather_fetched_at=forecast.weather_fetched_at if forecast else None,
            basis=forecast.basis if forecast else None,
            intervals=intervals,
            balance=balance,
            peak=_window(production) if production else None,
            notes=notes,
        )

    def _file_ids(self, user_id) -> list:
        files = [
            energy_file
            for source in (EnergyDataFile.SOURCE_METER, EnergyDataFile.SOURCE_DEVICES)
            for energy_file in self.files.list_completed_by_user_id(user_id, source)
        ]
        return [energy_file.id for energy_file in sorted(files, key=lambda f: (f.uploaded_at, str(f.id)))]

    def _readings(self, file_ids: list, start: datetime, end: datetime) -> dict[datetime, tuple[float, float]]:
        return {measured_at: (used, exported) for measured_at, used, exported in self.readings.merged_for_files(file_ids, start, end)}

    def _day_consumption(
        self,
        quarters: list[datetime],
        readings: dict[datetime, tuple[float, float]],
        model: dict[datetime, float],
        actual: dict[datetime, float] | None,
    ) -> dict[datetime, float] | None:
        """Zużycie domu w kwadransach doby: pobór − oddanie + produkcja. Bez produkcji z pliku bierzemy produkcję
        z modelu, ale zużycie nie może być mniejsze od poboru z sieci. Godzina powtórzona przy zmianie czasu
        ma w odczytach jeden zsumowany kwadrans, który dzielimy po równo."""
        local = [_naive_local(moment) for moment in quarters]
        counts = defaultdict(int)
        for moment in local:
            counts[moment] += 1
        if not any(moment in readings for moment in local):
            return None
        consumption = {}
        for moment, naive in zip(quarters, local):
            used, exported = readings.get(naive, (0.0, 0.0))
            used, exported = used / counts[naive], exported / counts[naive]
            if actual is not None:
                consumption[moment] = max(used - exported + actual.get(moment, 0.0), 0.0)
            else:
                consumption[moment] = max(used, used - exported + model.get(moment, 0.0))
        return consumption

    def _consumption(self, user_id, setup: PvSetup, day: date, quarters, model, actual, kind):
        file_ids = self._file_ids(user_id)
        if not file_ids:
            return None, None
        start = _naive_local(quarters[0])
        end = _naive_local(quarters[-1]) + QUARTER
        day_readings = self._readings(file_ids, start, end) if kind == "past" else {}
        measured = self._day_consumption(quarters, day_readings, model, actual) if kind == "past" else None
        if measured is not None:
            return measured, "devices" if actual is not None else "meter"
        typical = self._typical(user_id, setup, file_ids, day, quarters)
        return (typical, "typical") if typical is not None else (None, None)

    def _typical(self, user_id, setup: PvSetup, file_ids: list, day: date, quarters: list[datetime]) -> dict[datetime, float] | None:
        end_day = min(day, self.weather.today())
        weekend = day.weekday() >= 5
        hour = self.weather.now().replace(minute=0, second=0, microsecond=0)
        key = (user_id, tuple(file_ids), tuple(setup.arrays), setup.calibration.coefficient, weekend, end_day, hour)
        with _typical_lock:
            profile = _typical_profiles.get(key)
        if profile is None:
            profile = self._typical_profile(user_id, setup, file_ids, weekend, end_day)
            with _typical_lock:
                _typical_profiles[key] = profile
                while len(_typical_profiles) > TYPICAL_CACHE_SIZE:
                    _typical_profiles.popitem(last=False)
        if not profile:
            return None
        typical = {}
        for moment in quarters:
            local = moment.astimezone(MARKET_TIMEZONE)
            if (local.hour, local.minute) in profile:
                typical[moment] = profile[(local.hour, local.minute)]
        return typical

    def _typical_profile(self, user_id, setup: PvSetup, file_ids: list, weekend: bool, end_day: date) -> dict[tuple[int, int], float]:
        """Typowe zużycie: średnia z tej samej godziny zegarowej z ostatnich dni z plików (do 28), najpierw
        z dni tego samego rodzaju (robocze albo weekend)."""
        end = datetime.combine(end_day, time())
        readings = self._readings(file_ids, end - timedelta(days=TYPICAL_LOOKBACK_DAYS), end)
        if not readings:
            readings = self._readings(file_ids, EARLIEST_READINGS, end)
        if not readings:
            return {}
        by_day: dict[date, dict[datetime, tuple[float, float]]] = defaultdict(dict)
        for moment, values in readings.items():
            by_day[moment.date()][moment] = values
        same_kind = [d for d in by_day if (d.weekday() >= 5) == weekend]
        candidates = sorted(same_kind if len(same_kind) >= 3 else by_day, reverse=True)[:TYPICAL_DAYS]
        production = self.forecasts.devices.pv_production(user_id)
        modeled = self.forecasts.modeled(setup, candidates)
        sums: dict[tuple[int, int], list[float]] = defaultdict(list)
        for candidate in candidates:
            candidate_quarters = _quarters(candidate)
            actual = ({q: production.get(q, 0.0) for q in candidate_quarters}
                      if any(q in production for q in candidate_quarters) else None)
            consumption = self._day_consumption(candidate_quarters, by_day[candidate], modeled.get(candidate, {}), actual)
            for moment, kwh in (consumption or {}).items():
                local = moment.astimezone(MARKET_TIMEZONE)
                sums[(local.hour, local.minute)].append(kwh)
        return {clock: sum(values) / len(values) for clock, values in sums.items()}

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
            export_price, guessed = self._export_price(profile, hour, price)
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
            notes.append(f"Brak cen RCE z tego dnia: wartość oddania to średnia z tych samych godzin z {PRICE_LOOKBACK_DAYS} "
                         "poprzednich dni.")
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

    def _export_price(self, profile: UserProfile, hour: datetime, purchase_price: float) -> tuple[float | None, bool]:
        """Wartość kWh oddanej w godzinie: net-metering opust × cena z sieci; net-billing RCE/RCEm × 1,23
        (ujemna = 0), a bez opublikowanej ceny średnia z tych samych godzin z ostatnich dni."""
        if profile.pv_config.mode == "net_metering":
            return purchase_price * profile.pv_config.effective_k_factor, False
        engine = PVBalancingEngine(self.market)
        price_type = profile.pv_config.type_of_price or TypeOfMarketEnergyEnum.RCE
        quarters = [_naive_local(hour + QUARTER * index) for index in range(4)]
        try:
            return sum(engine.get_price_for_pv_energy(q, price_type) for q in quarters) / 4, False
        except ValueError:
            pass
        past = []
        for days_back in range(1, PRICE_LOOKBACK_DAYS + 1):
            for quarter in quarters:
                try:
                    past.append(engine.get_price_for_pv_energy(quarter - timedelta(days=days_back), TypeOfMarketEnergyEnum.RCE))
                except ValueError:
                    continue
        if not past:
            return None, True
        return sum(past) / len(past), True
