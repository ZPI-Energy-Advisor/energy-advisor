# ruff: noqa: F811 (fikstury db i home są parametrami testów)
"""ZP-113: wykonanie zatwierdzonego planu dnia w symulacji – jedno żądanie do huba, przebieg w bazie, raport."""

import json
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
from test_home_control import _hub_error, home  # noqa: F401 (home: fixture)
from test_home_events import _event, _report
from test_planning_preferences import EV, _put, _windows


PLAN_DAY = "2026-10-12"  # Dzień planu w test_day_plan; historia w plikach jest z 05.10.
PV = {"device_id": "dev_pv_01", "device_name": "Instalacja PV", "device_type": "pv_inverter",
      "device_category": "OZE", "max_power_kw": 5.0, "flexibility": {"mode": "fixed"}}
WASHER_IN_PLAN = {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))}


def _file(period: dict, devices: list[dict], actions: list[dict]) -> bytes:
    return json.dumps({"period": period, "devices": devices, "energy_usage": actions}).encode()


def _pv_action(day: str, energy_kwh: float) -> dict:
    """Produkcja PV 10:00–14:00 danego dnia (ujemna energia)."""
    return {"action_id": f"act_pv_{day}", "device_id": "dev_pv_01", "action_start": f"{day}T10:00:00+02:00",
            "action_end": f"{day}T14:00:00+02:00", "energy_kwh": energy_kwh}


def _home_with_pv(home, pv_actions: list[dict]):
    """Pralka z historią z 05.10 i PV z podanymi akcjami."""
    period = {"start": "2026-10-05T00:00:00+02:00", "end": "2026-10-13T00:00:00+02:00"}
    content = _file(period, [WASHER["device"], PV], [*WASHER["actions"], *pv_actions])
    assert _upload(home.owner, content).status_code == 200
    home.hub.use_clock_state()
    return home.owner


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
    # Zegar sam stanie o końcu przebiegu: auto ładuje się w nocy, więc koniec jego ładowania (przed 06:00).
    run_end = items["dev_ev_01"]["end"]
    assert home.hub.clock_updates[-1] == {"running": True, "stop_at": run_end}
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
    assert (run["horizon_start"], run["horizon_end"]) == (plan["horizon_start"], run_end)
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
    # Urządzenia stałe startują wyłączone i włącza je użytkownik: akcja lampy z historii nie trafia do huba.
    owner = _home_with_files(home)
    plan = _plan(owner)

    run = _start(owner, plan["id"]).json()

    assert set(_by_device(home.hub.batches[0])) == {"dev_wm_01", "dev_ev_01"}
    assert (run["history_day"], run["replayed_devices"]) == (None, [])
    assert run["replay"] == {"actions": 0, "devices": 0, "skipped_devices": [], "rejected_actions": 0}


def test_pv_produces_like_reference_day_moved_to_plan_day(home):
    owner = _home_with_pv(home, [_pv_action("2026-10-05", -6.4)])
    plan = _plan(owner, devices=[WASHER_IN_PLAN])

    run = _start(owner, plan["id"]).json()

    pv, = _by_device(home.hub.batches[0])["dev_pv_01"]
    assert (pv["command"], pv["ref"], pv["start_at"]) == ("run_profile", "act_pv_2026-10-05", f"{PLAN_DAY}T10:00:00+02:00")
    # Profil i energia z dnia referencyjnego (tolerancja 1%), z ujemnym znakiem.
    assert len(pv["profile_kwh"]) == 16
    assert sum(pv["profile_kwh"]) == pytest.approx(-6.4, rel=0.01)
    assert all(kwh < 0 for kwh in pv["profile_kwh"])
    assert run["history_day"] == "2026-10-05"
    assert run["replayed_devices"] == [{
        "device_id": "dev_pv_01", "device_name": "Instalacja PV", "history_day": "2026-10-05",
        "history_kwh": -6.4, "actual_kwh": 0.0,
    }]


def test_reference_day_is_last_day_with_history_before_plan_day(home):
    # „Wczoraj” względem doby planu, jak w planie: historia z dnia planu i późniejsza (plan demo) się nie liczy.
    owner = _home_with_pv(home, [
        _pv_action("2026-10-10", -3.0), _pv_action("2026-10-11", -5.0), _pv_action("2026-10-12", -9.0),
    ])
    plan = _plan(owner, devices=[WASHER_IN_PLAN])

    run = _start(owner, plan["id"]).json()

    pv, = _by_device(home.hub.batches[0])["dev_pv_01"]
    assert (run["history_day"], pv["ref"]) == ("2026-10-11", "act_pv_2026-10-11")
    assert sum(pv["profile_kwh"]) == pytest.approx(-5.0)


def test_each_device_has_its_own_reference_day_like_in_plan(home):
    # Pliki PV sięgają 11.10, a pompy ciepła 05.10: plan bierze dla pompy 05.10, więc symulacja też.
    owner = _home_with_pv(home, [_pv_action("2026-10-11", -5.0)])
    assert _upload(owner, _devices_file(HEAT_PUMP), name="pompa.json").status_code == 200
    plan = _plan(owner, devices=[WASHER_IN_PLAN, {"device_id": "dev_hp_01", "enabled": False}])

    run = _start(owner, plan["id"]).json()

    commands = _by_device(home.hub.batches[0])
    assert (commands["dev_pv_01"][0]["ref"], commands["dev_hp_01"][0]["ref"]) == ("act_pv_2026-10-11", "act_hp_1")
    days = {device["device_id"]: device["history_day"] for device in run["replayed_devices"]}
    assert days == {"dev_pv_01": "2026-10-11", "dev_hp_01": "2026-10-05"}
    assert run["history_day"] == "2026-10-11"  # Najnowszy z dni urządzeń.


def test_report_compares_pv_with_reference_day(home, db):
    owner = _home_with_pv(home, [_pv_action("2026-10-05", -6.4)])
    run = _start(owner, _plan(owner, devices=[WASHER_IN_PLAN])["id"]).json()
    _store_events(db, owner, [_report(run["simulation_id"], "dev_pv_01", f"{PLAN_DAY}T10:00:00+02:00", -0.4)])
    home.hub.clock_state["sim_time"] = f"{PLAN_DAY}T10:15:00+02:00"

    report = _latest(owner).json()

    pv, = report["replayed_devices"]
    assert (pv["history_kwh"], pv["actual_kwh"]) == (-6.4, pytest.approx(-0.4))
    # Bilans planu obejmuje tylko jego urządzenia.
    assert report["actual_kwh"] == 0.0


def test_unticked_heat_pump_uses_latest_day_when_plan_is_before_all_history(home):
    # Plan demo na dzień z historii, bez wcześniejszego: bierzemy ostatni dzień z historii w ogóle.
    owner = _home_with_files(home, WASHER, HEAT_PUMP, LAMP)
    plan = _plan(owner, plan_date="2026-10-05", devices=[WASHER_IN_PLAN, {"device_id": "dev_hp_01", "enabled": False}])

    run = _start(owner, plan["id"]).json()

    heat_pump, = _by_device(home.hub.batches[0])["dev_hp_01"]
    assert (run["history_day"], heat_pump["start_at"]) == ("2026-10-05", "2026-10-05T12:00:00+02:00")


def test_heat_pump_unticked_in_plan_replays_its_history_and_ticked_one_follows_plan(home):
    owner = _home_with_files(home, WASHER, HEAT_PUMP, LAMP)
    plan = _plan(owner, devices=[WASHER_IN_PLAN, {"device_id": "dev_hp_01", "enabled": False}])

    run = _start(owner, plan["id"]).json()

    commands = _by_device(home.hub.batches[0])
    heat_pump, = commands["dev_hp_01"]
    assert (heat_pump["ref"], heat_pump["start_at"]) == ("act_hp_1", f"{PLAN_DAY}T12:00:00+02:00")
    assert "dev_lamp_01" not in commands
    assert run["history_day"] == "2026-10-05"
    assert [device["device_id"] for device in run["replayed_devices"]] == ["dev_hp_01"]
    assert run["replay"]["actions"] == 1

    planned = _plan(owner, devices=[WASHER_IN_PLAN, {"device_id": "dev_hp_01", "enabled": True, "shift_hours": 1}])
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
    # Dzień referencyjny dla doby 06.10 to 05.10; blok z 02:00 06.10 jest już w nocy po nim.
    plan = _plan(home.owner, plan_date="2026-10-06", devices=[WASHER_IN_PLAN, {"device_id": "dev_hp_01", "enabled": False}])

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
    home.hub.clock_state.update(sim_time=first["horizon_end"], running=False, stop_at=None)

    _start(owner, plan["id"])

    stored = db.get(PlanRun, first["id"])
    db.refresh(stored)
    assert (stored.status, stored.ended_sim_time) == ("completed", datetime.fromisoformat(first["horizon_end"]))


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
    home.hub.clock_state["sim_time"] = (datetime.fromisoformat(run["horizon_end"]) + timedelta(minutes=15)).isoformat()

    report = _latest(owner).json()

    assert (report["status"], report["sim_time"]) == ("completed", run["horizon_end"])
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
    # Bez zatrzymania o 06:00 i bez reszty planu w kolejce: ręczny Start po „Zakończ” nie stanie nagle
    # o końcu planu ani nie uruchomi np. ładowania auta.
    assert home.hub.clock_updates[-1] == {"running": False, "stop_at": None}
    assert home.hub.log[-2:] == ["cancel scheduled", "clock ['running', 'stop_at']"]
    log = len(home.hub.log)
    assert _end(owner, run["id"]).json()["status"] == "ended"
    assert len(home.hub.log) == log  # Zakończony przebieg nie zmienia już niczego w hubie.


def test_hub_failure_while_cancelling_queue_keeps_run_open_to_retry(home):
    owner = _home_with_files(home)
    run = _start(owner, _plan(owner)["id"]).json()
    home.hub.commands_down = True

    assert _end(owner, run["id"]).status_code == 503
    assert _latest(owner).json()["status"] == "running"
    # Zegar dalej ma zatrzymanie o końcu planu: Start zamiast ponownego „Zakończ” nie przeciągnie doby.
    assert home.hub.clock_state["stop_at"] == run["horizon_end"]

    home.hub.commands_down = False
    assert _end(owner, run["id"]).json()["status"] == "ended"
    assert home.hub.log[-2:] == ["cancel scheduled", "clock ['running', 'stop_at']"]


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



# Bilans w stanie domu (ZP-110): przebieg planu liczy się od jego początku, także po północy drugiego dnia


def _today(user) -> dict:
    response = client.get("/api/v1/home/state", headers=_headers(user))
    assert response.status_code == 200, response.text
    return response.json()["today"]


def test_home_state_counts_plan_run_from_its_start_also_after_midnight(home, db):
    owner = _home_with_files(home)
    run = _start(owner, _plan(owner)["id"]).json()
    simulation_id = run["simulation_id"]
    _store_events(db, owner, [
        _report(simulation_id, "dev_wm_01", f"{PLAN_DAY}T10:00:00+02:00", 0.6),
        _report(simulation_id, "dev_ev_01", "2026-10-13T01:00:00+02:00", 0.9),
    ])
    home.hub.clock_state["sim_time"] = "2026-10-13T02:00:00+02:00"

    today = _today(owner)

    # Po północy doba kalendarzowa miałaby tylko 0,9 kWh z nocy; bilans obejmuje cały plan, jak raport.
    assert (today["period"], today["plan_date"]) == ("plan_run", PLAN_DAY)
    assert (today["day_start"], today["until"]) == (run["horizon_start"], "2026-10-13T02:00:00+02:00")
    assert today["consumption_kwh"] == pytest.approx(1.5)


def test_home_state_after_end_of_plan_horizon_counts_ordinary_day(home, db):
    owner = _home_with_files(home)
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    _store_events(db, owner, [_report(run["simulation_id"], "dev_wm_01", f"{PLAN_DAY}T10:00:00+02:00", 0.6)])
    home.hub.clock_state["sim_time"] = (datetime.fromisoformat(plan["horizon_end"]) + timedelta(hours=1)).isoformat()

    today = _today(owner)

    assert (today["period"], today["plan_date"]) == ("day", None)
    assert today["day_start"] == "2026-10-13T00:00:00+02:00"
    assert today["consumption_kwh"] == 0.0


# Pasek czasu i temperatura wody na ekranie „Mój dom” (ZP-110)


def test_run_carries_plan_prices_and_water_temperature_from_plan(home):
    from test_planning_preferences import WATER_HEATER

    owner = _home_with_files(home, WASHER, EV, WATER_HEATER)
    plan = _plan(owner, devices=[
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))},
        {"device_id": "dev_wh_01", "enabled": True, "ready_times": ["07:00", "19:00"]},
    ])

    run = _start(owner, plan["id"]).json()

    assert run["prices"] == plan["prices"]
    assert run["prices_approximate_from"] == plan["approximate_from"]
    heater, = run["water_heaters"]
    planned, = plan["water_heaters"]
    assert heater["device_id"] == "dev_wh_01"
    assert heater["temperatures"] == [
        {"start": entry["start"], "temp_c": entry["after"]} for entry in planned["temperatures"]
    ]


def test_run_without_water_heater_has_no_water_temperature(home):
    owner = _home_with_files(home)

    run = _start(owner, _plan(owner)["id"]).json()

    assert run["water_heaters"] == [] and len(run["prices"]) > 0


# Koniec przebiegu: północ albo koniec ostatniej pozycji planu, najpóźniej 06:00


def test_run_without_work_after_midnight_ends_at_midnight(home):
    owner = _home_with_files(home)
    plan = _plan(owner, devices=[
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))},
    ])

    run = _start(owner, plan["id"]).json()

    midnight = "2026-10-13T00:00:00+02:00"
    assert plan["horizon_end"] > midnight  # Plan liczy do 06:00, ale po północy nic z niego nie pracuje.
    assert run["horizon_end"] == midnight
    assert home.hub.clock_updates[-1] == {"running": True, "stop_at": midnight}


def test_run_ends_with_last_plan_item_after_midnight(home):
    owner = _home_with_files(home)
    plan = _plan(owner)
    ev = next(item for item in plan["items"] if item["device_id"] == "dev_ev_01")

    run = _start(owner, plan["id"]).json()

    assert ev["end"] > "2026-10-13T00:00:00+02:00"
    assert run["horizon_end"] == ev["end"] <= plan["horizon_end"]

