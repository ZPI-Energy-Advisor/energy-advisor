# ruff: noqa: F811 (fikstury db i home z test_home są parametrami testów)
"""ZP-119: zużycie pompy ciepła od temperatury: model, dopasowanie do plików, skalowanie w planie i generator."""

import json
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import Depends

from app.api.v1.deps import get_plan_service
from app.database import get_db
from app.models.UserProfile import UserProfile as UserProfileRow
from app.models.WeatherObservation import WeatherObservation
from app.providers.prices.base import MARKET_TIMEZONE, local_day_bounds_utc
from app.providers.weather import WeatherPoint, WeatherProviderError
from app.repositories.day_plan_repository import DayPlanRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.planning_repository import PlanningRepository
from app.repositories.weather_repository import WeatherRepository
from app.services.heat_pump import Block, HeatPumpService, Home, scale_blocks
from app.services.heat_pump_model import (
    HeatModel,
    building_heat_per_hdd,
    building_model,
    fit,
    heating_cop,
    heating_degree_days,
    hot_water_cop,
)
from app.services.plan_service import PlanService
from app.services.weather_service import Cell, WeatherService
from main import app
from test_day_plan import PLAN_DATE, _items, _owner, _PriceRange, _Prices
from test_energy_files import _headers, client
from test_home import HEAT_PUMP, db, home  # noqa: F401 (fixtures)
from test_planning_preferences import _put
from test_users_api import profile_payload

UTC = timezone.utc
FIXTURES = Path(__file__).parent / "fixtures"
CELL = Cell(Decimal("50.1"), Decimal("19.9"))
REFERENCE_DAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)


def test_degree_days_follow_eurostat_rule():
    assert heating_degree_days(0.0) == 18.0
    assert heating_degree_days(15.0) == 3.0
    assert heating_degree_days(15.1) == 0.0


def test_cop_drops_in_cold_and_is_higher_with_floor_heating():
    assert heating_cop(7.0, floor_heating=True) == pytest.approx(0.85 * (6.08 - 0.0941 * 19.5 + 0.000464 * 19.5 ** 2))
    assert heating_cop(-10.0, True) < heating_cop(0.0, True) < heating_cop(10.0, True)
    assert heating_cop(-5.0, floor_heating=True) > heating_cop(-5.0, floor_heating=False)
    assert hot_water_cop(-5.0) < heating_cop(-5.0, floor_heating=True)


def test_older_and_bigger_houses_need_more_heat():
    assert building_heat_per_hdd(1960, 120) > building_heat_per_hdd(1990, 120) > building_heat_per_hdd(2022, 120)
    assert building_heat_per_hdd(2010, 120) == pytest.approx(85 * 120 / 3300)
    assert building_heat_per_hdd(2010, 200) > building_heat_per_hdd(2010, 100)


def test_ten_degrees_colder_means_clearly_more_electricity():
    model = building_model(2010, 120, 3)

    assert model.kwh(-5.0) > 1.5 * model.kwh(5.0)
    assert model.kwh(20.0) == pytest.approx(model.hot_water_kwh / hot_water_cop(20.0))
    assert model.day(20.0).hdd == 0


def _synthetic_days(model: HeatModel, temperatures, noise=0.05, seed=1):
    rng = random.Random(seed)
    return [(t, model.kwh(t) * rng.uniform(1 - noise, 1 + noise)) for t in temperatures]


def test_fit_recovers_house_from_its_consumption():
    house = HeatModel(heat_per_hdd=4.2, hot_water_kwh=6.0, floor_heating=True, source="test")
    days = _synthetic_days(house, [t / 2 for t in range(-20, 40)])

    model = fit(days, floor_heating=True, fallback=building_model(2010, 120, 3))

    assert model.source == "history"
    assert model.heat_per_hdd == pytest.approx(4.2, rel=0.05)
    assert model.hot_water_kwh == pytest.approx(6.0, rel=0.2)
    assert model.mape < 0.06


def test_fit_ignores_days_when_the_pump_was_off_or_half_off():
    house = HeatModel(heat_per_hdd=3.0, hot_water_kwh=5.0, floor_heating=True, source="test")
    days = _synthetic_days(house, [t / 2 for t in range(-10, 30)])
    days += [(2.0, 0.0), (1.0, 0.1), (3.0, house.kwh(3.0) * 0.3), (0.0, house.kwh(0.0) * 3)]

    model = fit(days, floor_heating=True, fallback=None)

    assert model.heat_per_hdd == pytest.approx(3.0, rel=0.06)
    assert model.days == 40


def test_without_cold_days_heating_comes_from_profile_and_water_from_files():
    fallback = building_model(2010, 120, 3)
    house = HeatModel(heat_per_hdd=9.9, hot_water_kwh=4.0, floor_heating=True, source="test")
    summer = _synthetic_days(house, [16 + (i % 6) for i in range(20)])

    model = fit(summer, floor_heating=True, fallback=fallback)

    assert model.source == "mixed"
    assert model.heat_per_hdd == fallback.heat_per_hdd
    assert model.hot_water_kwh == pytest.approx(4.0, rel=0.1)


def test_short_history_falls_back_to_profile():
    fallback = building_model(2010, 120, 3)

    assert fit([(5.0, 10.0)] * 5, floor_heating=True, fallback=fallback) is fallback
    assert fit([(5.0, 10.0)] * 5, floor_heating=True, fallback=None) is None
    assert building_model(2010, None, 3) is None


def test_demo_file_heat_pump_follows_temperature_and_fits_the_profile_house():
    document = json.loads((FIXTURES / "devices_demo_30d.json").read_text(encoding="utf-8"))
    weather = json.loads((FIXTURES / "weather_demo_30d.json").read_text(encoding="utf-8"))
    start = datetime.fromisoformat(weather["start"].replace("Z", "+00:00"))
    temperatures = defaultdict(list)
    for hour, value in enumerate(weather["temperature_c"]):
        temperatures[(start + timedelta(hours=hour)).astimezone(MARKET_TIMEZONE).date()].append(value)
    used = defaultdict(float)
    for action in document["energy_usage"]:
        if action["device_id"] == "dev_hp_01":
            used[datetime.fromisoformat(action["action_start"]).astimezone(MARKET_TIMEZONE).date()] += action["energy_kwh"]
    days = [(sum(temperatures[d]) / len(temperatures[d]), used[d]) for d in sorted(used)]

    cold = [kwh for mean, kwh in days if mean < 9]
    warm = [kwh for mean, kwh in days if mean > 11]
    model = fit(days, floor_heating=True, fallback=None)

    assert len(days) == 30 and cold and warm
    assert sum(cold) / len(cold) > 1.5 * sum(warm) / len(warm)
    assert model.source == "history"
    assert model.heat_per_hdd == pytest.approx(building_heat_per_hdd(2010, 120), rel=0.15)
    assert model.mape < 0.15


def _at(hour, minute=0):
    return datetime(2026, 10, 12, hour, minute, tzinfo=UTC)


def test_scaling_keeps_block_starts_and_reaches_the_target():
    blocks = [Block(_at(2), 4, 2.0), Block(_at(12), 4, 2.0)]

    scaled = scale_blocks(blocks, 6.0, cap_kwh=1.0, horizon_end=_at(23))

    assert [(b.start, b.slots) for b in scaled] == [(_at(2), 4), (_at(12), 4)]
    assert [b.kwh for b in scaled] == [pytest.approx(3.0), pytest.approx(3.0)]


def test_scaling_lengthens_a_block_up_to_the_next_one_when_power_is_not_enough():
    blocks = [Block(_at(2), 4, 2.0), Block(_at(3), 4, 2.0)]

    scaled = scale_blocks(blocks, 12.0, cap_kwh=0.5, horizon_end=_at(5))

    assert [b.slots for b in scaled] == [4, 8]
    assert [b.kwh for b in scaled] == [pytest.approx(2.0), pytest.approx(4.0)]


def test_scaling_down_in_warm_weather_never_goes_negative():
    scaled = scale_blocks([Block(_at(2), 4, 2.0)], 0.5, cap_kwh=1.0, horizon_end=_at(23))

    assert scaled[0].kwh == pytest.approx(0.5) and scaled[0].slots == 4


class _Offline:
    def forecast(self, *args):
        raise WeatherProviderError("testy nie pytają Open-Meteo", retryable=False)

    archive = forecast


def _weather_day(db, day: date, source: str, temperature: float):
    start, end = local_day_bounds_utc(day)
    points, moment = [], start
    while moment < end:
        points.append(WeatherPoint(moment, 15, temperature, 50, 0.0, {}))
        moment += timedelta(minutes=15)
    WeatherRepository(db).upsert(CELL.latitude, CELL.longitude, source, points, NOW)


@pytest.fixture
def weather_cell(db):
    def clean():
        db.query(WeatherObservation).filter(
            WeatherObservation.latitude == CELL.latitude, WeatherObservation.longitude == CELL.longitude
        ).delete(synchronize_session=False)
        db.commit()

    clean()
    yield
    clean()


def _with_profile(db, user, area=120.0, year=2010):
    payload = profile_payload("G11")
    payload["base_info"].update({
        "heating_area_m2": area, "year_of_construction": year, "number_of_residents": 3,
        "location": {"latitude": 50.06, "longitude": 19.94, "source": "postal_code"},
    })
    db.add(UserProfileRow(user_id=user.id, **payload))
    db.commit()


def _plan(user, heat_pumps=True):
    def factory(session=Depends(get_db)):
        weather = WeatherService(WeatherRepository(session), client=_Offline(), now=lambda: NOW)
        return PlanService(
            PlanningRepository(session), DayPlanRepository(session), _Prices(), _PriceRange(), today=lambda: PLAN_DATE,
            heat_pumps=HeatPumpService(weather, DeviceRepository(session)) if heat_pumps else None,
        )

    app.dependency_overrides[get_plan_service] = factory
    try:
        return client.post("/api/v1/planning/plans", json={}, headers=_headers(user))
    finally:
        app.dependency_overrides.pop(get_plan_service, None)


def _enable_heat_pump(owner):
    assert _put(owner, {"devices": [{"device_id": "dev_hp_01", "enabled": True, "shift_hours": 1}]}).status_code == 200


def test_plan_heats_more_when_plan_day_is_colder_than_reference_day(db, home, weather_cell):
    owner = _owner(home, HEAT_PUMP)
    _with_profile(db, owner)
    _enable_heat_pump(owner)
    _weather_day(db, REFERENCE_DAY, "archive", 12.0)
    _weather_day(db, PLAN_DATE, "forecast", 0.0)

    response = _plan(owner)

    assert response.status_code == 201, response.text
    body = response.json()
    pump = body["heat_pumps"][0]
    model = building_model(2010, 120, 3)
    expected = 1.5 + model.kwh(0.0) - model.kwh(12.0)
    assert pump["target_kwh"] == pytest.approx(expected, abs=0.01)
    assert pump["kwh"] == pytest.approx(expected, abs=0.01)
    assert (pump["plan_temperature"]["mean_c"], pump["reference_temperature"]["mean_c"]) == (0.0, 12.0)
    assert pump["model"]["source"] == "building" and pump["hdd"] == 18.0
    item = _items(response)["dev_hp_01#1"]
    assert item["energy_kwh"] == pytest.approx(expected, abs=0.01)
    assert max(item["profile_kwh"]) <= 3.0 * 0.25 + 1e-6
    note = next(note for note in body["notes"] if note.startswith("Pompa ciepła"))
    assert "w poniedziałek 12 października średnio 0°C" in note and "było średnio 12°C" in note
    assert body["warnings"] == []


def test_plan_warns_when_pump_power_cannot_cover_the_cold(db, home, weather_cell):
    owner = _owner(home, HEAT_PUMP)
    _with_profile(db, owner, area=400.0, year=1960)
    _enable_heat_pump(owner)
    _weather_day(db, REFERENCE_DAY, "archive", 14.0)
    _weather_day(db, PLAN_DATE, "forecast", -15.0)

    body = _plan(owner).json()

    pump = body["heat_pumps"][0]
    assert pump["kwh"] < pump["target_kwh"]
    # Blok z 12:00 może się wydłużyć najwyżej do końca planu o 06:00: 18 h po 3 kW.
    assert pump["kwh"] == pytest.approx(3.0 * 18, abs=0.01)
    assert any("W domu może być trochę chłodniej" in warning for warning in body["warnings"])


def test_plan_without_weather_keeps_reference_energy_and_says_why(db, home, weather_cell):
    owner = _owner(home, HEAT_PUMP)
    _with_profile(db, owner)
    _enable_heat_pump(owner)

    body = _plan(owner).json()

    assert body["heat_pumps"] == []
    assert _items_energy(body) == 1.5
    assert any("Nie mamy pogody na" in note and "nie dopasowujemy grzania" in note for note in body["notes"])


def test_plan_without_profile_location_keeps_reference_energy(db, home, weather_cell):
    owner = _owner(home, HEAT_PUMP)
    _enable_heat_pump(owner)

    body = _plan(owner).json()

    assert body["heat_pumps"] == [] and _items_energy(body) == 1.5
    assert any(note.startswith("Pompa ciepła: grzeje tyle co") for note in body["notes"])


def _items_energy(body) -> float:
    return sum(item["energy_kwh"] for item in body["items"] if item["kind"] == "heat_pump")


def test_two_warm_days_keep_heating_almost_unchanged(db, home, weather_cell):
    owner = _owner(home, HEAT_PUMP)
    _with_profile(db, owner)
    _enable_heat_pump(owner)
    _weather_day(db, REFERENCE_DAY, "archive", 20.0)
    _weather_day(db, PLAN_DATE, "forecast", 17.0)

    body = _plan(owner).json()

    assert body["heat_pumps"][0]["hdd"] == 0
    assert _items_energy(body) == pytest.approx(1.5, abs=0.15)


SECOND_PUMP = {
    "device": {**HEAT_PUMP["device"], "device_id": "dev_hp_02", "device_name": "Pompa ciepła garaż"},
    "actions": [{**HEAT_PUMP["actions"][0], "action_id": "act_hp_2", "device_id": "dev_hp_02"}],
}


def test_two_pumps_share_one_change_of_the_house(db, home, weather_cell):
    owner = _owner(home, HEAT_PUMP, SECOND_PUMP)
    _with_profile(db, owner)
    assert _put(owner, {"devices": [
        {"device_id": device_id, "enabled": True, "shift_hours": 1} for device_id in ("dev_hp_01", "dev_hp_02")
    ]}).status_code == 200
    _weather_day(db, REFERENCE_DAY, "archive", 12.0)
    _weather_day(db, PLAN_DATE, "forecast", 0.0)

    body = _plan(owner).json()

    model = building_model(2010, 120, 3)
    change = model.kwh(0.0) - model.kwh(12.0)
    assert [pump["target_kwh"] for pump in body["heat_pumps"]] == [pytest.approx(1.5 + change / 2, abs=0.01)] * 2
    assert _items_energy(body) == pytest.approx(3.0 + change, abs=0.02)


def _generator():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import generate_devices_file

    return generate_devices_file


def _pump_kwh_per_day(house, days: int) -> float:
    return sum(action["energy"] for action in house.actions if action["device_id"] == "dev_hp_01") / days


def test_generator_heats_much_more_in_winter_than_in_summer():
    generator = _generator()

    winter = generator.build_house(date(2026, 1, 5), 14, 1, "full", 9.0)
    summer = generator.build_house(date(2026, 7, 6), 14, 1, "full", 9.0)

    assert _pump_kwh_per_day(winter, 14) > 5 * _pump_kwh_per_day(summer, 14)
    assert 10 < _pump_kwh_per_day(winter, 14) < 40
    assert 1 < _pump_kwh_per_day(summer, 14) < 3


def test_generator_bigger_older_house_uses_more_and_water_heater_takes_hot_water():
    generator = _generator()

    default = generator.build_house(date(2026, 1, 5), 7, 1, "full", 9.0)
    old_big = generator.build_house(date(2026, 1, 5), 7, 1, "full", 9.0, area_m2=200, year_built=1975)
    summer_with_boiler = generator.build_house(date(2026, 7, 6), 7, 1, "full", 9.0, with_water_heater=True)

    assert _pump_kwh_per_day(old_big, 7) > 2 * _pump_kwh_per_day(default, 7)
    assert old_big.devices["dev_hp_01"]["max_power_kw"] > 4.5
    assert default.devices["dev_hp_01"]["max_power_kw"] == 4.5
    assert _pump_kwh_per_day(summer_with_boiler, 7) < 0.3
    for action in old_big.actions:
        if action["device_id"] == "dev_hp_01":
            assert max(action["profile_kwh"]) <= old_big.devices["dev_hp_01"]["max_power_kw"] * 0.25 + 1e-9


def test_home_reads_profile_fields_and_ignores_broken_location():
    home = Home.of({"year_of_construction": 1990, "heating_area_m2": 90, "number_of_residents": 2,
                    "location": {"latitude": "x"}})

    assert (home.year_built, home.area_m2, home.residents, home.cell) == (1990, 90, 2, None)
