"""Dom jako magazyn ciepła: temperatura w domu, termostat i najtańsze grzanie pompą w zakresie komfortu."""

import math
import time

import pytest
from timing import TIME_LIMIT_SCALE

from app.services.heat_pump_model import building_heat_per_hdd, building_model
from app.services.house_heating import (
    CAPACITY_KWH_PER_M2_K,
    DEFAULT_TIME_CONSTANT_H,
    LEVELS,
    MIN_TIME_CONSTANT_H,
    House,
    house_capacity,
    optimize,
    thermostat,
)

SLOTS = 96
POWER_KW = 4.5


def _house(indoor=21, property_type="single_family_house", area=120.0, year=2010):
    model = building_model(year, area, 3, property_type=property_type)
    return House.of(model, property_type, area, indoor)


def _outdoor(mean=0.0):
    # Najzimniej ok. 3:00, najcieplej ok. 15:00.
    return [mean - 3 * math.cos(2 * math.pi * (slot / 4 - 3) / 24) for slot in range(SLOTS)]


def _night_cheap():
    return [0.5 if slot < 24 or 52 <= slot < 64 else 1.2 for slot in range(SLOTS)]


def test_apartment_loses_less_heat_and_cools_slower_than_detached_house():
    detached = _house()
    apartment = _house(property_type="apartment", area=60.0)
    terrace = _house(property_type="terrace_house")

    assert building_heat_per_hdd(2010, 120, "apartment") == pytest.approx(0.55 * building_heat_per_hdd(2010, 120))
    assert terrace.loss_kw_per_k < detached.loss_kw_per_k
    assert apartment.time_constant_h > terrace.time_constant_h > detached.time_constant_h
    # Dom 120 m² z 2010: stała czasowa ok. 43 h, przy 0 °C bez grzania stygnie o ok. 0,4 °C na godzinę.
    assert detached.time_constant_h == pytest.approx(43, abs=1)
    assert detached.cooling_per_hour(0.0) == pytest.approx(0.42, abs=0.02)


def test_capacity_without_area_comes_from_a_typical_time_constant():
    assert house_capacity("single_family_house", None, 0.2) == pytest.approx(DEFAULT_TIME_CONSTANT_H * 0.2)
    assert house_capacity("apartment", 50, 0.1) == pytest.approx(CAPACITY_KWH_PER_M2_K["apartment"] * 50)


def test_small_area_in_profile_cannot_make_a_house_that_cools_in_a_few_hours():
    model = building_model(2010, 120, 3)
    small = House.of(model, "single_family_house", 13.0, 21)
    big = House.of(model, "single_family_house", 120.0, 21)

    assert small.time_constant_h == pytest.approx(MIN_TIME_CONSTANT_H)
    assert big.time_constant_h == pytest.approx(43, abs=1)
    assert house_capacity("single_family_house", 13, 0.3) == pytest.approx(MIN_TIME_CONSTANT_H * 0.3)


def test_small_area_heats_cheaper_than_thermostat_without_false_shortfall():
    model = building_model(2010, 120, 3)
    house = House.of(model, "single_family_house", 13.0, 21)
    outdoor, prices = _outdoor(2.0), _night_cheap()

    before = thermostat(house, outdoor, prices, POWER_KW)
    after = optimize(house, outdoor, prices, POWER_KW)

    assert before.shortfall == 0 and after.shortfall == 0
    assert after.cost < before.cost
    assert min(after.temps) >= house.low - 0.01


def test_pump_modulates_in_quarter_steps():
    house = _house()
    cap = POWER_KW / 4

    heating = optimize(house, _outdoor(), _night_cheap(), POWER_KW)

    assert LEVELS == (0.0, 0.25, 0.5, 0.75, 1.0)
    assert all(any(kwh == pytest.approx(level * cap) for level in LEVELS) for kwh in heating.kwh)
    assert any(kwh == pytest.approx(0.25 * cap) or kwh == pytest.approx(0.75 * cap) for kwh in heating.kwh)


def test_thermostat_keeps_the_set_temperature_and_uses_about_the_daily_model_energy():
    house = _house()
    heating = thermostat(house, [0.0] * SLOTS, [1.0] * SLOTS, POWER_KW)

    model = building_model(2010, 120, 3)
    day = model.day(0.0)
    assert all(temp == pytest.approx(21.0, abs=0.01) for temp in heating.temps)
    assert sum(heating.kwh) == pytest.approx(day.space_heat_kwh / day.cop, rel=0.03)


def test_plan_heats_in_cheap_hours_within_comfort_band_and_costs_less():
    house = _house()
    outdoor, prices = _outdoor(), _night_cheap()

    before = thermostat(house, outdoor, prices, POWER_KW)
    after = optimize(house, outdoor, prices, POWER_KW)

    assert after.cost < 0.85 * before.cost
    assert min(after.temps) >= 20.0 - 0.01 and max(after.temps) <= 22.0 + 0.01
    assert after.temps[-1] >= 21.0 - 0.05 and after.shortfall == 0
    cheap = sum(kwh for slot, kwh in enumerate(after.kwh) if prices[slot] < 1)
    assert cheap > 0.6 * sum(after.kwh)


def test_warmer_setting_needs_more_heat():
    outdoor, prices = _outdoor(), _night_cheap()

    assert sum(optimize(_house(indoor=23), outdoor, prices, POWER_KW).kwh) > sum(
        optimize(_house(indoor=21), outdoor, prices, POWER_KW).kwh
    )


def test_pump_does_not_heat_the_house_while_heating_water():
    house = _house()
    blocked = set(range(24, 32))

    heating = optimize(house, _outdoor(), _night_cheap(), POWER_KW, blocked=blocked)

    assert all(heating.kwh[slot] == 0 for slot in blocked)
    assert heating.shortfall == 0


def test_too_weak_pump_reports_shortfall_instead_of_failing():
    house = _house(area=300.0, year=1960)

    heating = optimize(house, [-15.0] * SLOTS, [1.0] * SLOTS, 3.0)

    assert heating.shortfall > 0.3
    assert all(kwh == pytest.approx(0.75) for kwh in heating.kwh[-10:])


def test_grid_limit_moves_heating_out_of_blocked_quarters_when_possible():
    house = _house()
    allowed = [not 20 <= slot < 28 for slot in range(SLOTS)]

    heating = optimize(house, _outdoor(), [0.5] * SLOTS, POWER_KW, allowed=allowed)

    assert all(heating.kwh[slot] == 0 for slot in range(20, 28))


@pytest.mark.perf
def test_five_power_levels_plan_a_day_and_night_quickly():
    """ZP-151: 5 poziomów mocy zamiast 3 wydłużają planowanie najwyżej o kilkadziesiąt procent. Limit to doba
    i noc do 6:00 (120 kwadransów) z 5 poziomami; stara pętla z 5 poziomami była ok. 2,5 raza wolniejsza niż z 3."""
    house = _house()
    outdoor = [2.0 + 4 * ((slot % SLOTS) / SLOTS) for slot in range(SLOTS + 24)]
    prices = [0.5 if slot % SLOTS < 24 else 1.0 for slot in range(SLOTS + 24)]
    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        optimize(house, outdoor, prices, POWER_KW)
        best = min(best, time.perf_counter() - started)

    assert best < 0.06 * TIME_LIMIT_SCALE

