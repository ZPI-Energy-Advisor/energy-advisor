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
    UNCONFIRMED_COMMAND_MESSAGE,
    HomeControlService,
)
from app.services.home_service import AUTH_MESSAGE, DISABLED_MESSAGE, NOT_CONNECTED_MESSAGE
from main import app
from test_energy_files import _create_user, _flat_tariff_repository, _headers, client
from test_home import LAMP, WASHER, _devices_file, _reset_home, _upload, db  # noqa: F401 (db: fixture)
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
            return httpx.Response(200, json={**CLOCK, **body})
        assert method == "POST" and path.endswith("/commands"), (method, path)
        device_id = path.split("/")[3]
        self.commands.append((device_id, json.loads(request.content)))
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
    assert response.json() == {"sim_time": CLOCK["sim_time"], "running": True, "speed": 1440.0}
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

    assert home.hub.clock_updates == [{"sim_time": midnight}]


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
