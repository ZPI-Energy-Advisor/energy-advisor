"""ZP-97: sterowanie domem z ekranu „Mój dom” – komendy urządzeń, zegar symulacji i opis urządzeń w stanie."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.api.v1.deps import (
    get_calculation_service,
    get_home_owner_email,
    get_hub_client,
    get_schedule_price_service,
)
from app.clients.hub_client import API_KEY_HEADER, HubClient
from app.models.HomeConnection import HomeConnection
from app.services.calculation_service import CalculationService
from app.repositories.home_repository import HomeRepository
from app.schemas.smart_home import CommandType, DeviceCommand
from app.services.home_control_service import (
    CLOCK_RESET_FAILED_MESSAGE,
    DEVICE_UNREACHABLE_MESSAGE,
    HUB_UNAVAILABLE_MESSAGE,
    INVALID_RESPONSE_MESSAGE,
    REPLAY_FAILED_MESSAGE,
    UNCONFIRMED_COMMAND_MESSAGE,
    HomeControlService,
)
from app.services.home_service import AUTH_MESSAGE, DISABLED_MESSAGE, NOT_CONNECTED_MESSAGE
from main import app
from test_energy_files import _create_user, _flat_tariff_repository, _headers, client
from test_home import HEAT_PUMP, LAMP, WASHER, _devices_file, _reset_home, _upload, db  # noqa: F401 (db: fixture)
from test_home_events import FlatPrices, _device


HUB_URL = "http://hub.test"
API_KEY = "test-hub-key"
CLOCK = {"sim_time": "2026-10-19T12:00:00+02:00", "running": False, "speed": 288.0, "simulation_id": "sim_ctl"}


class FakeHub:
    """Hub z kontraktu: zapisuje komendy i zmiany zegara; `reply` podmienia odpowiedź, `down` symuluje awarię."""

    def __init__(self):
        self.commands: list[tuple[str, dict]] = []
        self.clock_updates: list[dict] = []
        self.devices: list[dict] = []
        self.reply: httpx.Response | None = None
        self.down = False
        self.timeout = False
        # Odpowiedzi tylko dla komend urządzeń (device_id -> odpowiedź) i kolejność zmian w hubie.
        self.command_replies: dict[str, httpx.Response] = {}
        self.commands_down = False
        self.log: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get(API_KEY_HEADER) != API_KEY:
            return httpx.Response(401, json={"detail": "Błędny klucz", "code": "invalid_api_key"})
        if self.down:
            raise httpx.ConnectError("Connection refused", request=request)
        path, method = request.url.path, request.method
        if self.timeout and method != "GET":
            raise httpx.ReadTimeout("timed out", request=request)
        if (method, path) == ("PUT", "/home/devices"):
            devices = json.loads(request.content)["devices"]
            return httpx.Response(200, json={"devices": [
                {"device_id": device["device_id"], "port": 9101, "state": "off"} for device in devices
            ]})
        if (method, path) == ("GET", "/home/devices"):
            return httpx.Response(200, json={"sim_time": CLOCK["sim_time"], "devices": self.devices})
        if (method, path) == ("GET", "/home/clock"):
            return httpx.Response(200, json=CLOCK)
        if self.reply is not None:
            return self.reply
        if (method, path) == ("PUT", "/home/clock"):
            body = json.loads(request.content)
            self.clock_updates.append(body)
            self.log.append(f"clock {sorted(body)}")
            return httpx.Response(200, json={**CLOCK, **body})
        assert method == "POST" and path.endswith("/commands"), (method, path)
        device_id = path.split("/")[3]
        if self.commands_down:
            return _hub_error(503, "internal_error", "Hub przeciążony")
        if device_id in self.command_replies:
            return self.command_replies[device_id]
        body = json.loads(request.content)
        self.commands.append((device_id, body))
        self.log.append(f"{body['command']} {device_id}")
        return httpx.Response(202, json={
            "command_id": "cmd_1", "device_id": device_id, "status": "accepted", "state": "running",
        })


@pytest.fixture
def home(db):  # noqa: F811
    """Podłączony dom właściciela, drugi użytkownik i FakeHub."""
    owner, other = _create_user(db), _create_user(db)
    _reset_home(db)
    db.execute(update(HomeConnection).values(user_id=owner.id, connected_at=datetime.now(timezone.utc)))
    db.commit()
    hub = FakeHub()
    hub_client = HubClient(httpx.Client(
        base_url=HUB_URL, transport=httpx.MockTransport(hub.handle), headers={API_KEY_HEADER: API_KEY},
    ))
    overrides = {
        get_hub_client: lambda: hub_client,
        get_home_owner_email: lambda: owner.email,
        get_calculation_service: lambda: CalculationService(_flat_tariff_repository()),
        get_schedule_price_service: FlatPrices,
    }
    app.dependency_overrides.update(overrides)
    yield SimpleNamespace(owner=owner, other=other, hub=hub, client=hub_client)
    for dependency in overrides:
        app.dependency_overrides.pop(dependency, None)
    _reset_home(db)
    hub_client.close()


def _command(user, device_id: str, body: dict):
    return client.post(f"/api/v1/home/devices/{device_id}/commands", json=body, headers=_headers(user))


def _clock(user, body: dict):
    return client.put("/api/v1/home/clock", json=body, headers=_headers(user))


def _hub_error(status_code: int, code: str, detail: str) -> httpx.Response:
    return httpx.Response(status_code, json={"detail": detail, "code": code})


# Dostęp


def test_other_user_cannot_control_owner_home(home):
    assert _command(home.other, "dev_lamp_01", {"command": "on"}).status_code == 403
    assert _clock(home.other, {"running": True}).status_code == 403
    assert home.hub.commands == [] and home.hub.clock_updates == []


def test_disconnected_home_cannot_be_controlled(home, db):  # noqa: F811
    _reset_home(db)

    for response in (_command(home.owner, "dev_lamp_01", {"command": "on"}), _clock(home.owner, {"running": True})):
        assert response.status_code == 409
        assert response.json()["detail"] == NOT_CONNECTED_MESSAGE
    assert home.hub.commands == [] and home.hub.clock_updates == []


def test_control_is_unavailable_without_hub(home):
    app.dependency_overrides[get_hub_client] = lambda: None

    assert _command(home.owner, "dev_lamp_01", {"command": "on"}).status_code == 503
    assert _clock(home.owner, {"running": True}).status_code == 503


def test_service_without_hub_refuses_before_touching_home(home, db):  # noqa: F811
    service = HomeControlService(HomeRepository(db), hub_client=None)

    with pytest.raises(HTTPException) as error:
        service.send_command(home.owner, "dev_lamp_01", DeviceCommand(command=CommandType.ON))

    assert (error.value.status_code, error.value.detail) == (503, DISABLED_MESSAGE)


# Komendy urządzeń


@pytest.mark.parametrize("body", [
    {"command": "on"},
    {"command": "off"},
    {"command": "start_program", "program_id": "cotton_60"},
])
def test_command_is_forwarded_to_hub(home, body):
    response = _command(home.owner, "dev_wm_01", body)

    assert response.status_code == 202
    assert response.json() == {"command_id": "cmd_1", "device_id": "dev_wm_01", "status": "accepted", "state": "running"}
    assert home.hub.commands == [("dev_wm_01", body)]


def test_invalid_command_is_rejected_before_hub(home):
    response = _command(home.owner, "dev_wm_01", {"command": "start_program"})

    assert response.status_code == 422
    assert home.hub.commands == []


@pytest.mark.parametrize(("status_code", "code", "detail"), [
    (409, "invalid_state", "Trwa program urządzenia"),
    (404, "device_not_found", "Nie ma urządzenia 'dev_x' w rejestrze"),
    (404, "program_not_found", "Urządzenie nie ma programu 'eco'"),
])
def test_command_rejected_by_hub_keeps_its_status_and_description(home, status_code, code, detail):
    home.hub.reply = _hub_error(status_code, code, detail)

    response = _command(home.owner, "dev_wm_01", {"command": "on"})

    assert (response.status_code, response.json()["detail"]) == (status_code, detail)


def test_unreachable_device_is_reported(home):
    home.hub.reply = _hub_error(502, "device_unreachable", "Brak odpowiedzi urządzenia: timeout")

    response = _command(home.owner, "dev_wm_01", {"command": "on"})

    assert (response.status_code, response.json()["detail"]) == (502, DEVICE_UNREACHABLE_MESSAGE)


def test_unavailable_hub_is_reported(home):
    home.hub.down = True

    response = _command(home.owner, "dev_wm_01", {"command": "on"})

    assert (response.status_code, response.json()["detail"]) == (503, HUB_UNAVAILABLE_MESSAGE)


def test_unanswered_command_is_not_reported_as_safe_to_retry(home):
    # Hub mógł wykonać komendę przed timeoutem, więc odpowiedź nie może zachęcać do ponowienia.
    home.hub.timeout = True

    response = _command(home.owner, "dev_wm_01", {"command": "start_program", "program_id": "cotton_60"})

    assert (response.status_code, response.json()["detail"]) == (504, UNCONFIRMED_COMMAND_MESSAGE)


def test_unanswered_clock_update_can_be_retried(home):
    # PUT zegara jest idempotentny, więc brak odpowiedzi to zwykła niedostępność huba.
    home.hub.timeout = True

    response = _clock(home.owner, {"day": "2026-10-19"})

    assert (response.status_code, response.json()["detail"]) == (503, HUB_UNAVAILABLE_MESSAGE)


def test_hub_error_outside_contract_is_not_shown_as_user_error(home):
    home.hub.reply = httpx.Response(404, json={"detail": "Not Found"})  # Np. starszy hub bez tej trasy.

    response = _command(home.owner, "dev_wm_01", {"command": "on"})

    assert (response.status_code, response.json()["detail"]) == (502, INVALID_RESPONSE_MESSAGE)


def test_rejected_api_key_is_reported_as_configuration_error(home):
    home.client.client.headers[API_KEY_HEADER] = "zly-klucz"

    response = _command(home.owner, "dev_wm_01", {"command": "on"})

    assert (response.status_code, response.json()["detail"]) == (502, AUTH_MESSAGE)


# Zegar symulacji


def test_start_and_speed_are_forwarded_to_hub(home):
    response = _clock(home.owner, {"running": True, "speed": 1440})

    assert response.status_code == 200
    assert response.json() == {"sim_time": CLOCK["sim_time"], "running": True, "speed": 1440.0, "replay": None}
    assert home.hub.clock_updates == [{"running": True, "speed": 1440.0}]


def test_pause_is_forwarded_to_hub(home):
    _clock(home.owner, {"running": False})

    assert home.hub.clock_updates == [{"running": False}]


@pytest.mark.parametrize(("day", "midnight"), [
    ("2026-10-19", "2026-10-19T00:00:00+02:00"),
    ("2026-10-25", "2026-10-25T00:00:00+02:00"),  # Doba zmiany czasu na zimowy zaczyna się jeszcze w czasie letnim.
    ("2026-12-01", "2026-12-01T00:00:00+01:00"),
])
def test_day_sets_sim_time_to_midnight_in_home_timezone(home, day, midnight):
    assert _clock(home.owner, {"day": day}).status_code == 200

    assert home.hub.clock_updates == [{"sim_time": midnight, "restart": True}]


@pytest.mark.parametrize("body", [{}, {"speed": 0}, {"speed": -288}, {"day": "19.10.2026"}])
def test_invalid_clock_update_is_rejected_before_hub(home, body):
    assert _clock(home.owner, body).status_code == 422
    assert home.hub.clock_updates == []


def test_setting_day_while_clock_runs_is_rejected_by_hub(home):
    home.hub.reply = _hub_error(409, "clock_running", "Czas można ustawić tylko przy zatrzymanym zegarze")

    response = _clock(home.owner, {"day": "2026-10-19"})

    assert (response.status_code, response.json()["detail"]) == (409, "Czas można ustawić tylko przy zatrzymanym zegarze")


def test_failed_device_reset_asks_to_set_day_again(home):
    home.hub.reply = _hub_error(502, "device_unreachable", "Urządzenia bez resetu: dev_wm_01")

    response = _clock(home.owner, {"day": "2026-10-19"})

    assert (response.status_code, response.json()["detail"]) == (502, CLOCK_RESET_FAILED_MESSAGE)


# Opis urządzeń w stanie domu


def test_state_describes_devices_with_registry_data(home):
    assert _upload(home.owner, _devices_file(WASHER, LAMP)).status_code == 200
    home.hub.devices = [
        _device("dev_lamp_01", state="running", power_kw=0.1, name="Lampa"),
        _device("dev_wm_01", state="idle", power_kw=0.0, name="Pralka Bosch"),
        _device("dev_unknown", state="off", power_kw=0.0),  # Hub z zaległym rejestrem.
    ]

    devices = {device["device_id"]: device for device in client.get(
        "/api/v1/home/state", headers=_headers(home.owner),
    ).json()["devices"]}

    lamp, washer, unknown = devices["dev_lamp_01"], devices["dev_wm_01"], devices["dev_unknown"]
    assert (lamp["device_type"], lamp["device_category"], lamp["flexibility_mode"]) == ("other", "Inne", "fixed")
    assert lamp["programs"] == []
    assert (washer["device_category"], washer["flexibility_mode"]) == ("AGD", "shiftable")
    assert washer["programs"] == [
        {"program_id": "cotton_60", "program_name": "Bawełna 60°C", "duration_min": 45},
        {"program_id": "quick_30", "program_name": "Szybkie 30°C", "duration_min": 30},
    ]
    assert (unknown["device_category"], unknown["flexibility_mode"], unknown["programs"]) == (None, None, [])


# Odtworzenie doby z historii (ZP-96)


def _file(period: dict, devices: list[dict], actions: list[dict]) -> bytes:
    return json.dumps({"period": period, "devices": devices, "energy_usage": actions}).encode()


def _runs(hub: FakeHub) -> list[tuple[str, dict]]:
    return [(device_id, body) for device_id, body in hub.commands if body["command"] == "run_profile"]


def test_setting_day_replays_fixed_actions_from_history(home):
    assert _upload(home.owner, _devices_file(WASHER, LAMP, HEAT_PUMP)).status_code == 200

    response = _clock(home.owner, {"day": "2026-10-05"})

    assert response.status_code == 200
    assert response.json()["replay"] == {"actions": 1, "devices": 1, "skipped_devices": [], "rejected_actions": 0}
    (device_id, run), = _runs(home.hub)  # Pralka i pompa ciepła są przesuwalne: nimi steruje optymalizacja.
    assert device_id == "dev_lamp_01"
    assert (run["ref"], run["start_at"]) == ("act_lamp_1", "2026-10-05T18:00:00+02:00")
    assert len(run["profile_kwh"]) == 4
    assert sum(run["profile_kwh"]) == pytest.approx(0.08)  # Energia akcji z pliku.


def test_replay_is_planned_after_new_day_and_before_clock_starts(home):
    _upload(home.owner, _devices_file(LAMP))

    _clock(home.owner, {"day": "2026-10-05", "running": True, "speed": 1440})

    assert home.hub.log == ["clock ['restart', 'sim_time']", "run_profile dev_lamp_01", "clock ['running', 'speed']"]


def test_replayed_day_has_energy_of_file_for_fixed_devices(home):
    # Akcje na granicy dób: lampa 23:00-1:00, lodówka przez całą dobę i PV w dzień.
    period = {"start": "2026-10-05T00:00:00+02:00", "end": "2026-10-07T00:00:00+02:00"}
    devices = [
        {**LAMP["device"]},
        {"device_id": "dev_fr_01", "device_name": "Lodówka", "device_type": "fridge", "device_category": "AGD",
         "max_power_kw": 0.15, "flexibility": {"mode": "fixed"}},
        {"device_id": "dev_pv_01", "device_name": "PV", "device_type": "pv_inverter", "device_category": "OZE",
         "max_power_kw": 5.0, "flexibility": {"mode": "fixed"}},
    ]
    actions = [
        {"action_id": "act_1", "device_id": "dev_lamp_01", "action_start": "2026-10-05T23:00:00+02:00",
         "action_end": "2026-10-06T01:00:00+02:00", "energy_kwh": 0.16},
        {"action_id": "act_2", "device_id": "dev_fr_01", "action_start": "2026-10-06T00:00:00+02:00",
         "action_end": "2026-10-07T00:00:00+02:00", "energy_kwh": 0.95},
        {"action_id": "act_3", "device_id": "dev_pv_01", "action_start": "2026-10-06T10:00:00+02:00",
         "action_end": "2026-10-06T14:00:00+02:00", "energy_kwh": -6.4},
    ]
    assert _upload(home.owner, _file(period, devices, actions)).status_code == 200

    replay = _clock(home.owner, {"day": "2026-10-06"}).json()["replay"]

    runs = {device_id: run for device_id, run in _runs(home.hub)}
    assert replay == {"actions": 3, "devices": 3, "skipped_devices": [], "rejected_actions": 0}
    # Lampa z poprzedniej doby: od północy, z drugą połową energii.
    assert runs["dev_lamp_01"]["start_at"] == "2026-10-06T00:00:00+02:00"
    assert sum(runs["dev_lamp_01"]["profile_kwh"]) == pytest.approx(0.08)
    assert (len(runs["dev_fr_01"]["profile_kwh"]), sum(runs["dev_fr_01"]["profile_kwh"])) == (96, pytest.approx(0.95))
    assert sum(runs["dev_pv_01"]["profile_kwh"]) == pytest.approx(-6.4)
    assert all(kwh < 0 for kwh in runs["dev_pv_01"]["profile_kwh"])


def test_day_without_history_replays_nothing(home):
    _upload(home.owner, _devices_file(LAMP))

    response = _clock(home.owner, {"day": "2026-11-01"})

    assert response.json()["replay"] == {"actions": 0, "devices": 0, "skipped_devices": [], "rejected_actions": 0}
    assert _runs(home.hub) == []


def test_clock_change_without_day_does_not_replay(home):
    _upload(home.owner, _devices_file(LAMP))

    response = _clock(home.owner, {"running": True})

    assert response.json()["replay"] is None
    assert _runs(home.hub) == []


def test_device_unknown_to_hub_is_skipped_and_rest_is_replayed(home):
    _upload(home.owner, _devices_file(LAMP))
    other = {"device": {**LAMP["device"], "device_id": "dev_lamp_02"},
             "actions": [{**LAMP["actions"][0], "action_id": "act_lamp_2", "device_id": "dev_lamp_02"}]}
    _upload(home.owner, _devices_file(other), name="druga.json")
    home.hub.command_replies["dev_lamp_02"] = _hub_error(404, "device_not_found", "Nie ma urządzenia")

    replay = _clock(home.owner, {"day": "2026-10-05"}).json()["replay"]

    assert replay == {"actions": 1, "devices": 1, "skipped_devices": ["dev_lamp_02"], "rejected_actions": 0}
    assert [device_id for device_id, _ in _runs(home.hub)] == ["dev_lamp_01"]


def test_action_rejected_for_other_reason_is_counted_but_device_is_not_skipped(home):
    _upload(home.owner, _devices_file(LAMP))
    home.hub.command_replies["dev_lamp_01"] = _hub_error(409, "invalid_state", "Trwa program urządzenia")

    replay = _clock(home.owner, {"day": "2026-10-05"}).json()["replay"]

    # Hub zna urządzenie, więc ponowne podłączenie domu nic by nie dało.
    assert replay == {"actions": 0, "devices": 0, "skipped_devices": [], "rejected_actions": 1}


def test_setting_same_day_again_restarts_simulation_before_replay(home):
    # Hub bez `restart` nie resetuje przy tym samym sim_time, więc druga doba zdublowałaby akcje w kolejce.
    _upload(home.owner, _devices_file(LAMP))

    _clock(home.owner, {"day": "2026-10-05"})
    _clock(home.owner, {"day": "2026-10-05"})

    midnight = {"sim_time": "2026-10-05T00:00:00+02:00", "restart": True}
    assert home.hub.clock_updates == [midnight, midnight]


def test_hub_failure_during_replay_asks_to_set_day_again(home):
    _upload(home.owner, _devices_file(LAMP))
    home.hub.commands_down = True

    response = _clock(home.owner, {"day": "2026-10-05", "running": True})

    assert (response.status_code, response.json()["detail"]) == (502, REPLAY_FAILED_MESSAGE)
    assert home.hub.clock_updates == [{"sim_time": "2026-10-05T00:00:00+02:00", "restart": True}]  # Zegar nie ruszył.


def test_state_shows_replayed_action(home):
    run = {"ref": "act_lamp_1", "started_at": "2026-10-05T18:00:00+02:00", "ends_at": "2026-10-05T19:00:00+02:00"}
    home.hub.devices = [{**_device("dev_lamp_01", state="running", power_kw=0.08), "run": run}]

    device, = client.get("/api/v1/home/state", headers=_headers(home.owner)).json()["devices"]

    assert device["run"] == run


@pytest.mark.parametrize("body", [
    {"command": "run_profile"},
    {"command": "run_profile", "profile_kwh": []},
    {"command": "run_profile", "profile_kwh": [0.1], "program_id": "eco"},
    {"command": "on", "profile_kwh": [0.1]},
    {"command": "off", "start_at": "2026-10-05T18:00:00+02:00"},
])
def test_invalid_run_profile_command_is_rejected_before_hub(home, body):
    assert _command(home.owner, "dev_lamp_01", body).status_code == 422
    assert home.hub.commands == []
