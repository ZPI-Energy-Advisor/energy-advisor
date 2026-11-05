import importlib
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from app.clients.hub_client import (
    API_KEY_HEADER,
    REGISTRY_TIMEOUT_SECONDS,
    HubAuthError,
    HubClient,
    HubError,
    HubUnavailableError,
)
from app import config
from app.core import smart_home_factory
from app.schemas.smart_home import CommandType, DeviceCommand, DeviceState, HubDevice


HUB_URL = "http://hub.test"
API_KEY = "test-hub-key"
WARSAW = timezone(timedelta(hours=2))


def _client(handler) -> HubClient:
    def authorized(request: httpx.Request):
        # Zachowanie prawdziwego huba: bez poprawnego klucza zawsze 401.
        if request.headers.get(API_KEY_HEADER) != API_KEY:
            return httpx.Response(401, json={"detail": "Błędny klucz", "code": "invalid_api_key"})
        return handler(request)

    return HubClient(httpx.Client(
        base_url=HUB_URL,
        transport=httpx.MockTransport(authorized),
        headers={API_KEY_HEADER: API_KEY},
    ))


def _washing_machine() -> HubDevice:
    return HubDevice.model_validate({
        "device_id": "dev_wm_01",
        "device_name": "Pralka Bosch",
        "device_type": "washing_machine",
        "device_category": "AGD",
        "max_power_kw": 2.2,
        "flexibility": {"mode": "shiftable", "allowed_window": {"from": "07:00", "to": "22:00"}},
        "programs": [{
            "program_id": "cotton_60",
            "program_name": "Bawełna 60°C",
            "duration_min": 30,
            "profile_kwh": [0.55, 0.5],
        }],
    })


def test_put_devices_sends_registry_and_returns_ports():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(200, json={"devices": [{"device_id": "dev_wm_01", "port": 9101, "state": "off"}]})

    registered = _client(handler).put_devices([_washing_machine()])

    request = requests[0]
    assert request.method == "PUT"
    assert request.url == f"{HUB_URL}/home/devices"
    body = json.loads(request.content)
    device = body["devices"][0]
    assert device["device_id"] == "dev_wm_01"
    # Okno ma w JSON nazwę "from" jak w pliku urządzeń, nie pythonowe "from_".
    assert device["flexibility"]["allowed_window"] == {"from": "07:00", "to": "22:00"}
    assert device["programs"][0]["profile_kwh"] == [0.55, 0.5]
    assert registered[0].port == 9101
    assert registered[0].state == DeviceState.OFF


def test_put_devices_waits_longer_than_other_requests():
    timeouts = {}

    def handler(request: httpx.Request):
        timeouts[request.method] = request.extensions["timeout"]["read"]
        return httpx.Response(200, json={"devices": [], "sim_time": None})

    client = HubClient(httpx.Client(
        base_url=HUB_URL,
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    ))
    client.put_devices([])
    client.get_devices()

    assert timeouts == {"PUT": REGISTRY_TIMEOUT_SECONDS, "GET": 5.0}


def test_get_devices_parses_status():
    def handler(request: httpx.Request):
        assert request.method == "GET"
        return httpx.Response(200, json={
            "sim_time": "2026-10-19T09:45:00+02:00",
            "devices": [{
                "device_id": "dev_wm_01",
                "device_name": "Pralka Bosch",
                "port": 9101,
                "state": "running",
                "program_id": "cotton_60",
                "program_started_at": "2026-10-19T09:30:00+02:00",
                "program_ends_at": "2026-10-19T10:00:00+02:00",
                "power_kw": 2.0,
                "energy_kwh": 0.55,
                "future_field": "ignorowane",
            }],
        })

    status = _client(handler).get_devices()

    assert status.sim_time == datetime(2026, 10, 19, 9, 45, tzinfo=WARSAW)
    device = status.devices[0]
    assert device.state == DeviceState.RUNNING
    assert device.program_id == "cotton_60"
    assert device.energy_kwh == 0.55


def test_get_devices_accepts_unreachable_device_without_readings():
    def handler(request: httpx.Request):
        return httpx.Response(200, json={
            "sim_time": None,
            "devices": [{
                "device_id": "dev_wm_01",
                "device_name": "Pralka Bosch",
                "port": 9101,
                "state": "unreachable",
                "power_kw": None,
                "energy_kwh": None,
            }],
        })

    status = _client(handler).get_devices()

    assert status.sim_time is None
    assert status.devices[0].state == DeviceState.UNREACHABLE
    assert status.devices[0].power_kw is None


def test_send_command_posts_start_program():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(202, json={
            "command_id": "cmd_1", "device_id": "dev_wm_01", "status": "scheduled", "state": "idle",
        })

    command = DeviceCommand(
        command=CommandType.START_PROGRAM,
        program_id="cotton_60",
        start_at=datetime(2026, 10, 19, 13, 0, tzinfo=WARSAW),
    )
    result = _client(handler).send_command("dev_wm_01", command)

    assert requests[0].url == f"{HUB_URL}/home/devices/dev_wm_01/commands"
    assert json.loads(requests[0].content) == {
        "command": "start_program",
        "program_id": "cotton_60",
        "start_at": "2026-10-19T13:00:00+02:00",
    }
    assert result.status == "scheduled"


def test_send_command_escapes_device_id():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(202, json={"command_id": "c", "device_id": "d", "status": "accepted", "state": "idle"})

    _client(handler).send_command("dev/../x", DeviceCommand(command=CommandType.ON))

    assert requests[0].url.raw_path == b"/home/devices/dev%2F..%2Fx/commands"


def test_on_command_sends_only_command():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(202, json={"command_id": "c", "device_id": "d", "status": "accepted", "state": "idle"})

    _client(handler).send_command("dev_tv_01", DeviceCommand(command=CommandType.ON))

    assert json.loads(requests[0].content) == {"command": "on"}


def test_update_clock_sends_only_given_fields():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(200, json={"sim_time": "2026-10-19T09:45:00+02:00", "running": False, "speed": 60})

    clock = _client(handler).update_clock(running=False)

    assert json.loads(requests[0].content) == {"running": False}
    assert clock.running is False
    assert clock.speed == 60


def test_timeout_raises_retryable_unavailable_error():
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(HubUnavailableError) as exc_info:
        _client(handler).get_devices()
    assert exc_info.value.retryable is True


def test_command_timeout_is_not_retryable():
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(HubUnavailableError) as exc_info:
        _client(handler).send_command("dev_wm_01", DeviceCommand(command=CommandType.START_PROGRAM, program_id="eco"))
    assert exc_info.value.retryable is False


def test_connection_error_raises_unavailable_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(HubUnavailableError):
        _client(handler).get_devices()


def test_wrong_api_key_raises_auth_error():
    client = HubClient(httpx.Client(
        base_url=HUB_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"detail": "Błędny klucz", "code": "invalid_api_key"})
            if request.headers.get(API_KEY_HEADER) != API_KEY else httpx.Response(200, json={"devices": []})
        ),
        headers={API_KEY_HEADER: "wrong-key"},
    ))

    with pytest.raises(HubAuthError) as exc_info:
        client.get_devices()
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "invalid_api_key"
    assert exc_info.value.retryable is False


def test_build_hub_client_returns_none_without_hub_url(monkeypatch):
    monkeypatch.setattr(smart_home_factory, "HUB_URL", None)

    assert smart_home_factory.build_hub_client() is None


def test_build_hub_client_requires_api_key(monkeypatch):
    monkeypatch.setattr(smart_home_factory, "HUB_URL", HUB_URL)
    monkeypatch.setattr(smart_home_factory, "HUB_API_KEY", None)

    with pytest.raises(RuntimeError, match="HUB_API_KEY"):
        smart_home_factory.build_hub_client()


def test_create_sets_api_key_and_timeout():
    client = HubClient.create(f"{HUB_URL}/", API_KEY, timeout=2.5)
    try:
        assert client.client.headers[API_KEY_HEADER] == API_KEY
        assert client.client.timeout.read == 2.5
        assert str(client.client.base_url) == f"{HUB_URL}"
    finally:
        client.close()


@pytest.mark.parametrize("status_code, code", [(404, "device_not_found"), (409, "invalid_state")])
def test_client_errors_keep_hub_error_code(status_code, code):
    client = _client(lambda request: httpx.Response(status_code, json={"detail": "x", "code": code}))

    with pytest.raises(HubError) as exc_info:
        client.send_command("dev_x", DeviceCommand(command=CommandType.OFF))
    assert not isinstance(exc_info.value, HubUnavailableError)
    assert exc_info.value.status_code == status_code
    assert exc_info.value.code == code
    assert exc_info.value.retryable is False


@pytest.mark.parametrize("status_code", [500, 502, 503])
def test_server_errors_are_retryable(status_code):
    client = _client(lambda request: httpx.Response(status_code, json={"detail": "x", "code": "device_unreachable"}))

    with pytest.raises(HubUnavailableError) as exc_info:
        client.get_devices()
    assert exc_info.value.status_code == status_code
    assert exc_info.value.retryable is True


def test_command_server_error_is_not_retryable():
    client = _client(lambda request: httpx.Response(502, json={"detail": "x", "code": "device_unreachable"}))

    with pytest.raises(HubUnavailableError) as exc_info:
        client.send_command("dev_wm_01", DeviceCommand(command=CommandType.ON))
    assert exc_info.value.retryable is False


def test_empty_hub_timeout_uses_default(monkeypatch):
    monkeypatch.setenv("HUB_TIMEOUT_SECONDS", "")
    try:
        assert importlib.reload(config).HUB_TIMEOUT_SECONDS == 5.0
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_response_breaking_contract_raises_hub_error():
    client = _client(lambda request: httpx.Response(200, json={"devices": [{"device_id": "dev_wm_01"}]}))

    with pytest.raises(HubError, match="niezgodna z kontraktem"):
        client.get_devices()


def test_invalid_json_raises_hub_error():
    client = _client(lambda request: httpx.Response(200, text="<html>"))

    with pytest.raises(HubError, match="niepoprawny JSON"):
        client.get_devices()


@pytest.mark.parametrize("data", [
    {"command": "start_program"},
    {"command": "on", "program_id": "cotton_60"},
    {"command": "start_program", "program_id": "cotton_60", "start_at": "2026-10-19T13:00:00"},
])
def test_device_command_validation(data):
    with pytest.raises(ValidationError):
        DeviceCommand.model_validate(data)
