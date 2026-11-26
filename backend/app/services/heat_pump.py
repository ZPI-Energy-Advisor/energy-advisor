"""Pompa ciepła w planie na jutro (ZP-119): ile prądu zużyje przy prognozowanej temperaturze.

Plan bierze bloki grzania z dnia referencyjnego (ostatni dzień z historią) i skaluje je do pogody dnia planu:
energia = zużycie dnia referencyjnego + (model dla dnia planu − model dla dnia referencyjnego). Model
(`heat_pump_model`) jest dopasowany do zużycia pompy z plików, a bez historii liczony z profilu.
"""

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from pydantic import ValidationError

from app.repositories.device_repository import DeviceRepository
from app.schemas.user_profile import HomeLocation
from app.services.heat_pump_model import (
    DEFAULT_INDOOR_C,
    HeatingDay,
    HeatModel,
    building_model,
    fit,
    floor_heating_for,
)
from app.services.water_heater import TankLimits
from app.services.weather_service import Cell, WeatherService, WeatherUnavailableError

logger = logging.getLogger(__name__)

HEAT_PUMP_TYPE = "heat_pump"
WATER_HEATER_TYPE = "water_heater"
MIN_TEMPERATURE_SHARE = 0.8
MIN_TARGET_SHARE = 0.5
SLOT = timedelta(minutes=15)
# Zasobnik ciepłej wody pompy ciepła, gdy użytkownik ustawi godziny „ciepła woda gotowa na”: typowy 200 l,
# a pompa grzeje wodę najwyżej do ok. 55 °C (grzałka bojlera do 75 °C).
HEAT_PUMP_TANK_LITERS = 200
HEAT_PUMP_TANK = TankLimits(min_temp=40.0, ready_temp=50.0, max_temp=55.0, plan_start_temp=45.0)
DEFAULT_HEAT_PUMP_POWER_KW = 4.5


@dataclass(frozen=True)
class Home:
    year_built: int | None
    area_m2: float | None
    residents: int | None
    cell: Cell | None
    property_type: str | None = None

    @classmethod
    def of(cls, base_info: dict) -> "Home":
        location = None
        if base_info.get("location"):
            try:
                location = HomeLocation.model_validate(base_info["location"])
            except ValidationError:
                location = None
        return cls(
            year_built=base_info.get("year_of_construction"),
            area_m2=base_info.get("heating_area_m2"),
            residents=base_info.get("number_of_residents"),
            cell=Cell.of(location) if location else None,
            property_type=base_info.get("type_of_property"),
        )


@dataclass(frozen=True)
class DayTemperature:
    day: date
    mean_c: float
    min_c: float
    max_c: float
    source: str


@dataclass(frozen=True)
class HeatPumpDay:
    """Energia pompy na dzień planu: `kwh` to cel dla planu, `reference_kwh` zużycie dnia referencyjnego."""

    model: HeatModel
    reference_day: date
    reference_kwh: float
    kwh: float
    reference: HeatingDay | None = None
    reference_temperature: DayTemperature | None = None
    plan: HeatingDay | None = None
    plan_temperature: DayTemperature | None = None
    # Temperatura w domu w dniu planu (ustawienie pompy); dzień referencyjny liczymy dla domyślnej.
    indoor_c: float = DEFAULT_INDOOR_C
    # Udział tej pompy w zmianie zużycia domu (przy kilku pompach mniej niż 1).
    share: float = 1.0


def _temperature(day: date, weather) -> DayTemperature | None:
    values = [q.temperature_c for q in weather.quarters if q.temperature_c is not None]
    if not values or len(values) < MIN_TEMPERATURE_SHARE * len(weather.quarters):
        return None
    sources = {q.source for q in weather.quarters if q.source}
    return DayTemperature(
        day=day,
        mean_c=sum(values) / len(values),
        min_c=min(values),
        max_c=max(values),
        source=sources.pop() if len(sources) == 1 else "mixed",
    )


class HeatPumpService:
    def __init__(self, weather: WeatherService, devices: DeviceRepository):
        self.weather = weather
        self.devices = devices

    def history(self, user_id) -> dict[date, float]:
        """Zużycie wszystkich pomp ciepła domu na dobę z plików, dni minione."""
        today = self.weather.today()
        return {day: kwh for day, kwh in self.devices.daily_energy_by_type(user_id, HEAT_PUMP_TYPE).items() if day < today}

    def model(self, user_id, home: Home, history: dict[date, float] | None = None) -> HeatModel | None:
        # Bojler w obecnych plikach (bez wersji przykrytych nowszym plikiem) grzeje wodę, więc pompa tylko dom.
        hot_water = not self.devices.has_current_device_type(user_id, WATER_HEATER_TYPE)
        fallback = building_model(home.year_built, home.area_m2, home.residents, hot_water=hot_water,
                                  property_type=home.property_type)
        if home.cell is None:
            return fallback
        history = self.history(user_id) if history is None else history
        if not history:
            return fallback
        temperatures = self.stored_temperatures(home.cell, history)
        days = [(temperatures[day].mean_c, history[day]) for day in sorted(history) if day in temperatures]
        return fit(days, floor_heating_for(home.year_built), fallback)

    def stored_temperatures(self, cell: Cell, days) -> dict[date, DayTemperature]:
        result = {}
        for day, weather in self.weather.stored_days(cell, days, []).items():
            temperature = _temperature(day, weather)
            if temperature:
                result[day] = temperature
        return result

    def outdoor(self, cell: Cell, day: date) -> tuple[DayTemperature, dict[datetime, float]] | None:
        """Temperatura na dworze w każdym kwadransie doby (brakujące kwadranse: średnia doby); None bez pogody."""
        try:
            weather = self.weather.day(cell, day, [])
        except WeatherUnavailableError:
            return None
        temperature = _temperature(day, weather)
        if temperature is None:
            return None
        return temperature, {
            q.start: q.temperature_c if q.temperature_c is not None else temperature.mean_c for q in weather.quarters
        }

    def share(self, user_id, reference_day: date | None, reference_kwh: float) -> float:
        """Część domu ogrzewana tą pompą: jej udział w zużyciu wszystkich pomp w dniu referencyjnym (zwykle 1)."""
        if reference_day is None:
            return 1.0
        house = self.history(user_id).get(reference_day, 0.0)
        return min(reference_kwh / house, 1.0) if house > 0 else 1.0

    def has_water_heater(self, user_id) -> bool:
        return self.devices.has_current_device_type(user_id, WATER_HEATER_TYPE)

    def temperature(self, cell: Cell, day: date) -> DayTemperature | None:
        try:
            return _temperature(day, self.weather.day(cell, day, []))
        except WeatherUnavailableError:
            return None

    def plan_day(self, user_id, home: Home, reference_day: date, reference_kwh: float, plan_date: date,
                 indoor_c: float | None = None) -> HeatPumpDay | None:
        """Cel energii pompy na dzień planu; None bez modelu (brak metrażu w profilu i historii).

        Model opisuje cały dom, więc przy kilku pompach każda dostaje część zmiany według swojego udziału
        w zużyciu dnia referencyjnego. `indoor_c`: temperatura w domu w dniu planu; dzień referencyjny
        liczymy dla domyślnej, bo nie wiemy, jaką ustawienie było wtedy."""
        indoor_c = DEFAULT_INDOOR_C if indoor_c is None else indoor_c
        history = self.history(user_id) if home.cell is not None else {}
        model = self.model(user_id, home, history)
        if model is None:
            return None
        if home.cell is None:
            return HeatPumpDay(model, reference_day, reference_kwh, reference_kwh)
        reference_temperature = self.temperature(home.cell, reference_day)
        plan_temperature = self.temperature(home.cell, plan_date)
        if reference_temperature is None or plan_temperature is None:
            return HeatPumpDay(model, reference_day, reference_kwh, reference_kwh,
                               reference_temperature=reference_temperature, plan_temperature=plan_temperature)
        reference = model.day(reference_temperature.mean_c)
        plan = model.day(plan_temperature.mean_c, indoor_c)
        house_reference = history.get(reference_day, 0.0)
        share = min(reference_kwh / house_reference, 1.0) if house_reference > 0 else 1.0
        target = max(reference_kwh + share * (plan.kwh - reference.kwh), share * MIN_TARGET_SHARE * plan.kwh, 0.0)
        return HeatPumpDay(model, reference_day, reference_kwh, target, reference, reference_temperature,
                           plan, plan_temperature, indoor_c, share)


@dataclass
class Block:
    start: datetime
    slots: int
    kwh: float
    # Energia w kwadransach, gdy blok ma przerwy (pompa grzeje wtedy wodę); None to po równo w każdym.
    profile: list[float] | None = None

    def profile_kwh(self) -> list[float]:
        return self.profile if self.profile is not None else [self.kwh / self.slots] * self.slots


def scale_blocks(blocks: list[Block], target_kwh: float, cap_kwh: float | None, horizon_end: datetime,
                 blocked: frozenset[datetime] | set[datetime] = frozenset()) -> list[Block]:
    """Bloki dnia referencyjnego przeskalowane do `target_kwh`. Blok, który przy mocy pompy (`cap_kwh` na kwadrans)
    nie zmieści energii, wydłuża się do następnego bloku albo końca planu; czego i tak się nie da, przepada
    (pompa pracuje wtedy bez przerwy i więcej nie da).

    `blocked`: kwadranse, w których pompa grzeje wodę. Blok ich nie zajmuje: ma w nich przerwę (zero w profilu)
    i wydłuża się o tyle kwadransów dalej."""
    total = sum(block.kwh for block in blocks)
    if total <= 0:
        return [Block(block.start, block.slots, block.kwh) for block in blocks]
    factor = target_kwh / total
    ordered = sorted(blocks, key=lambda block: block.start)
    result = []
    for index, block in enumerate(ordered):
        kwh = block.kwh * factor
        limit = ordered[index + 1].start if index + 1 < len(ordered) else horizon_end
        span = max(block.slots, int((limit - block.start) / SLOT))
        moments = [block.start + offset * SLOT for offset in range(span)]
        needed = max(block.slots, math.ceil(kwh / cap_kwh - 1e-9)) if cap_kwh else block.slots
        chosen = [moment for moment in moments if moment not in blocked][:needed]
        if not chosen:
            result.append(Block(block.start, block.slots, 0.0, [0.0] * block.slots))
            continue
        if cap_kwh:
            kwh = min(kwh, cap_kwh * len(chosen))
        if not blocked or len(chosen) == int((chosen[-1] - block.start) / SLOT) + 1:
            result.append(Block(block.start, len(chosen), kwh))
            continue
        used = set(chosen)
        length = int((chosen[-1] - block.start) / SLOT) + 1
        per_slot = kwh / len(chosen)
        profile = [per_slot if block.start + offset * SLOT in used else 0.0 for offset in range(length)]
        result.append(Block(block.start, length, kwh, profile))
    return result
