"""Bojler jako magazyn ciepła (ZP-112): temperatura wody, wymagania i najtańsze grzanie."""

import pytest

from app.services.water_heater import (
    LOSS_C_PER_HOUR_AT_READY,
    ROOM_TEMP,
    MAX_TEMP,
    MIN_TEMP,
    READY_TEMP,
    PLAN_START_TEMP,
    THERMOSTAT_START_TEMP,
    Tank,
    daily_draw_kwh,
    default_tank_liters,
    draw_from_history,
    thermostat_loss_kwh,
    draws,
    optimize,
    simulate,
    thermostat,
)

SLOTS = 96  # doba planu
MORNING, EVENING = 24, 72  # 06:00 i 18:00
READY = [MORNING, EVENING]


def night_cheap_prices() -> list[float]:
    """Tanio w nocy (00:00–05:00) i w południe (12:00–15:00), drogo w szczycie."""
    return [0.3 if slot < 20 or 48 <= slot < 60 else 1.2 for slot in range(SLOTS)]


def case(residents=3, liters=120, power_kw=2.0):
    tank = Tank(liters=liters, power_kw=power_kw)
    draw = draws(SLOTS, READY, daily_draw_kwh(residents))
    return tank, draw, night_cheap_prices()


def test_more_residents_need_more_hot_water_and_bigger_tank():
    assert daily_draw_kwh(5) > daily_draw_kwh(2)
    assert (default_tank_liters(2), default_tank_liters(4), default_tank_liters(5)) == (80, 120, 150)
    assert sum(draws(SLOTS, READY, daily_draw_kwh(5))) > sum(draws(SLOTS, READY, daily_draw_kwh(2)))


def test_hot_water_cools_down_faster_than_warm():
    tank = Tank(liters=80, power_kw=2.0)

    def cooled(start):
        return start - simulate(tank, start, [False] * 4, [0.0] * 4, [1.0] * 4, [0.0] * 4).temps[-1]

    # Przy 55°C ok. 0,5°C na godzinę; przy 75°C szybciej o (75 − 22) / (55 − 22), przy 45°C wolniej.
    assert cooled(READY_TEMP) == pytest.approx(LOSS_C_PER_HOUR_AT_READY, abs=0.01)
    assert cooled(MAX_TEMP) == pytest.approx(cooled(READY_TEMP) * (MAX_TEMP - ROOM_TEMP) / (READY_TEMP - ROOM_TEMP), abs=0.02)
    assert cooled(45.0) < cooled(READY_TEMP)


def test_hot_water_from_history_subtracts_thermostat_losses():
    # 80 l trzymane na 55°C traci 12°C na dobę, czyli ok. 1,1 kWh: z 3,5 kWh w pliku zostaje ok. 2,4 kWh poboru.
    assert thermostat_loss_kwh(80) == pytest.approx(1.12, abs=0.01)
    assert draw_from_history(3.5, 80) == pytest.approx(3.5 - thermostat_loss_kwh(80))
    assert draw_from_history(0.3, 80) == 0.5  # bojler prawie nieużywany: nie mniej niż minimum


def test_plan_keeps_water_ready_and_never_cold_and_is_cheaper_than_thermostat():
    tank, draw, prices = case()

    before = thermostat(tank, draw, prices, READY)
    after = optimize(tank, draw, prices, READY)

    assert after.shortfall == 0
    assert after.cost < before.cost
    assert all(MIN_TEMP - 1e-6 <= temp <= MAX_TEMP + 1e-6 for temp in after.temps)
    assert after.temps[MORNING - 1] >= READY_TEMP and after.temps[EVENING - 1] >= READY_TEMP
    # Termostat trzyma 55°C od północy, a plan zaczyna od 45°C i kończy dobę co najmniej tak samo.
    assert (before.start_temp, after.start_temp) == (THERMOSTAT_START_TEMP, PLAN_START_TEMP)
    assert after.temps[-1] >= PLAN_START_TEMP and before.temps[-1] >= THERMOSTAT_START_TEMP - 1
    # Grzanie na zapas: tylko w tanich kwadransach, a w drogim szczycie wieczorem grzałka stoi.
    assert all(prices[slot] == 0.3 for slot, active in enumerate(after.on) if active)
    assert max(after.temps) > READY_TEMP + 5


def test_too_small_heater_reports_shortfall():
    tank, draw, prices = case(residents=6, liters=50, power_kw=0.5)

    assert optimize(tank, draw, prices, READY).shortfall > 0
