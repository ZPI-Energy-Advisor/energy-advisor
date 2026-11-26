# ruff: noqa: F811 (fikstury db i home są parametrami testów)
"""ZP-120: to, co w dobie planu pracuje samo (PV z prognozy, pompa i bojler spoza planu), w planie i w symulacji."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import Depends

from app.api.v1.deps import get_plan_service
from app.database import get_db
from app.models.UserProfile import UserProfile as UserProfileRow
from app.models.WeatherObservation import WeatherObservation
from app.providers.prices.base import local_day_bounds_utc
from app.providers.weather import WeatherPoint, WeatherProviderError
from app.repositories.day_plan_repository import DayPlanRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.home_repository import HomeRepository
from app.repositories.planning_repository import PlanningRepository
from app.repositories.user_repository import UserRepository
from app.repositories.weather_repository import WeatherRepository
from app.services.day_background import DayBackground, DayBackgroundService, scale_runs
from app.services.heat_pump import HeatPumpService
from app.services.heat_pump_model import building_model
from app.services.home_replay import ReplayRun
from app.services.plan_service import PlanService
from app.services.pv_forecast import PvForecastService, clear_calibrations
from app.services.weather_service import Cell, WeatherService
from main import app
from test_day_plan import _PriceRange, _Prices
from test_energy_files import _headers, client
from test_home import HEAT_PUMP, WASHER, _upload, db  # noqa: F401 (db: fixture)
from test_home_control import home  # noqa: F401 (home: fixture)
from test_plan_run import PV, WASHER_IN_PLAN, _by_device, _file, _pv_action, _start
from test_planning_preferences import _put
from test_users_api import profile_payload

UTC = timezone.utc
CELL = Cell(Decimal("50.1"), Decimal("19.9"))
REFERENCE_DAY = date(2026, 10, 5)
PLAN_DAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)
PANELS = {"mode": "net_billing", "type_of_price": "RCE", "installation": {"arrays": [{"power_kwp": 5.0, "azimuth": 0, "tilt": 35}]}}
HEAT_PUMP_ACTIONS = [{**HEAT_PUMP["actions"][0]}]


@pytest.fixture(autouse=True)
def _fresh_calibrations():
    clear_calibrations()
    yield
    clear_calibrations()


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


class _Offline:
    def forecast(self, *args):
        raise WeatherProviderError("testy nie pytają Open-Meteo", retryable=False)

    archive = forecast


def _weather_day(db, day: date, source: str, temperature: float, sun_w_m2: float, now=NOW):
    start, end = local_day_bounds_utc(day)
    points, moment = [], start
    while moment < end:
        hour = moment.hour
        sun = sun_w_m2 if 8 <= hour < 14 else 0.0
        points.append(WeatherPoint(moment, 15, temperature, 50, sun, {"35/0": sun}))
        moment += timedelta(minutes=15)
    WeatherRepository(db).upsert(CELL.latitude, CELL.longitude, source, points, now)


def _house(db, home, pv_actions, extra=(), pv_config=PANELS, period_start="2026-10-05", period_end="2026-10-13"):
    period = {"start": f"{period_start}T00:00:00+02:00", "end": f"{period_end}T00:00:00+02:00"}
    devices = [WASHER["device"], PV, *[entry["device"] for entry in extra]]
    actions = [*WASHER["actions"], *pv_actions, *[action for entry in extra for action in entry["actions"]]]
    assert _upload(home.owner, _file(period, devices, actions)).status_code == 200
    home.hub.use_clock_state()
    payload = profile_payload("G11")
    payload["base_info"].update({
        "heating_area_m2": 120, "year_of_construction": 2010, "number_of_residents": 3,
        "location": {"latitude": 50.06, "longitude": 19.94, "source": "postal_code"},
    })
    payload["pv_config"] = pv_config
    db.add(UserProfileRow(user_id=home.owner.id, **payload))
    db.commit()
    return home.owner


def _service(session, now):
    weather = WeatherService(WeatherRepository(session), client=_Offline(), now=lambda: now)
    heat_pumps = HeatPumpService(weather, DeviceRepository(session))
    return PlanService(
        PlanningRepository(session), DayPlanRepository(session), _Prices(), _PriceRange(), today=lambda: PLAN_DAY,
        heat_pumps=heat_pumps,
        background=DayBackgroundService(
            HomeRepository(session), UserRepository(session).valid_profile,
            PvForecastService(weather, DeviceRepository(session)), heat_pumps,
        ),
    )


def _plan(owner, devices=None, plan_date: date = PLAN_DAY, now=NOW) -> dict:
    assert _put(owner, {"devices": devices or [WASHER_IN_PLAN]}).status_code == 200
    app.dependency_overrides[get_plan_service] = lambda session=Depends(get_db): _service(session, now)
    try:
        response = client.post("/api/v1/planning/plans", json={"plan_date": plan_date.isoformat()}, headers=_headers(owner))
    finally:
        app.dependency_overrides.pop(get_plan_service, None)
    assert response.status_code == 201, response.text
    plan = response.json()
    assert client.post(f"/api/v1/planning/plans/{plan['id']}/approve", headers=_headers(owner)).status_code == 200
    return plan


def _background(db, owner, plan) -> DayBackground:
    stored = DayPlanRepository(db).get(owner.id, plan["id"])
    db.refresh(stored)
    return DayBackground.from_json(stored.result["background"])


def _pv_forecast_kwh(db, owner, day=PLAN_DAY, now=NOW) -> float:
    weather = WeatherService(WeatherRepository(db), client=_Offline(), now=lambda: now)
    profile = UserRepository(db).valid_profile(owner.id)
    return PvForecastService(weather, DeviceRepository(db)).forecast(owner.id, profile, day).total_kwh


def test_pv_in_plan_and_simulation_comes_from_the_weather_forecast(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)])
    _weather_day(db, REFERENCE_DAY, "archive", 14.0, 300.0)
    _weather_day(db, PLAN_DAY, "forecast", 10.0, 600.0)
    expected = _pv_forecast_kwh(db, owner)

    plan = _plan(owner)
    background = _background(db, owner, plan)
    pv_device, = background.devices
    run = _start(owner, plan["id"]).json()

    assert expected > 6.4
    assert (pv_device.source, pv_device.history_day, pv_device.reference_kwh) == ("forecast", REFERENCE_DAY, pytest.approx(-6.4))
    assert pv_device.kwh == pytest.approx(-expected, abs=0.01)
    pv, = _by_device(home.hub.batches[0])["dev_pv_01"]
    assert sum(pv["profile_kwh"]) == pytest.approx(-expected, abs=0.01)
    assert all(kwh <= 0 for kwh in pv["profile_kwh"])
    assert pv["ref"] == f"pv_forecast_{PLAN_DAY.isoformat()}"
    replayed, = run["replayed_devices"]
    assert (replayed["source"], replayed["history_kwh"], replayed["reference_kwh"]) == (
        "forecast", pytest.approx(-expected, abs=0.01), -6.4,
    )
    assert any(note.startswith("Instalacja PV w symulacji: produkcja z prognozy pogody") for note in plan["notes"])


def test_simulation_uses_plan_snapshot_even_when_forecast_changes_later(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)])
    _weather_day(db, REFERENCE_DAY, "archive", 14.0, 300.0)
    _weather_day(db, PLAN_DAY, "forecast", 10.0, 600.0)
    plan = _plan(owner)
    planned = _background(db, owner, plan).devices[0].kwh
    _weather_day(db, PLAN_DAY, "forecast", 10.0, 50.0)

    _start(owner, plan["id"])

    pv, = _by_device(home.hub.batches[0])["dev_pv_01"]
    assert sum(pv["profile_kwh"]) == pytest.approx(planned, abs=0.01)


def test_without_weather_pv_stays_like_reference_day_and_plan_says_why(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)])

    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()

    pv, = _by_device(home.hub.batches[0])["dev_pv_01"]
    assert (pv["ref"], sum(pv["profile_kwh"])) == ("act_pv_2026-10-05", pytest.approx(-6.4, rel=0.01))
    assert run["replayed_devices"][0]["source"] == "history"
    assert any("produkcja jak w poniedziałek 5 października, bo nie ma pogody na ten dzień" in note
               for note in plan["notes"])


def test_profile_without_panels_keeps_pv_from_history_and_asks_to_add_them(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)], pv_config={"mode": "none"})
    _weather_day(db, PLAN_DAY, "forecast", 10.0, 600.0)

    plan = _plan(owner)
    _start(owner, plan["id"])

    pv, = _by_device(home.hub.batches[0])["dev_pv_01"]
    assert sum(pv["profile_kwh"]) == pytest.approx(-6.4, rel=0.01)
    assert any("profil nie ma paneli" in note for note in plan["notes"])


def test_unplanned_heat_pump_heats_more_on_a_colder_day_in_plan_and_simulation(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)], extra=[HEAT_PUMP])
    _weather_day(db, REFERENCE_DAY, "archive", 12.0, 300.0)
    _weather_day(db, PLAN_DAY, "forecast", 0.0, 300.0)

    plan = _plan(owner, devices=[WASHER_IN_PLAN, {"device_id": "dev_hp_01", "enabled": False}])
    background = _background(db, owner, plan)
    _start(owner, plan["id"])

    pump = next(device for device in background.devices if device.device_id == "dev_hp_01")
    model = building_model(2010, 120, 3)
    expected = 1.5 + model.kwh(0.0) - model.kwh(12.0)
    assert (pump.source, pump.reference_kwh) == ("forecast", pytest.approx(1.5))
    assert pump.kwh == pytest.approx(expected, abs=0.01)
    sent = sum(sum(command["profile_kwh"]) for command in _by_device(home.hub.batches[0])["dev_hp_01"])
    assert sent == pytest.approx(expected, abs=0.01)
    assert max(kwh for command in _by_device(home.hub.batches[0])["dev_hp_01"] for kwh in command["profile_kwh"]) <= 0.75 + 1e-6
    assert any(note.startswith("Pompa ciepła pracuje sama, poza planem") for note in plan["notes"])


def test_unplanned_heat_pump_without_weather_heats_like_reference_day_and_says_why(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)], extra=[HEAT_PUMP])

    plan = _plan(owner, devices=[WASHER_IN_PLAN, {"device_id": "dev_hp_01", "enabled": False}])
    _start(owner, plan["id"])

    sent = sum(sum(command["profile_kwh"]) for command in _by_device(home.hub.batches[0])["dev_hp_01"])
    assert sent == pytest.approx(1.5)
    assert any("grzeje jak w poniedziałek 5 października, bo nie mamy pogody" in note for note in plan["notes"])


def test_planned_heat_pump_is_not_sent_twice(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)], extra=[HEAT_PUMP])
    _weather_day(db, REFERENCE_DAY, "archive", 12.0, 300.0)
    _weather_day(db, PLAN_DAY, "forecast", 0.0, 300.0)

    plan = _plan(owner, devices=[WASHER_IN_PLAN, {"device_id": "dev_hp_01", "enabled": True, "shift_hours": 1}])
    _start(owner, plan["id"])

    assert [device.device_id for device in _background(db, owner, plan).devices] == ["dev_pv_01"]
    commands = _by_device(home.hub.batches[0])["dev_hp_01"]
    assert all("ref" not in command for command in commands)
    assert sum(sum(c["profile_kwh"]) for c in commands) == pytest.approx(plan["heat_pumps"][0]["kwh"], abs=0.01)


def test_december_plan_from_september_file_has_winter_sun_and_more_heating(db, home, weather_cell):
    september = "2026-09-15"
    pump = {"device": HEAT_PUMP["device"], "actions": [{**HEAT_PUMP["actions"][0],
            "action_start": f"{september}T12:00:00+02:00", "action_end": f"{september}T13:00:00+02:00"}]}
    owner = _house(db, home, [_pv_action(september, -20.0)], extra=[pump], period_start="2026-09-15")
    december, now = date(2026, 12, 10), datetime(2026, 12, 11, 10, 0, tzinfo=UTC)
    _weather_day(db, date(2026, 9, 15), "archive", 17.0, 700.0, now)
    _weather_day(db, december, "archive", -3.0, 150.0, now)

    plan = _plan(owner, devices=[WASHER_IN_PLAN, {"device_id": "dev_hp_01", "enabled": False}], plan_date=december, now=now)
    devices = {device.device_id: device for device in _background(db, owner, plan).devices}

    assert devices["dev_pv_01"].source == "forecast" and -20.0 < devices["dev_pv_01"].kwh < -1.0
    assert devices["dev_hp_01"].kwh > 10 * devices["dev_hp_01"].reference_kwh
    assert any("produkcja z pogody z archiwum" in note for note in plan["notes"])


def _run(start_hour, values):
    return ReplayRun("dev_hp_01", datetime(2026, 10, 12, start_hour, tzinfo=UTC), "ref", list(values))


def test_scaling_runs_keeps_shape_and_total():
    scaled = scale_runs([_run(2, [0.2, 0.4]), _run(10, [0.2])], 1.6, cap_kwh=None, day_end=datetime(2026, 10, 13, tzinfo=UTC))

    assert [run.profile_kwh for run in scaled] == [[pytest.approx(0.4), pytest.approx(0.8)], [pytest.approx(0.4)]]


def test_scaling_runs_fills_headroom_then_extends_until_the_next_run():
    runs = [_run(2, [0.5, 0.1]), _run(3, [0.5])]

    scaled = scale_runs(runs, 3.3, cap_kwh=0.75, day_end=datetime(2026, 10, 13, tzinfo=UTC))

    first, second = scaled
    assert first.profile_kwh == [pytest.approx(0.75), pytest.approx(0.75), pytest.approx(0.3)]
    assert second.profile_kwh == [pytest.approx(0.75), pytest.approx(0.75)]
    assert first.end <= second.start
    assert sum(sum(run.profile_kwh) for run in scaled) == pytest.approx(3.3)


def test_scaling_runs_cannot_run_past_the_next_run_and_drops_the_rest():
    scaled = scale_runs([_run(2, [0.5]), _run(3, [0.5])], 6.0, cap_kwh=0.75,
                        day_end=datetime(2026, 10, 12, 4, tzinfo=UTC))

    assert [len(run.profile_kwh) for run in scaled] == [4, 4]
    assert sum(sum(run.profile_kwh) for run in scaled) == pytest.approx(6.0)
    tight = scale_runs([_run(2, [0.5]), _run(3, [0.5])], 20.0, cap_kwh=0.75,
                       day_end=datetime(2026, 10, 12, 4, tzinfo=UTC))
    assert sum(sum(run.profile_kwh) for run in tight) == pytest.approx(0.75 * 8)


def test_extra_load_is_only_what_pump_adds_above_the_reference_day():
    background = DayBackground()
    before = [_run(2, [0.2, 0.2])]
    after = [_run(2, [0.5, 0.1, 0.3])]

    DayBackgroundService._add_extra(background, before, after)

    start = datetime(2026, 10, 12, 2, tzinfo=UTC)
    assert background.extra_load == {start: pytest.approx(0.3), start + timedelta(minutes=30): pytest.approx(0.3)}
