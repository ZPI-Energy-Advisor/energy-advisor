# ruff: noqa: F811 (fikstury db i home są parametrami testów)
"""ZP-114: rachunek przed i po planie w przebiegu symulacji – porównanie, odchylenia, PV i urządzenia stałe osobno."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.PlanRun import PlanRun
from test_energy_files import _headers, client
from test_home import db  # noqa: F401 (db: fixture)
from test_home_control import _hub_error, home  # noqa: F401 (home: fixture)
from test_home_events import _event, _report
from test_plan_run import (
    WASHER_IN_PLAN,
    _end,
    _home_with_files,
    _home_with_pv,
    _latest,
    _plan,
    _pv_action,
    _start,
    _store_events,
)


SLOT = timedelta(minutes=15)


def _actions(run: dict) -> dict[str, dict]:
    return {action["device_id"]: action for device in run["devices"] for action in device["actions"]}


def _items(plan: dict) -> dict[str, dict]:
    return {item["device_id"]: item for item in plan["items"]}


def _executed(run: dict, item: dict, *, scale: float = 1.0, until: datetime | None = None) -> list[dict]:
    """Zdarzenia urządzenia, które wykonało pozycję planu: start z komendą planu i energia z jej profilu."""
    start = datetime.fromisoformat(item["start"])
    action = _actions(run)[item["device_id"]]
    events = [_event(
        "device_started", item["device_id"], start.isoformat(),
        {"command_id": action["command_id"], "program_id": item.get("program_id"), "ref": None},
        simulation_id=run["simulation_id"],
    )]
    for index, kwh in enumerate(item["profile_kwh"]):
        slot = start + index * SLOT
        if kwh and (until is None or slot + SLOT <= until):
            events.append(_report(run["simulation_id"], item["device_id"], slot.isoformat(), kwh * scale))
    return events


def _finish(home, plan: dict) -> dict:
    """Zegar przebiegu mija koniec planu: przebieg jest wykonany, a raport pełny."""
    home.hub.clock_state["sim_time"] = plan["horizon_end"]
    return _latest_report(home)


def _latest_report(home) -> dict:
    response = _latest(home.owner)
    assert response.status_code == 200, response.text
    return response.json()


def _cost_of(items: list[dict], prices: dict[datetime, float]) -> float:
    return sum(
        kwh * prices[datetime.fromisoformat(item["start"]) + index * SLOT]
        for item in items for index, kwh in enumerate(item["profile_kwh"]) if kwh
    )


def _prices(plan: dict) -> dict[datetime, float]:
    return {datetime.fromisoformat(entry["start"]): entry["price_pln_kwh"] for entry in plan["prices"]}


# Porównanie


def test_plan_executed_as_planned_saves_what_plan_promised(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    items = _items(plan)
    _store_events(db, owner, [*_executed(run, items["dev_wm_01"]), *_executed(run, items["dev_ev_01"])])

    report = _finish(home, plan)

    assert report["status"] == "completed"
    cost = report["cost"]
    assert cost["complete"] is True
    assert cost["deviations"] == [] and cost["pending"] == [] and cost["excluded"] == []
    # Bez odchyleń rachunek to oszczędność planu (tolerancja 1%).
    assert cost["cost_before"] == pytest.approx(plan["cost_before"], rel=0.01, abs=0.01)
    assert cost["cost_after"] == pytest.approx(plan["cost_after"], rel=0.01, abs=0.01)
    assert cost["saving"] == pytest.approx(plan["saving"], rel=0.01, abs=0.01)
    assert cost["cost_after"] == pytest.approx(cost["planned_cost"], abs=0.01)
    if plan["cost_before"] > 0:
        assert cost["saving_percent"] == pytest.approx(cost["saving"] / cost["cost_before"] * 100, abs=0.1)
    devices = {device["device_id"]: device for device in cost["devices"]}
    assert set(devices) == {"dev_wm_01", "dev_ev_01"}
    assert devices["dev_ev_01"]["energy_after_kwh"] == pytest.approx(5.0, rel=0.01)
    assert devices["dev_ev_01"]["cost_after"] == pytest.approx(_cost_of([items["dev_ev_01"]], _prices(plan)), abs=0.01)


def test_device_using_other_energy_than_planned_is_a_deviation_but_stays_compared(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    items = _items(plan)
    _store_events(db, owner, [*_executed(run, items["dev_wm_01"], scale=0.5), *_executed(run, items["dev_ev_01"])])

    cost = _finish(home, plan)["cost"]

    deviation, = cost["deviations"]
    assert (deviation["kind"], deviation["device_id"], deviation["excluded"]) == ("energy_mismatch", "dev_wm_01", False)
    assert {device["device_id"] for device in cost["devices"]} == {"dev_wm_01", "dev_ev_01"}


def test_manual_switch_off_during_planned_work_excludes_device(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    items = _items(plan)
    washer_start = datetime.fromisoformat(items["dev_wm_01"]["start"])
    _store_events(db, owner, [
        *_executed(run, items["dev_wm_01"], until=washer_start + SLOT),
        _event("device_finished", "dev_wm_01", (washer_start + SLOT).isoformat(),
               {"interrupted": True, "ref": None}, simulation_id=run["simulation_id"]),
        *_executed(run, items["dev_ev_01"]),
    ])

    cost = _finish(home, plan)["cost"]

    deviation, = cost["deviations"]
    assert (deviation["kind"], deviation["device_name"], deviation["excluded"]) == ("interrupted", "Pralka Bosch", True)
    assert deviation["sim_time"] == (washer_start + SLOT).isoformat()
    assert cost["excluded"] == [{"device_id": "dev_wm_01", "device_name": "Pralka Bosch"}]
    # Porównanie zostaje dla auta, które pracowało według planu.
    device, = cost["devices"]
    assert device["device_id"] == "dev_ev_01"
    assert cost["cost_before"] == device["cost_before"]


def test_manual_start_of_planned_device_excludes_it(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    items = _items(plan)
    _store_events(db, owner, [
        *_executed(run, items["dev_wm_01"]),
        *_executed(run, items["dev_ev_01"]),
        # Drugie pranie wieczorem z „Mój dom”: komenda spoza planu.
        _event("device_started", "dev_wm_01", f"{plan['plan_date']}T21:00:00+02:00",
               {"command_id": "cmd_manual", "program_id": "cotton_60", "ref": None}, simulation_id=run["simulation_id"]),
    ])

    cost = _finish(home, plan)["cost"]

    assert [(deviation["kind"], deviation["device_id"]) for deviation in cost["deviations"]] == [("manual_start", "dev_wm_01")]
    assert [device["device_id"] for device in cost["devices"]] == ["dev_ev_01"]


def test_rejected_command_and_device_error_exclude_devices(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    home.hub.command_replies["dev_ev_01"] = _hub_error(404, "device_not_found", "Nie ma urządzenia w rejestrze")
    run = _start(owner, plan["id"]).json()
    _store_events(db, owner, [
        _event("device_error", "dev_wm_01", f"{plan['plan_date']}T08:00:00+02:00",
               {"code": "command_failed", "message": "Pralka nie wykonała komendy"}, simulation_id=run["simulation_id"]),
    ])

    cost = _finish(home, plan)["cost"]

    kinds = {deviation["device_id"]: (deviation["kind"], deviation["excluded"]) for deviation in cost["deviations"]}
    assert kinds == {"dev_ev_01": ("rejected", True), "dev_wm_01": ("device_error", True)}
    assert (cost["devices"], cost["cost_before"], cost["saving_percent"]) == ([], 0.0, None)


# Poza porównaniem


def test_fixed_devices_switched_on_by_hand_are_listed_separately(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    items = _items(plan)
    lamp_slot = datetime.fromisoformat(f"{plan['plan_date']}T19:00:00+02:00")
    _store_events(db, owner, [
        *_executed(run, items["dev_wm_01"]),
        *_executed(run, items["dev_ev_01"]),
        _event("device_started", "dev_lamp_01", lamp_slot.isoformat(), {"command_id": "cmd_lamp"},
               simulation_id=run["simulation_id"]),
        _report(run["simulation_id"], "dev_lamp_01", lamp_slot.isoformat(), 0.2),
    ])

    cost = _finish(home, plan)["cost"]

    manual, = cost["manual"]
    assert (manual["device_name"], manual["energy_kwh"]) == ("Lampa", 0.2)
    assert manual["cost"] == pytest.approx(0.2 * _prices(plan)[lamp_slot], abs=0.01)
    assert cost["manual_cost"] == manual["cost"]
    # Lampa nie zmienia porównania ani nie jest odchyleniem.
    assert cost["deviations"] == []
    assert cost["saving"] == pytest.approx(plan["saving"], rel=0.01, abs=0.01)


def test_pv_is_outside_comparison_and_shows_what_plan_took_from_panels(home, db):
    owner = _home_with_pv(home, [_pv_action("2026-10-05", -6.4)])
    plan = _plan(owner, devices=[WASHER_IN_PLAN])
    run = _start(owner, plan["id"]).json()
    washer = _items(plan)["dev_wm_01"]
    washer_start = datetime.fromisoformat(washer["start"])
    _store_events(db, owner, [
        *_executed(run, washer),
        # Produkcja PV w pierwszym kwadransie prania: więcej, niż pralka zużywa.
        _report(run["simulation_id"], "dev_pv_01", washer_start.isoformat(), -1.0),
    ])

    cost = _finish(home, plan)["cost"]

    first_slot = washer["profile_kwh"][0]
    assert cost["pv"] == {
        "production_kwh": 1.0,
        "self_consumption_kwh": pytest.approx(first_slot, abs=0.001),
        "plan_from_pv_kwh": pytest.approx(first_slot, abs=0.001),
        "plan_kwh": pytest.approx(sum(washer["profile_kwh"]), abs=0.001),
    }
    assert cost["manual"] == []
    # Koszt pralki to jej energia razy ceny, bez odejmowania PV: tak samo liczy plan.
    assert cost["saving"] == pytest.approx(plan["saving"], rel=0.01, abs=0.01)


def test_grid_limit_exceeded_with_manual_devices_is_a_deviation(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    stored = db.get(PlanRun, run["id"])
    stored.tariff = {**stored.tariff, "max_grid_kw": 3.0}
    db.commit()
    slot = datetime.fromisoformat(f"{plan['plan_date']}T19:00:00+02:00")
    _store_events(db, owner, [
        _report(run["simulation_id"], "dev_lamp_01", slot.isoformat(), 1.0),  # 4 kW w kwadransie.
        _report(run["simulation_id"], "dev_lamp_01", (slot + SLOT).isoformat(), 1.1),
    ])

    cost = _finish(home, plan)["cost"]

    grid = [deviation for deviation in cost["deviations"] if deviation["kind"] == "grid_limit"]
    assert len(grid) == 1
    assert (grid[0]["sim_time"], grid[0]["end"]) == (slot.isoformat(), (slot + 2 * SLOT).isoformat())
    assert "4,40 kW" in grid[0]["message"] and "3,00 kW" in grid[0]["message"]


# Raport niepełny i zapis


def test_end_before_plan_end_compares_only_finished_devices(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    items = _items(plan)
    washer_end = datetime.fromisoformat(items["dev_wm_01"]["end"])
    assert washer_end < datetime.fromisoformat(items["dev_ev_01"]["end"])
    _store_events(db, owner, _executed(run, items["dev_wm_01"]))
    home.hub.clock_state["sim_time"] = washer_end.isoformat()

    ended = _end(owner, run["id"]).json()

    cost = ended["cost"]
    assert (ended["status"], cost["complete"]) == ("ended", False)
    assert [device["device_id"] for device in cost["devices"]] == ["dev_wm_01"]
    assert cost["pending"] == [{"device_id": "dev_ev_01", "device_name": "Ładowarka EV"}]
    assert db.get(PlanRun, run["id"]).report["complete"] is False


def test_report_is_saved_in_run_history_and_frozen_after_events_settle(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    items = _items(plan)
    _store_events(db, owner, [*_executed(run, items["dev_wm_01"]), *_executed(run, items["dev_ev_01"])])
    saving = _finish(home, plan)["cost"]["saving"]

    history = client.get("/api/v1/home/plan-runs", headers=_headers(owner))

    assert history.status_code == 200
    entry, = history.json()
    assert (entry["id"], entry["status"], entry["complete"], entry["saving"], entry["deviations"]) == (
        run["id"], "completed", True, saving, 0,
    )
    stored = db.get(PlanRun, run["id"])
    db.refresh(stored)
    assert stored.report["saving"] == saving

    # Zdarzenia, które doszły po zamknięciu, jeszcze się liczą, a po chwili raport już się nie zmienia.
    stored.ended_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    _store_events(db, owner, [_event(
        "device_started", "dev_wm_01", f"{plan['plan_date']}T23:00:00+02:00", {"command_id": "cmd_late"},
        simulation_id=run["simulation_id"],
    )])
    detail = client.get(f"/api/v1/home/plan-runs/{run['id']}", headers=_headers(owner))
    assert detail.status_code == 200
    assert detail.json()["cost"]["saving"] == saving
    assert detail.json()["cost"]["deviations"] == []


def test_previous_run_superseded_by_new_start_keeps_its_report(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    first = _start(owner, plan["id"]).json()
    items = _items(plan)
    _store_events(db, owner, _executed(first, items["dev_wm_01"]))

    _start(owner, plan["id"])

    stored = db.get(PlanRun, first["id"])
    db.refresh(stored)
    assert stored.status == "superseded"
    assert stored.report is not None and stored.report["complete"] is False


def test_other_users_run_is_not_found(home):
    owner = _home_with_files(home)
    run = _start(owner, _plan(owner)["id"]).json()

    response = client.get(f"/api/v1/home/plan-runs/{run['id']}", headers=_headers(home.other))

    assert response.status_code in (403, 404)


def test_run_from_before_report_has_no_cost(home, db):
    owner = _home_with_files(home)
    run = _start(owner, _plan(owner)["id"]).json()
    stored = db.get(PlanRun, run["id"])
    stored.tariff = None
    db.commit()

    assert _latest(owner).json()["cost"] is None
