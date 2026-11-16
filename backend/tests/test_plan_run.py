# ruff: noqa: F811 (fikstury db i home są parametrami testów)
"""ZP-113: wykonanie zatwierdzonego planu dnia w symulacji – jedno żądanie do huba, przebieg w bazie, raport."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.DayPlan import DayPlan
from app.models.PlanRun import PlanRun
from app.repositories.home_event_repository import HomeEventRepository
from app.schemas.smart_home import MAX_BATCH_COMMANDS, CommandType, HubCommand, HubCommandResult, HubEvent
from app.services.home_control_service import send_batch
from app.services.plan_run_service import (
    PLAN_FAILED_MESSAGE,
    PLAN_NOT_APPROVED_MESSAGE,
    PLAN_NOT_FOUND_MESSAGE,
    PLAN_OUTDATED_MESSAGE,
    RUN_NOT_FOUND_MESSAGE,
)
from test_day_plan import WARSAW, _create
from test_energy_files import _headers, client
from test_home import HEAT_PUMP, LAMP, WASHER, _devices_file, _upload, db  # noqa: F401 (db: fixture)
from test_home_control import _file, _hub_error, home  # noqa: F401 (home: fixture)
from test_home_events import _event, _report
from test_planning_preferences import EV, _put, _windows


PLAN_DAY = "2026-10-12"  # Dzień planu w test_day_plan; historia w plikach jest z 05.10.


def _plan(owner, *, approve: bool = True, plan_date: str | None = None, devices: list[dict] | None = None) -> dict:
    """Plan z pralką (program) i autem (ładowanie z przerwami), domyślnie zatwierdzony."""
    assert _put(owner, {"devices": devices or [
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))},
        {"device_id": "dev_ev_01", "enabled": True, "windows": _windows(("18:00", "07:00")), "energy_kwh": 5},
    ]}).status_code == 200
    response = _create(owner, {"plan_date": plan_date} if plan_date else None)
    assert response.status_code == 201, response.text
    plan = response.json()
    if approve:
        assert client.post(f"/api/v1/planning/plans/{plan['id']}/approve", headers=_headers(owner)).status_code == 200
    return plan


def _home_with_files(home, *entries):
    assert _upload(home.owner, _devices_file(*(entries or (WASHER, EV, LAMP)))).status_code == 200
    home.hub.use_clock_state()
    return home.owner


def _start(user, plan_id):
    return client.post("/api/v1/home/plan-runs", json={"plan_id": str(plan_id)}, headers=_headers(user))


def _latest(user):
    return client.get("/api/v1/home/plan-runs/latest", headers=_headers(user))


def _end(user, run_id):
    return client.post(f"/api/v1/home/plan-runs/{run_id}/end", headers=_headers(user))


def _by_device(batch: list[dict]) -> dict[str, list[dict]]:
    commands: dict[str, list[dict]] = {}
    for body in batch:
        commands.setdefault(body["device_id"], []).append(body)
    return commands


def _store_events(db, owner, events: list[dict]) -> None:
    repository = HomeEventRepository(db)
    repository.insert_new(owner.id, [HubEvent.model_validate(event) for event in events])
    repository.commit()


# Uruchomienie


def test_approved_plan_goes_to_hub_in_one_request_after_new_day_and_before_clock_starts(home):
    owner = _home_with_files(home)
    plan = _plan(owner)
    items = {item["action_id"]: item for item in plan["items"]}

    response = _start(owner, plan["id"])

    assert response.status_code == 201, response.text
    assert home.hub.log == [
        "clock ['running']",
        "clock ['restart', 'sim_time']",
        "commands ['start_program dev_wm_01', 'run_profile dev_ev_01']",
        "clock ['running', 'stop_at']",
    ]
    assert home.hub.clock_updates[1] == {"sim_time": f"{PLAN_DAY}T00:00:00+02:00", "restart": True}
    # Zegar sam stanie o końcu planu (06:00 następnego dnia).
    assert home.hub.clock_updates[-1] == {"running": True, "stop_at": plan["horizon_end"]}
    assert [update.get("running") for update in (home.hub.clock_updates[0], home.hub.clock_updates[-1])] == [False, True]
    commands = _by_device(home.hub.batches[0])
    washer, = commands["dev_wm_01"]
    assert washer == {"device_id": "dev_wm_01", "command": "start_program", "program_id": "cotton_60",
                      "start_at": items["dev_wm_01"]["start"]}
    ev, = commands["dev_ev_01"]
    assert (ev["start_at"], ev["profile_kwh"]) == (items["dev_ev_01"]["start"], items["dev_ev_01"]["profile_kwh"])
    assert "ref" not in ev  # ref opisuje akcje z historii, a plan łączy się ze zdarzeniami przez command_id.

    run = response.json()
    assert (run["status"], run["plan_id"], run["plan_date"]) == ("running", plan["id"], PLAN_DAY)
    assert (run["horizon_start"], run["horizon_end"]) == (plan["horizon_start"], plan["horizon_end"])
    assert {device["device_id"]: device["planned_kwh"] for device in run["devices"]} == {
        "dev_wm_01": items["dev_wm_01"]["energy_kwh"], "dev_ev_01": items["dev_ev_01"]["energy_kwh"],
    }
    assert all(action["status"] == "scheduled" for device in run["devices"] for action in device["actions"])


def test_plan_commands_carry_planned_energy(home):
    owner = _home_with_files(home)
    plan = _plan(owner)
    _start(owner, plan["id"])

    ev, = _by_device(home.hub.batches[0])["dev_ev_01"]
    assert sum(ev["profile_kwh"]) == pytest.approx(5.0)
    # Program pralki z rejestru huba ma energię pozycji planu: 0,6 + 0,5 + 0,3 kWh.
    assert _items_energy(plan, "dev_wm_01") == pytest.approx(1.4)


def _items_energy(plan: dict, device_id: str) -> float:
    return sum(item["energy_kwh"] for item in plan["items"] if item["device_id"] == device_id)


def test_fixed_devices_are_not_replayed_in_plan_run(home):
    # Symulacja planu pokazuje plan: lampa z historii (05.10) nie rusza, a jej akcja nie trafia do huba.
    owner = _home_with_files(home)
    plan = _plan(owner)

    run = _start(owner, plan["id"]).json()

    assert set(_by_device(home.hub.batches[0])) == {"dev_wm_01", "dev_ev_01"}
    assert (run["history_day"], run["replayed_devices"]) == (None, [])
    assert run["replay"] == {"actions": 0, "devices": 0, "skipped_devices": [], "rejected_actions": 0}


def test_unticked_heat_pump_replays_plan_day_when_it_has_own_history(home):
    owner = _home_with_files(home, WASHER, HEAT_PUMP, LAMP)
    washer = {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))}
    plan = _plan(owner, plan_date="2026-10-05", devices=[washer, {"device_id": "dev_hp_01", "enabled": False}])

    run = _start(owner, plan["id"]).json()

    heat_pump, = _by_device(home.hub.batches[0])["dev_hp_01"]
    assert (run["history_day"], heat_pump["start_at"]) == ("2026-10-05", "2026-10-05T12:00:00+02:00")


def test_heat_pump_unticked_in_plan_replays_its_history_and_ticked_one_follows_plan(home):
    owner = _home_with_files(home, WASHER, HEAT_PUMP, LAMP)
    washer = {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))}
    plan = _plan(owner, devices=[washer, {"device_id": "dev_hp_01", "enabled": False}])

    run = _start(owner, plan["id"]).json()

    commands = _by_device(home.hub.batches[0])
    heat_pump, = commands["dev_hp_01"]
    assert (heat_pump["ref"], heat_pump["start_at"]) == ("act_hp_1", f"{PLAN_DAY}T12:00:00+02:00")
    assert "dev_lamp_01" not in commands
    assert (run["history_day"], run["replayed_devices"]) == ("2026-10-05", ["dev_hp_01"])
    assert run["replay"]["actions"] == 1

    planned = _plan(owner, devices=[washer, {"device_id": "dev_hp_01", "enabled": True, "shift_hours": 1}])
    _start(owner, planned["id"])

    heat_pump, = _by_device(home.hub.batches[1])["dev_hp_01"]
    item, = [item for item in planned["items"] if item["device_id"] == "dev_hp_01"]
    assert ("ref" not in heat_pump, heat_pump["start_at"]) == (True, item["start"])


def test_unticked_heat_pump_replays_only_day_without_following_night(home):
    # Jak plan dla zaznaczonej pompy: blok z nocy po dniu referencyjnym należy do kolejnej doby.
    period = {"start": "2026-10-05T00:00:00+02:00", "end": "2026-10-07T00:00:00+02:00"}
    night = {**HEAT_PUMP["actions"][0], "action_id": "act_hp_night",
             "action_start": "2026-10-06T02:00:00+02:00", "action_end": "2026-10-06T03:00:00+02:00"}
    entries = {"devices": [WASHER["device"], HEAT_PUMP["device"]],
               "actions": [*WASHER["actions"], *HEAT_PUMP["actions"], night]}
    assert _upload(home.owner, _file(period, entries["devices"], entries["actions"])).status_code == 200
    home.hub.use_clock_state()
    washer = {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))}
    plan = _plan(home.owner, plan_date="2026-10-05", devices=[washer, {"device_id": "dev_hp_01", "enabled": False}])

    run = _start(home.owner, plan["id"]).json()

    heat_pump = _by_device(home.hub.batches[0])["dev_hp_01"]
    assert [command["ref"] for command in heat_pump] == ["act_hp_1"]
    assert (run["history_day"], run["replay"]["actions"]) == ("2026-10-05", 1)


def test_draft_plan_cannot_run(home):
    owner = _home_with_files(home)
    plan = _plan(owner, approve=False)

    response = _start(owner, plan["id"])

    assert (response.status_code, response.json()["detail"]) == (409, PLAN_NOT_APPROVED_MESSAGE)
    assert home.hub.log == []


def test_plan_saved_before_simulation_fields_asks_to_replan(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    stored = db.get(DayPlan, plan["id"])
    stored.result = {**stored.result, "items": [
        {key: value for key, value in item.items() if key not in ("program_id", "profile_kwh")}
        for item in stored.result["items"]
    ]}
    db.commit()

    response = _start(owner, plan["id"])

    assert (response.status_code, response.json()["detail"]) == (409, PLAN_OUTDATED_MESSAGE)
    assert home.hub.log == []


def test_unknown_plan_and_other_users_are_refused(home):
    owner = _home_with_files(home)
    plan = _plan(owner)

    assert (_start(owner, uuid4()).status_code, _start(owner, uuid4()).json()["detail"]) == (404, PLAN_NOT_FOUND_MESSAGE)
    assert _start(home.other, plan["id"]).status_code == 403
    assert _latest(home.other).status_code == 403
    assert home.hub.log == []


def test_rejected_command_is_reported_and_does_not_block_other_devices(home):
    owner = _home_with_files(home)
    plan = _plan(owner)
    home.hub.command_replies["dev_ev_01"] = _hub_error(404, "device_not_found", "Nie ma urządzenia w rejestrze")

    run = _start(owner, plan["id"]).json()

    actions = {device["device_id"]: device["actions"][0] for device in run["devices"]}
    assert (actions["dev_ev_01"]["status"], actions["dev_ev_01"]["code"]) == ("rejected", "device_not_found")
    assert actions["dev_ev_01"]["detail"] == "Nie ma urządzenia w rejestrze"
    assert actions["dev_wm_01"]["status"] == "scheduled"
    assert run["status"] == "running"
    assert home.hub.clock_updates[-1]["running"] is True


def test_hub_failure_while_sending_plan_keeps_clock_stopped_and_saves_no_run(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    home.hub.commands_down = True

    response = _start(owner, plan["id"])

    assert (response.status_code, response.json()["detail"]) == (502, PLAN_FAILED_MESSAGE)
    assert home.hub.clock_updates[-1] == {"sim_time": f"{PLAN_DAY}T00:00:00+02:00", "restart": True}
    assert db.execute(select(PlanRun).where(PlanRun.user_id == owner.id)).first() is None


def test_starting_again_supersedes_previous_run(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    first = _start(owner, plan["id"]).json()

    second = _start(owner, plan["id"]).json()

    assert second["simulation_id"] != first["simulation_id"]
    assert db.get(PlanRun, first["id"]).status == "superseded"
    assert _latest(owner).json()["id"] == second["id"]


def test_run_finished_in_hub_before_new_start_counts_as_completed(home, db):
    # Hub stanął o końcu planu, ale nikt nie otworzył „Mój dom”: przebieg jest wykonany, a nie przerwany.
    owner = _home_with_files(home)
    plan = _plan(owner)
    first = _start(owner, plan["id"]).json()
    home.hub.clock_state.update(sim_time=plan["horizon_end"], running=False, stop_at=None)

    _start(owner, plan["id"])

    stored = db.get(PlanRun, first["id"])
    db.refresh(stored)
    assert (stored.status, stored.ended_sim_time) == ("completed", datetime.fromisoformat(plan["horizon_end"]))


def test_commands_over_contract_limit_go_in_several_requests():
    sent = []

    class Hub:
        def send_commands(self, commands):
            sent.append(len(commands))
            return [HubCommandResult(device_id=command.device_id, status="scheduled") for command in commands]

    commands = [HubCommand(device_id="dev_lt_01", command=CommandType.ON)] * (MAX_BATCH_COMMANDS + 1)

    results = send_batch(Hub(), commands, PLAN_FAILED_MESSAGE)

    assert (sent, len(results)) == ([MAX_BATCH_COMMANDS, 1], MAX_BATCH_COMMANDS + 1)


# Raport i koniec przebiegu


def test_latest_is_null_without_runs(home):
    owner = _home_with_files(home)

    response = _latest(owner)

    assert (response.status_code, response.json()) == (200, None)


def test_report_shows_energy_of_plan_devices_so_far_and_device_errors(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    simulation_id = run["simulation_id"]
    washer_start = datetime.fromisoformat(next(item["start"] for item in plan["items"] if item["device_id"] == "dev_wm_01"))
    _store_events(db, owner, [
        _report(simulation_id, "dev_wm_01", washer_start.isoformat(), 0.6),
        _report("sim_other", "dev_wm_01", washer_start.isoformat(), 5.0),  # Inny przebieg się nie liczy.
        _event("device_error", "dev_ev_01", f"{PLAN_DAY}T22:00:00+02:00",
               {"code": "device_unreachable", "message": "Brak odpowiedzi urządzenia"}, simulation_id=simulation_id),
    ])
    home.hub.clock_state["sim_time"] = (washer_start + timedelta(minutes=15)).isoformat()

    report = _latest(owner).json()

    devices = {device["device_id"]: device for device in report["devices"]}
    assert devices["dev_wm_01"]["actual_kwh"] == pytest.approx(0.6)
    assert devices["dev_ev_01"]["actual_kwh"] == 0.0
    assert report["actual_kwh"] == pytest.approx(0.6)
    assert report["sim_time"] == (washer_start + timedelta(minutes=15)).astimezone(WARSAW).isoformat()
    error, = report["errors"]
    assert (error["device_name"], error["code"], error["sim_time"]) == (
        "Ładowarka EV", "device_unreachable", f"{PLAN_DAY}T22:00:00+02:00",
    )


def test_run_completes_when_clock_passes_end_of_plan(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    home.hub.clock_state["sim_time"] = (datetime.fromisoformat(plan["horizon_end"]) + timedelta(minutes=15)).isoformat()

    report = _latest(owner).json()

    assert (report["status"], report["sim_time"]) == ("completed", plan["horizon_end"])
    stored = db.get(PlanRun, run["id"])
    db.refresh(stored)
    assert stored.status == "completed" and stored.ended_at is not None


def test_new_day_set_on_clock_supersedes_run(home):
    owner = _home_with_files(home)
    run = _start(owner, _plan(owner)["id"]).json()

    client.put("/api/v1/home/clock", json={"day": "2026-10-05"}, headers=_headers(owner))

    report = _latest(owner).json()
    assert (report["id"], report["status"]) == (run["id"], "superseded")


def test_end_stops_clock_and_closes_run_once(home):
    owner = _home_with_files(home)
    run = _start(owner, _plan(owner)["id"]).json()
    home.hub.clock_state["sim_time"] = f"{PLAN_DAY}T09:00:00+02:00"

    ended = _end(owner, run["id"])

    assert ended.status_code == 200
    body = ended.json()
    assert (body["status"], body["sim_time"]) == ("ended", f"{PLAN_DAY}T09:00:00+02:00")
    # Bez zatrzymania o 06:00: ręczny Start po „Zakończ” nie stanie nagle o końcu planu.
    assert home.hub.clock_updates[-1] == {"running": False, "stop_at": None}
    updates = len(home.hub.clock_updates)
    assert _end(owner, run["id"]).json()["status"] == "ended"
    assert len(home.hub.clock_updates) == updates  # Zakończony przebieg nie zatrzymuje zegara drugi raz.


def test_end_of_unknown_run_is_not_found(home):
    owner = _home_with_files(home)

    response = _end(owner, uuid4())

    assert (response.status_code, response.json()["detail"]) == (404, RUN_NOT_FOUND_MESSAGE)


def test_report_keeps_last_known_state_when_hub_is_down(home):
    owner = _home_with_files(home)
    run = _start(owner, _plan(owner)["id"]).json()
    home.hub.down = True

    report = _latest(owner)

    assert (report.status_code, report.json()["status"], report.json()["id"]) == (200, "running", run["id"])

