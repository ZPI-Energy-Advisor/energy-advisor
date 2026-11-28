# ruff: noqa: F811 (fikstury db i home są parametrami testów)
"""ZP-153: statystyki na żywo w czasie przebiegu planu."""

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.plan_run import PlanRunActionOut
from app.services.heat_pump_model import building_model
from app.services.home_state_service import DayEnergy
from app.services.house_heating import House, optimize
from app.services.plan_run_live import live
from app.services.plan_run_report import RunEnergy
from app.services.pv_balance import HouseBalance
from test_home import db  # noqa: F401 (db: fixture)
from test_home_control import home  # noqa: F401 (home: fixture)
from test_home_events import _event
from test_plan_run import _home_with_files, _latest, _plan, _start, _store_events
from test_plan_run_report import _executed, _finish, _items, _prices

SLOT = timedelta(minutes=15)
UTC = timezone.utc
DAY = datetime(2026, 10, 11, 22, tzinfo=UTC)  # północ 12.10 w Polsce


def _baseline_cost(item: dict, prices: dict[datetime, float], until: datetime) -> float:
    start = datetime.fromisoformat(item["original_start"])
    total = 0.0
    for index, kwh in enumerate(item["original_profile_kwh"]):
        slot = start + index * SLOT
        if kwh and slot < until:
            total += kwh * prices[slot] * min((until - slot) / SLOT, 1.0)
    return total


# Przebieg przez API


def test_saving_so_far_counts_devices_still_working_and_matches_report_at_the_end(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    items = _items(plan)
    ev = items["dev_ev_01"]
    charging = datetime.fromisoformat(ev["start"])
    middle = charging + 2 * SLOT + timedelta(minutes=5)
    _store_events(db, owner, [*_executed(run, items["dev_wm_01"]), *_executed(run, ev, until=middle)])
    home.hub.clock_state["sim_time"] = middle.isoformat()

    during = _latest(owner).json()

    assert during["status"] == "running" and during["cost"]["pending"] != []
    saving = during["live"]["saving"]
    prices = _prices(plan)
    expected_before = sum(_baseline_cost(item, prices, middle) for item in (items["dev_wm_01"], ev))
    assert saving["cost_before"] == pytest.approx(expected_before, abs=0.01)
    measured = items["dev_wm_01"]["profile_kwh"], ev["profile_kwh"][:2]
    assert saving["cost_after"] == pytest.approx(
        sum(kwh * prices[datetime.fromisoformat(items["dev_wm_01"]["start"]) + i * SLOT] for i, kwh in enumerate(measured[0]) if kwh)
        + sum(kwh * prices[charging + i * SLOT] for i, kwh in enumerate(measured[1]) if kwh),
        abs=0.01,
    )
    assert during["live"]["price_now"] == prices[charging + 2 * SLOT]
    assert during["live"]["indoor"] == [] and during["live"]["pv"] is None

    _store_events(db, owner, [event for event in _executed(run, ev) if event["type"] == "energy_report"
                              and datetime.fromisoformat(event["data"]["interval_start"]) >= charging + 2 * SLOT])
    done = _finish(home, plan)

    final = done["live"]["saving"]
    assert saving["planned_saving"] == final["planned_saving"] == pytest.approx(plan["saving"], abs=0.01)
    assert final["cost_before"] == pytest.approx(done["cost"]["cost_before"], rel=0.01, abs=0.01)
    assert final["cost_after"] == pytest.approx(done["cost"]["cost_after"], rel=0.01, abs=0.01)
    assert final["saving"] == pytest.approx(done["cost"]["saving"], rel=0.01, abs=0.01)
    # Oszczędność w miarę pracy: pralka cała (skończyła), auto w proporcji do naładowanej energii; na końcu raport.
    def item_saving(item):
        return item["cost_before"] - item["cost_after"]
    charged = sum(ev["profile_kwh"][:2]) / sum(ev["profile_kwh"])
    expected = item_saving(items["dev_wm_01"]) + item_saving(ev) * charged
    assert saving["progress_saving"] == pytest.approx(expected, abs=0.01)
    assert final["progress_saving"] == pytest.approx(final["saving"], abs=0.01)


def test_device_switched_off_by_hand_leaves_saving_so_far(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    items = _items(plan)
    washer = items["dev_wm_01"]
    stop = datetime.fromisoformat(washer["start"]) + SLOT
    _store_events(db, owner, [
        *_executed(run, washer, until=stop),
        _event("device_finished", "dev_wm_01", stop.isoformat(), {"interrupted": True}, simulation_id=run["simulation_id"]),
    ])
    home.hub.clock_state["sim_time"] = (stop + SLOT).isoformat()

    saving = _latest(owner).json()["live"]["saving"]

    assert [device["device_id"] for device in saving["excluded"]] == ["dev_wm_01"]


def test_live_needs_profiles_saved_at_start(home, db):
    from app.models.PlanRun import PlanRun

    owner = _home_with_files(home)
    plan = _plan(owner)
    run_id = _start(owner, plan["id"]).json()["id"]
    stored = db.get(PlanRun, run_id)
    stored.items = [{key: value for key, value in item.items() if key not in ("original_profile_kwh", "original_start")}
                    for item in stored.items]
    db.commit()
    home.hub.clock_state["sim_time"] = datetime.fromisoformat(plan["items"][0]["start"]).isoformat()

    assert _latest(owner).json()["live"]["saving"] is None


# Rachunek z migawki


def _action(device_id: str, start: datetime, profile: list[float], original_start: datetime | None = None,
            original: list[float] | None = None, action_id: str | None = None) -> PlanRunActionOut:
    return PlanRunActionOut(
        action_id=action_id or device_id, device_id=device_id, device_name=device_id, kind="heat_pump",
        start=start, end=start + len(profile) * SLOT, energy_kwh=sum(profile), status="accepted",
        original_start=original_start or start, original_profile_kwh=original or profile, profile_kwh=profile,
    )


def _energy(by_device: dict[str, dict[datetime, float]]) -> DayEnergy:
    energy = DayEnergy()
    for device_id, slots in by_device.items():
        for slot, kwh in slots.items():
            energy.by_device_slot[device_id][slot] += kwh
            energy.by_slot[slot] += kwh
            energy.by_device[device_id] += kwh
    return energy


def _run(actions, energy, until, *, pv_devices=(), balance=None, prices=None):
    return RunEnergy(
        actions=actions, prices=prices or {DAY + index * SLOT: 1.0 for index in range(96)}, max_grid_kw=None,
        energy=energy, events=[], errors=[], names={}, background=set(pv_devices), pv_devices=set(pv_devices),
        until=until, complete=False, balance=balance,
    )


def _pump_snapshot(house: House, outdoor: list[float], temps: list[float]) -> dict:
    return {
        "device_id": "dev_hp_01", "device_name": "Pompa", "indoor_c": house.indoor_c,
        "band": [house.low, house.high], "loss_kw_per_k": house.loss_kw_per_k,
        "capacity_kwh_per_k": house.capacity_kwh_per_k, "floor_heating": house.floor_heating,
        "quarters": [
            {"start": (DAY + index * SLOT).isoformat(), "outdoor": outdoor[index], "after": temps[index]}
            for index in range(96)
        ],
    }


def test_indoor_temperature_follows_plan_and_drops_when_pump_is_off():
    house = House.of(building_model(2010, 120, 3), "single_family_house", 120.0, 21)
    outdoor = [0.0] * 96
    prices = [0.5 if index < 24 or 52 <= index < 64 else 1.2 for index in range(96)]
    plan = optimize(house, outdoor, prices, 4.5)
    snapshot = _pump_snapshot(house, outdoor, plan.temps)
    action = _action("dev_hp_01", DAY, plan.kwh, action_id="dev_hp_01#dom")
    until = DAY + 40 * SLOT + timedelta(minutes=7)
    worked = _energy({"dev_hp_01": {DAY + index * SLOT: kwh for index, kwh in enumerate(plan.kwh[:41])}})
    heating = [index for index, kwh in enumerate(plan.kwh[:41]) if kwh]
    assert heating, "plan grzeje przed 10:00"
    off = _energy({"dev_hp_01": {DAY + index * SLOT: kwh for index, kwh in enumerate(plan.kwh[:heating[0]])}})

    following = live(_run([action], worked, until), {"heat_pumps": [snapshot]}).indoor[0]
    stopped = live(_run([action], off, until), {"heat_pumps": [snapshot]}).indoor[0]

    assert following.at == (DAY + 40 * SLOT).astimezone(following.at.tzinfo)
    assert following.temp_c == pytest.approx(plan.temps[39], abs=0.2)
    assert house.low - 0.05 <= following.temp_c <= house.high + 0.05
    assert following.plan_c == plan.temps[39]
    assert (following.set_c, following.band) == (21, [20.0, 22.0])
    assert stopped.temp_c < following.temp_c - 0.3
    # Wykres: cała doba według planu, a z symulacji tylko pełne kwadranse do teraz.
    assert len(following.points) == 96
    assert following.points[39].temp_c == pytest.approx(plan.temps[39], abs=0.2)
    assert following.points[39].plan_c == plan.temps[39]
    assert following.points[40].temp_c is None and following.points[95].plan_c == plan.temps[95]


def test_indoor_temperature_is_shown_from_the_first_moment_of_the_plan():
    house = House.of(building_model(2010, 120, 3), "single_family_house", 120.0, 21)
    snapshot = _pump_snapshot(house, [0.0] * 96, [21.0] * 96)

    start = live(_run([], _energy({}), DAY), {"heat_pumps": [snapshot]}).indoor[0]

    # Przed pierwszym pełnym kwadransem: temperatura startowa domu, a nie brak wskaźnika.
    assert start.temp_c == house.indoor_c and start.plan_c is None
    assert all(point.temp_c is None for point in start.points)


def test_water_heating_of_the_pump_does_not_warm_the_house():
    house = House.of(building_model(2010, 120, 3), "single_family_house", 120.0, 21)
    snapshot = _pump_snapshot(house, [0.0] * 96, [21.0] * 96)
    water = _action("dev_hp_01", DAY, [1.0, 1.0], action_id="dev_hp_01#woda")
    measured = _energy({"dev_hp_01": {DAY: 1.0, DAY + SLOT: 1.0}})

    with_water = live(_run([water], measured, DAY + 2 * SLOT), {"heat_pumps": [snapshot]}).indoor[0]
    nothing = live(_run([water], _energy({}), DAY + 2 * SLOT), {"heat_pumps": [snapshot]}).indoor[0]

    assert with_water.temp_c == nothing.temp_c


def test_panels_split_into_used_at_home_and_exported_by_hour():
    hour = DAY + 12 * 4 * SLOT
    energy = _energy({
        "dev_pv_01": {hour + index * SLOT: -0.5 for index in range(4)},
        "dev_tv": {hour: 0.6, hour + 3 * SLOT: 0.2},
        "dev_lamp": {hour + 4 * SLOT: 0.3},
    })
    balance = HouseBalance({}, {}, {}, {hour: 0.4})

    pv = live(_run([], energy, hour + 5 * SLOT, pv_devices=["dev_pv_01"], balance=balance), {}).pv

    assert (pv.production_kwh, pv.self_kwh, pv.export_kwh) == (2.0, 0.8, 1.2)
    assert pv.self_kwh + pv.export_kwh == pv.production_kwh
    assert pv.export_pln == pytest.approx(1.2 * 0.4)


def test_panel_hours_compare_plan_with_measured_production_so_far():
    noon = DAY + 12 * 4 * SLOT
    planned = {noon + index * SLOT: 0.5 for index in range(8)}
    energy = _energy({"dev_pv_01": {noon + index * SLOT: -0.4 for index in range(5)}})
    balance = HouseBalance({}, planned, {}, {})

    pv = live(_run([], energy, noon + 5 * SLOT, pv_devices=["dev_pv_01"], balance=balance), {}).pv

    assert pv.planned_kwh == 4.0
    first, second = pv.hours
    assert (first.planned_kwh, first.actual_kwh) == (2.0, 1.6)
    # Bieżąca godzina: tyle, ile już zmierzono.
    assert (second.planned_kwh, second.actual_kwh) == (2.0, pytest.approx(0.4))


def test_without_pump_panels_or_weather_those_tiles_are_missing():
    result = live(_run([], _energy({}), DAY + SLOT), {})

    assert (result.indoor, result.pv, result.weather, result.export_price_now) == ([], None, None, None)
    assert result.saving.cost_before == 0 and result.saving.saving_percent is None


def test_weather_now_is_the_quarter_of_the_clock_from_the_plan():
    weather = {"past": True, "quarters": [
        {"start": (DAY + index * SLOT).isoformat(), "temperature_c": float(index), "cloud_cover_pct": 10 * index}
        for index in range(4)
    ]}

    now = live(_run([], _energy({}), DAY + 2 * SLOT + timedelta(minutes=3)), {"weather": weather}).weather
    boundary = live(_run([], _energy({}), DAY + 2 * SLOT), {"weather": weather}).weather

    assert (now.temperature_c, now.cloud_cover_pct, now.past) == (2.0, 20, True)
    # Na granicy kwadransu zegar jest już w nowym kwadransie.
    assert boundary.temperature_c == 2.0
    end = live(_run([], _energy({}), DAY + 4 * SLOT), {"weather": weather}).weather
    assert end.temperature_c == 3.0


def test_run_snapshot_keeps_house_model_only_of_pumps_that_hold_indoor_temperature():
    from app.services.plan_run_service import _heat_pump_snapshot

    indoor = {
        "device_id": "dev_hp_01", "device_name": "Pompa", "mode": "indoor", "indoor_c": 21, "band": [20, 22],
        "loss_kw_per_k": 0.21, "capacity_kwh_per_k": 9.1, "floor_heating": True,
        "temperatures": [{"start": "2026-10-12T00:00:00+02:00", "before": 21, "after": 20.9, "outdoor": 2.0}],
    }
    history = {"device_id": "dev_hp_02", "device_name": "Stara", "mode": "history"}
    before_zp153 = {**indoor, "device_id": "dev_hp_03", "loss_kw_per_k": None}

    snapshot, = _heat_pump_snapshot([indoor, history, before_zp153])

    assert snapshot == {
        "device_id": "dev_hp_01", "device_name": "Pompa", "indoor_c": 21, "band": [20, 22],
        "loss_kw_per_k": 0.21, "capacity_kwh_per_k": 9.1, "floor_heating": True,
        "quarters": [{"start": "2026-10-12T00:00:00+02:00", "outdoor": 2.0, "after": 20.9}],
    }


def _item(action_id: str, device_id: str, start: datetime, profile: list[float], kind: str = "heat_pump"):
    from app.schemas.day_plan import PlanItemOut

    return PlanItemOut(
        action_id=action_id, device_id=device_id, device_name=device_id, kind=kind, original_start=start,
        original_end=start, start=start, end=start + len(profile) * SLOT, energy_kwh=sum(profile), status="moved",
        profile_kwh=profile, original_profile_kwh=profile, program_id="cotton" if kind == "program" else None,
    )


def test_heat_pump_house_and_water_go_to_the_hub_as_one_profile():
    from app.services.plan_run_service import PlanRunService

    house = _item("dev_hp_01#dom", "dev_hp_01", DAY, [0.5, 0.0, 0.0, 0.5, 0.5])
    water = _item("dev_hp_01#woda", "dev_hp_01", DAY + SLOT, [1.0, 1.0])
    washer = _item("dev_wm_01", "dev_wm_01", DAY, [0.3], kind="program")
    later = _item("dev_ev_01", "dev_ev_01", DAY + 20 * SLOT, [1.0], kind="ev")

    planned = PlanRunService._plan_commands([house, water, washer, later])

    assert [item.action_id for item, _ in planned] == ["dev_hp_01#dom", "dev_hp_01#woda", "dev_wm_01", "dev_ev_01"]
    (_, house_command), (_, water_command) = planned[:2]
    assert house_command is water_command
    assert (house_command.start_at, house_command.profile_kwh) == (DAY, [0.5, 1.0, 1.0, 0.5, 0.5])
    assert planned[2][1] is not house_command and planned[3][1].profile_kwh == [1.0]


def test_profiles_of_one_device_that_do_not_overlap_stay_separate():
    from app.services.plan_run_service import PlanRunService

    morning = _item("dev_wh_01#1", "dev_wh_01", DAY, [1.0])
    evening = _item("dev_wh_01#2", "dev_wh_01", DAY + 40 * SLOT, [1.0])

    planned = PlanRunService._plan_commands([morning, evening])

    assert planned[0][1] is not planned[1][1]



def test_report_values_pv_sent_to_the_grid():
    from app.services.plan_run_report import _pv as report_pv

    hour = DAY + 12 * 4 * SLOT
    energy = _energy({
        "dev_pv_01": {hour + index * SLOT: -0.5 for index in range(4)},
        "dev_tv": {hour: 0.6, hour + 3 * SLOT: 0.2},
    })
    balance = HouseBalance({}, {}, {}, {hour: 0.4})

    pv = report_pv(_run([], energy, hour + 4 * SLOT, pv_devices=["dev_pv_01"], balance=balance), set())

    # Raport liczy autokonsumpcję w kwadransach: zużyto 0,5 + 0,2 kWh, resztę (1,3 kWh) oddano po 0,40 zł.
    assert (pv.production_kwh, pv.self_consumption_kwh, pv.export_kwh) == (2.0, 0.7, 1.3)
    assert pv.export_pln == pytest.approx(1.3 * 0.4)
    assert report_pv(_run([], energy, hour + 4 * SLOT, pv_devices=["dev_pv_01"]), set()).export_pln is None
