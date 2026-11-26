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
from app.services.heat_pump_model import HeatingDay, HeatModel, building_model, fit, floor_heating_for
from app.services.weather_service import Cell, WeatherService, WeatherUnavailableError

logger = logging.getLogger(__name__)

HEAT_PUMP_TYPE = "heat_pump"
WATER_HEATER_TYPE = "water_heater"
MIN_TEMPERATURE_SHARE = 0.8
MIN_TARGET_SHARE = 0.5
SLOT = timedelta(minutes=15)


@dataclass(frozen=True)
class Home:
    year_built: int | None
    area_m2: float | None
    residents: int | None
    cell: Cell | None

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
        hot_water = not self.devices.has_device_type(user_id, WATER_HEATER_TYPE)
        fallback = building_model(home.year_built, home.area_m2, home.residents, hot_water=hot_water)
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

    def temperature(self, cell: Cell, day: date) -> DayTemperature | None:
        try:
            return _temperature(day, self.weather.day(cell, day, []))
        except WeatherUnavailableError:
            return None

    def plan_day(self, user_id, home: Home, reference_day: date, reference_kwh: float, plan_date: date) -> HeatPumpDay | None:
        """Cel energii pompy na dzień planu; None bez modelu (brak metrażu w profilu i historii).

        Model opisuje cały dom, więc przy kilku pompach każda dostaje część zmiany według swojego udziału
        w zużyciu dnia referencyjnego."""
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
        plan = model.day(plan_temperature.mean_c)
        house_reference = history.get(reference_day, 0.0)
        share = min(reference_kwh / house_reference, 1.0) if house_reference > 0 else 1.0
        target = max(reference_kwh + share * (plan.kwh - reference.kwh), share * MIN_TARGET_SHARE * plan.kwh, 0.0)
        return HeatPumpDay(model, reference_day, reference_kwh, target, reference, reference_temperature,
                           plan, plan_temperature)


@dataclass
class Block:
    start: datetime
    slots: int
    kwh: float


def scale_blocks(blocks: list[Block], target_kwh: float, cap_kwh: float | None, horizon_end: datetime) -> list[Block]:
    """Bloki dnia referencyjnego przeskalowane do `target_kwh`. Blok, który przy mocy pompy (`cap_kwh` na kwadrans)
    nie zmieści energii, wydłuża się do następnego bloku albo końca planu; czego i tak się nie da, przepada
    (pompa pracuje wtedy bez przerwy i więcej nie da)."""
    total = sum(block.kwh for block in blocks)
    if total <= 0:
        return [Block(block.start, block.slots, block.kwh) for block in blocks]
    factor = target_kwh / total
    ordered = sorted(blocks, key=lambda block: block.start)
    result = []
    for index, block in enumerate(ordered):
        kwh = block.kwh * factor
        slots = block.slots
        if cap_kwh:
            limit = ordered[index + 1].start if index + 1 < len(ordered) else horizon_end
            free = max(block.slots, int((limit - block.start) / SLOT))
            slots = min(max(block.slots, math.ceil(kwh / cap_kwh - 1e-9)), free)
            kwh = min(kwh, cap_kwh * slots)
        result.append(Block(block.start, slots, kwh))
    return result