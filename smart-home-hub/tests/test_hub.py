import asyncio
import json
import os
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from hub.api import create_app
from hub.clock import SIM_TIMEZONE, TICK_STEP, SimClock
from hub.config import HubSettings
from hub.models import DeviceCommand
from hub.supervisor import DeviceSupervisor, HubError, ManagedDevice
from device.models import DeviceConfig


API_KEY = "test-hub-key"
HEADERS = {"X-Hub-Api-Key": API_KEY}
FIRST_PORT = 19101
BACKEND_URL = "http://backend.test"
SAMPLE_FILE = Path(__file__).resolve().parents[2] / "frontend" / "public" / "samples" / "devices-example.json"


def _washing_machine() -> dict:
    return {
        "device_id": "dev_wm_01",
        "device_name": "Pralka Bosch",
        "device_type": "washing_machine",
        "device_category": "AGD",
        "flexibility": {"mode": "shiftable"},
        "programs": [{
            "program_id": "cotton_60",
            "program_name": "Bawełna 60°C",
            "duration_min": 120,
            "profile_kwh": [0.45, 0.45, 0.3, 0.1, 0.1, 0.15, 0.2, 0.2],
        }],
    }


def _lamp(device_id: str = "dev_lt_01", power: float = 0.06) -> dict:
    return {
        "device_id": device_id,
        "device_name": "Lampa",
        "device_type": "light",
        "device_category": "Oświetlenie",
        "max_power_kw": power,
        "flexibility": {"mode": "fixed"},
    }


@pytest.fixture
def settings(tmp_path) -> HubSettings:
    return HubSettings(
        api_key=API_KEY,
        state_dir=tmp_path,
        first_port=FIRST_PORT,
        last_port=FIRST_PORT + 29,
        health_interval_seconds=3600,
    )


class FakeBackend:
    """Backend z kontraktu webhooka: zapisuje partie zdarzeń i odpowiada 202."""

    def __init__(self):
        self.batches: list[list[dict]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.path) == ("POST", "/api/v1/home/events")
        assert request.headers["X-Hub-Api-Key"] == API_KEY
        events = json.loads(request.content)["events"]
        self.batches.append(events)
        return httpx.Response(202, json={"accepted": len(events), "duplicates": 0})

    @property
    def events(self) -> list[dict]:
        return [event for batch in self.batches for event in batch]


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def client(settings, backend):
    app = create_app(replace(settings, backend_url=BACKEND_URL), webhook_transport=httpx.MockTransport(backend.handle))
    with TestClient(app, headers=HEADERS) as test_client:
        test_client.backend = backend
        yield test_client


def _put(client: TestClient, devices: list[dict]):
    return client.put("/home/devices", json={"devices": devices})


def _pid(client: TestClient, device_id: str) -> int:
    return client.app.state.supervisor.devices[device_id].process.pid


def _device_status(client: TestClient, device_id: str) -> dict:
    devices = client.get("/home/devices").json()["devices"]
    return next(device for device in devices if device["device_id"] == device_id)


def _wait_for_state(client: TestClient, device_id: str, state: str) -> None:
    deadline = time.monotonic() + 20
    while _device_status(client, device_id)["state"] != state:
        assert time.monotonic() < deadline, f"{device_id} nie osiągnęło stanu {state}"
        time.sleep(0.1)


def test_registry_from_sample_file_starts_all_devices_on_consecutive_ports(client):
    sample = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))

    response = _put(client, sample["devices"])

    assert response.status_code == 200
    registered = response.json()["devices"]
    assert len(registered) == 24
    assert [device["port"] for device in registered] == list(range(FIRST_PORT, FIRST_PORT + 24))
    assert {device["state"] for device in registered} == {"off"}

    devices = client.get("/home/devices").json()["devices"]
    assert len(devices) == 24
    assert all(device["state"] == "off" for device in devices)


def test_second_registry_stops_removed_and_restarts_changed_only(client):
    _put(client, [_lamp("dev_a"), _lamp("dev_b"), _lamp("dev_c")])
    pids = {device_id: _pid(client, device_id) for device_id in ("dev_a", "dev_b", "dev_c")}
    removed_process = client.app.state.supervisor.devices["dev_c"].process
    port_b = client.app.state.supervisor.devices["dev_b"].port

    response = _put(client, [_lamp("dev_a"), _lamp("dev_b", power=0.08)])

    assert response.status_code == 200
    assert [device["device_id"] for device in response.json()["devices"]] == ["dev_a", "dev_b"]
    assert removed_process.poll() is not None
    assert _pid(client, "dev_a") == pids["dev_a"]
    assert _pid(client, "dev_b") != pids["dev_b"]
    assert client.app.state.supervisor.devices["dev_b"].port == port_b


def test_name_change_does_not_restart_device(client):
    _put(client, [_lamp()])
    pid = _pid(client, "dev_lt_01")
    client.post("/home/devices/dev_lt_01/commands", json={"command": "on"})

    _put(client, [{**_lamp(), "device_name": "Lampa w salonie"}])

    assert _pid(client, "dev_lt_01") == pid
    status = _device_status(client, "dev_lt_01")
    assert status["device_name"] == "Lampa w salonie"
    assert status["state"] == "running"
    port = client.app.state.supervisor.devices["dev_lt_01"].port
    assert httpx.get(f"http://127.0.0.1:{port}/config").json()["device_name"] == "Lampa w salonie"


def test_unchanged_registry_keeps_processes(client):
    _put(client, [_lamp()])
    pid = _pid(client, "dev_lt_01")

    _put(client, [_lamp()])

    assert _pid(client, "dev_lt_01") == pid


def test_removed_device_frees_its_port(client):
    _put(client, [_lamp("dev_a"), _lamp("dev_b")])

    response = _put(client, [_lamp("dev_b"), _lamp("dev_c")])

    ports = {device["device_id"]: device["port"] for device in response.json()["devices"]}
    assert ports == {"dev_b": FIRST_PORT + 1, "dev_c": FIRST_PORT}


def test_empty_registry_removes_all_devices(client):
    _put(client, [_lamp()])
    process = client.app.state.supervisor.devices["dev_lt_01"].process

    assert _put(client, []).json() == {"devices": []}

    assert process.poll() is not None
    assert client.get("/home/devices").json()["devices"] == []


def test_port_pool_exhausted_leaves_running_devices(settings):
    with TestClient(create_app(replace(settings, last_port=FIRST_PORT + 1)), headers=HEADERS) as client:
        _put(client, [_lamp("dev_a")])
        pid = _pid(client, "dev_a")

        response = _put(client, [_lamp("dev_b"), _lamp("dev_c"), _lamp("dev_d")])

        assert response.status_code == 409
        assert response.json()["code"] == "port_pool_exhausted"
        assert _pid(client, "dev_a") == pid
        assert [device["device_id"] for device in client.get("/home/devices").json()["devices"]] == ["dev_a"]


def test_killed_device_is_detected_and_returns_on_same_port(client):
    _put(client, [_lamp()])
    device = client.app.state.supervisor.devices["dev_lt_01"]
    port, old_pid = device.port, device.process.pid

    device.process.kill()
    device.process.wait()
    assert _device_status(client, "dev_lt_01")["state"] == "unreachable"
    assert _device_status(client, "dev_lt_01")["power_kw"] is None

    client.portal.call(client.app.state.supervisor.check_health)

    assert device.port == port
    assert device.process.pid != old_pid
    assert _device_status(client, "dev_lt_01")["state"] == "off"
    assert httpx.get(f"http://127.0.0.1:{port}/health").json()["device_id"] == "dev_lt_01"


def test_health_loop_restarts_device_on_its_own(settings):
    with TestClient(create_app(replace(settings, health_interval_seconds=0.1)), headers=HEADERS) as client:
        _put(client, [_lamp()])
        device = client.app.state.supervisor.devices["dev_lt_01"]
        old_pid = device.process.pid

        device.process.kill()

        deadline = time.monotonic() + 20
        while device.process is None or device.process.pid == old_pid:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        _wait_for_state(client, "dev_lt_01", "off")


def test_device_that_keeps_failing_gets_error_after_restart_limit(settings, backend):
    limited = replace(settings, max_restarts=2, device_start_timeout_seconds=0.01, backend_url=BACKEND_URL)
    app = create_app(limited, webhook_transport=httpx.MockTransport(backend.handle))
    with TestClient(app, headers=HEADERS) as client:
        client.backend = backend
        _put(client, [_lamp()])
        supervisor = client.app.state.supervisor
        device = supervisor.devices["dev_lt_01"]

        for _ in range(3):
            device.process.kill()
            device.process.wait()
            client.portal.call(supervisor.check_health)

        status = _device_status(client, "dev_lt_01")
        assert status["state"] == "error"
        assert status["energy_kwh"] is None
        assert device.process is None
        error, = _events(client, "dev_lt_01", "device_error")
        assert error["data"]["code"] == "restart_limit_exceeded"


def test_stopping_hub_stops_all_devices(settings):
    with TestClient(create_app(settings), headers=HEADERS) as client:
        _put(client, [_lamp("dev_a"), _lamp("dev_b")])
        processes = [device.process for device in client.app.state.supervisor.devices.values()]

    assert all(process.poll() is not None for process in processes)


def test_hub_restart_brings_devices_back_on_same_ports(settings):
    with TestClient(create_app(settings), headers=HEADERS) as client:
        _put(client, [_lamp("dev_a"), _washing_machine()])
        ports = {device["device_id"]: device["port"] for device in client.get("/home/devices").json()["devices"]}

    with TestClient(create_app(settings), headers=HEADERS) as client:
        devices = client.get("/home/devices").json()["devices"]

    assert {device["device_id"]: device["port"] for device in devices} == ports
    assert {device["state"] for device in devices} == {"off"}


def test_washing_machine_program_goes_through_hub_to_device(client):
    _put(client, [_washing_machine()])

    response = client.post(
        "/home/devices/dev_wm_01/commands",
        json={"command": "start_program", "program_id": "cotton_60"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["state"] == "running"
    assert body["command_id"].startswith("cmd_")
    assert _device_status(client, "dev_wm_01")["program_id"] == "cotton_60"


def test_on_and_off_commands_reach_device(client):
    _put(client, [_lamp()])

    assert client.post("/home/devices/dev_lt_01/commands", json={"command": "on"}).json()["state"] == "running"
    assert _device_status(client, "dev_lt_01")["power_kw"] == pytest.approx(0.06)
    assert client.post("/home/devices/dev_lt_01/commands", json={"command": "off"}).json()["state"] == "off"


def test_device_errors_keep_contract_code(client):
    _put(client, [_washing_machine()])
    start = {"command": "start_program", "program_id": "cotton_60"}
    client.post("/home/devices/dev_wm_01/commands", json=start)

    busy = client.post("/home/devices/dev_wm_01/commands", json=start)
    unknown = client.post("/home/devices/dev_wm_01/commands", json={**start, "program_id": "nie_ma"})

    assert (busy.status_code, busy.json()["code"]) == (409, "invalid_state")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "program_not_found")


def test_unknown_device_returns_404(client):
    response = client.post("/home/devices/dev_brak/commands", json={"command": "on"})

    assert response.status_code == 404
    assert response.json()["code"] == "device_not_found"


def test_command_to_dead_device_returns_502(client):
    _put(client, [_lamp()])
    device = client.app.state.supervisor.devices["dev_lt_01"]
    device.process.kill()
    device.process.wait()

    response = client.post("/home/devices/dev_lt_01/commands", json={"command": "on"})

    assert response.status_code == 502
    assert response.json()["code"] == "device_unreachable"


def test_registry_with_duplicate_ids_is_rejected(client):
    response = _put(client, [_lamp(), _lamp()])

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_command_without_program_id_is_rejected(client):
    _put(client, [_washing_machine()])

    response = client.post("/home/devices/dev_wm_01/commands", json={"command": "start_program"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_malformed_body_returns_400(client):
    response = client.put("/home/devices", json={"devices": "nie lista"})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"


@pytest.mark.parametrize("headers", [{}, {"X-Hub-Api-Key": "zly-klucz"}])
def test_requests_without_valid_key_are_rejected(settings, headers):
    with TestClient(create_app(settings)) as client:
        response = client.get("/home/devices", headers=headers)

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_api_key"


def test_settings_require_api_key(monkeypatch):
    monkeypatch.delenv("HUB_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="HUB_API_KEY"):
        HubSettings.from_env()


def test_devices_listen_only_on_configured_host(client, settings):
    _put(client, [_lamp()])

    config_path = settings.state_dir / "devices" / f"{FIRST_PORT}.json"
    assert json.loads(config_path.read_text(encoding="utf-8"))["bind_host"] == "127.0.0.1"
    assert os.path.exists(settings.state_dir / "state.json")


def _tick(client: TestClient, count: int = 1) -> None:
    for _ in range(count):
        client.portal.call(client.app.state.supervisor.tick)


def _set_clock(client: TestClient, sim_time: str = "2026-10-19T12:00:00+02:00") -> None:
    assert client.put("/home/clock", json={"sim_time": sim_time}).status_code == 200


def _start_program(client: TestClient, start_at: str | None = None, program_id: str = "cotton_60"):
    body = {"command": "start_program", "program_id": program_id}
    if start_at:
        body["start_at"] = start_at
    return client.post("/home/devices/dev_wm_01/commands", json=body)


def _delivered(client: TestClient) -> list[dict]:
    """Zdarzenia, które dotarły do backendu, po opróżnieniu kolejki webhooka."""
    _wait_until(lambda: not client.app.state.supervisor.publisher.pending)
    return client.backend.events


def _events(client: TestClient, device_id: str, event_type: str) -> list[dict]:
    return [
        event for event in _delivered(client)
        if event["device_id"] == device_id and event["type"] == event_type
    ]


def _wait_until(condition) -> None:
    deadline = time.monotonic() + 20
    while not condition():
        assert time.monotonic() < deadline, "warunek nie został spełniony"
        time.sleep(0.01)


def test_clock_starts_stopped_at_full_quarter_and_matches_devices_status(client):
    clock = client.get("/home/clock").json()

    assert clock["running"] is False
    assert clock["speed"] == 288
    assert clock["sim_time"].endswith(("T00:00:00+01:00", "T00:00:00+02:00"))
    assert client.get("/home/devices").json()["sim_time"] == clock["sim_time"]


def test_put_clock_changes_only_given_fields(client):
    _set_clock(client)

    response = client.put("/home/clock", json={"speed": 60})

    assert response.status_code == 200
    assert response.json() == {
        "sim_time": "2026-10-19T12:00:00+02:00", "running": False, "speed": 60,
        "simulation_id": client.app.state.supervisor.clock.simulation_id,
    }
    assert client.get("/home/clock").json() == response.json()


def test_sim_time_is_returned_in_home_timezone(client):
    _set_clock(client, "2026-10-19T10:00:00+00:00")

    assert client.get("/home/clock").json()["sim_time"] == "2026-10-19T12:00:00+02:00"


@pytest.mark.parametrize("body", [
    {"speed": 0},
    {"speed": -1},
    {"sim_time": "2026-10-19T12:00:00"},
    {"sim_time": "2026-10-19T12:05:00+02:00"},
    {"sim_time": "0001-01-01T00:00:00+01:00"},
    {"sim_time": "9999-12-31T23:45:00-01:00"},
    {"sim_time": "9999-12-31T23:45:00+00:00"},
])
def test_invalid_clock_update_is_rejected(client, body):
    before = client.get("/home/clock").json()

    response = client.put("/home/clock", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert client.get("/home/clock").json() == before


def test_sim_time_cannot_be_changed_while_clock_runs(client):
    _set_clock(client)
    client.put("/home/clock", json={"running": True, "speed": 1})

    response = client.put("/home/clock", json={"sim_time": "2026-10-20T00:00:00+02:00"})

    assert response.status_code == 409
    assert response.json()["code"] == "clock_running"
    assert client.get("/home/clock").json()["sim_time"] == "2026-10-19T12:00:00+02:00"


def test_program_with_start_at_runs_at_given_sim_time(client):
    _put(client, [_washing_machine()])
    _set_clock(client)

    response = _start_program(client, "2026-10-19T13:00:00+02:00")

    assert response.status_code == 202
    assert response.json()["status"] == "scheduled"
    assert response.json()["state"] == "off"

    _tick(client, 3)
    assert client.get("/home/clock").json()["sim_time"] == "2026-10-19T12:45:00+02:00"
    assert _device_status(client, "dev_wm_01")["state"] == "off"

    _tick(client)
    status = _device_status(client, "dev_wm_01")
    assert status["state"] == "running"
    assert status["program_started_at"] == "2026-10-19T13:00:00+02:00"
    assert status["program_ends_at"] == "2026-10-19T15:00:00+02:00"

    _tick(client, 7)
    assert _device_status(client, "dev_wm_01")["state"] == "running"

    _tick(client)
    status = _device_status(client, "dev_wm_01")
    assert status["state"] == "idle"
    assert status["energy_kwh"] == pytest.approx(1.95)
    started, = _events(client, "dev_wm_01", "device_started")
    finished, = _events(client, "dev_wm_01", "device_finished")
    assert started["sim_time"] == "2026-10-19T13:00:00+02:00"
    assert finished["sim_time"] == "2026-10-19T15:00:00+02:00"
    assert finished["data"]["energy_kwh"] == pytest.approx(1.95)


def test_start_at_equal_to_clock_starts_now(client):
    _put(client, [_washing_machine()])
    _set_clock(client)

    body = _start_program(client, "2026-10-19T12:00:00+02:00").json()

    assert (body["status"], body["state"]) == ("accepted", "running")


def test_start_at_compares_moments_not_local_hours(client):
    _put(client, [_washing_machine()])
    _set_clock(client)

    body = _start_program(client, "2026-10-19T11:00:00+00:00").json()

    assert body["status"] == "scheduled"
    _tick(client, 4)
    assert _device_status(client, "dev_wm_01")["program_started_at"] == "2026-10-19T13:00:00+02:00"


@pytest.mark.parametrize(("start_at", "program_id", "status_code", "code"), [
    ("2026-10-19T11:45:00+02:00", "cotton_60", 422, "start_at_in_past"),
    ("2026-10-19T13:05:00+02:00", "cotton_60", 422, "validation_error"),
    ("2026-10-19T13:00:00", "cotton_60", 422, "validation_error"),
    ("2026-10-19T13:00:00+02:00", "nie_ma", 404, "program_not_found"),
])
def test_invalid_start_at_is_rejected_and_nothing_is_scheduled(client, start_at, program_id, status_code, code):
    _put(client, [_washing_machine()])
    _set_clock(client)

    response = _start_program(client, start_at, program_id)

    assert (response.status_code, response.json()["code"]) == (status_code, code)
    _tick(client, 4)
    assert _device_status(client, "dev_wm_01")["state"] == "off"


def test_command_without_start_at_begins_at_current_sim_time(client):
    _put(client, [_washing_machine()])
    _set_clock(client)

    _start_program(client)
    _tick(client)

    status = _device_status(client, "dev_wm_01")
    assert status["program_started_at"] == "2026-10-19T12:00:00+02:00"
    assert status["energy_kwh"] == pytest.approx(0.45)


def test_device_added_after_clock_was_set_knows_sim_time(client):
    _set_clock(client)
    _put(client, [_lamp()])

    assert _device_status(client, "dev_lt_01")["state"] == "off"
    port = client.app.state.supervisor.devices["dev_lt_01"].port
    assert httpx.get(f"http://127.0.0.1:{port}/status").json()["sim_time"] == "2026-10-19T12:00:00+02:00"


def test_conflicting_scheduled_command_is_reported_as_device_error(client):
    _put(client, [_washing_machine()])
    _set_clock(client)
    _start_program(client)
    _start_program(client, "2026-10-19T12:15:00+02:00")

    _tick(client)

    assert _device_status(client, "dev_wm_01")["state"] == "running"
    error, = _events(client, "dev_wm_01", "device_error")
    assert error["data"]["code"] == "invalid_state"
    assert error["sim_time"] == "2026-10-19T12:15:00+02:00"


def test_removed_device_loses_scheduled_commands(client):
    _put(client, [_washing_machine(), _lamp()])
    _set_clock(client)
    _start_program(client, "2026-10-19T12:15:00+02:00")
    _put(client, [_lamp()])
    _put(client, [_lamp(), _washing_machine()])

    _tick(client)

    assert _device_status(client, "dev_wm_01")["state"] == "off"


def test_new_sim_time_starts_new_simulation_also_backwards(client):
    _put(client, [_washing_machine()])
    _set_clock(client)
    _start_program(client)
    _start_program(client, "2026-10-19T15:00:00+02:00")
    _tick(client, 2)

    _set_clock(client, "2026-10-19T08:00:00+02:00")

    status = _device_status(client, "dev_wm_01")
    assert status["state"] == "off"
    assert status["energy_kwh"] == 0
    _start_program(client)
    _tick(client, 8)
    assert _device_status(client, "dev_wm_01")["energy_kwh"] == pytest.approx(1.95)
    assert _events(client, "dev_wm_01", "device_error") == []
    _set_clock(client, "2026-10-19T15:00:00+02:00")
    _tick(client, 1)
    assert _device_status(client, "dev_wm_01")["state"] == "off"


def test_repeated_put_with_same_sim_time_keeps_simulation(client):
    _put(client, [_washing_machine()])
    _set_clock(client)
    _start_program(client)
    _start_program(client, "2026-10-19T15:00:00+02:00")

    _set_clock(client)

    assert _device_status(client, "dev_wm_01")["state"] == "running"
    assert len(client.app.state.supervisor._scheduled) == 1


@pytest.mark.parametrize("sim_time", ["2026-10-25T02:15:00+02:00", "2026-10-25T02:15:00+01:00"])
def test_repeated_put_in_repeated_dst_hour_keeps_simulation(client, sim_time):
    _put(client, [_washing_machine()])
    _set_clock(client, sim_time)
    _start_program(client)

    _set_clock(client, sim_time)

    assert _device_status(client, "dev_wm_01")["state"] == "running"


def _fail_reset_once(supervisor: DeviceSupervisor, monkeypatch) -> None:
    forward = supervisor._forward
    failures = [HubError(502, "device_unreachable", "Timeout")]

    async def flaky_forward(device, path, *args, **kwargs):
        if path == "/reset" and failures:
            raise failures.pop()
        return await forward(device, path, *args, **kwargs)

    monkeypatch.setattr(supervisor, "_forward", flaky_forward)


def test_failed_reset_keeps_clock_so_put_can_be_retried(client, monkeypatch):
    _put(client, [_washing_machine()])
    _set_clock(client)
    _start_program(client)
    _start_program(client, "2026-10-19T15:00:00+02:00")
    _fail_reset_once(client.app.state.supervisor, monkeypatch)
    body = {"sim_time": "2026-10-19T08:00:00+02:00", "running": True}

    response = client.put("/home/clock", json=body)

    assert response.status_code == 502
    assert response.json()["code"] == "device_unreachable"
    assert "dev_wm_01" in response.json()["detail"]
    clock = client.get("/home/clock").json()
    assert clock["sim_time"] == "2026-10-19T12:00:00+02:00"
    assert clock["running"] is False
    assert len(client.app.state.supervisor._scheduled) == 1

    assert client.put("/home/clock", json={"sim_time": body["sim_time"]}).status_code == 200

    assert _device_status(client, "dev_wm_01")["state"] == "off"
    assert client.app.state.supervisor._scheduled == []
    _tick(client)
    assert _events(client, "dev_wm_01", "device_error") == []


@pytest.mark.parametrize(("status_code", "content"), [
    (200, b"<html>obcy proces</html>"),
    (200, b"[]"),
    (500, b"[]"),
])
def test_unexpected_device_response_is_reported_as_unreachable(settings, status_code, content):
    async def forward() -> None:
        supervisor = DeviceSupervisor(settings)
        supervisor._client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(status_code, content=content)),
        )
        async with supervisor._client:
            await supervisor._forward(ManagedDevice(DeviceConfig.model_validate(_lamp()), FIRST_PORT), "/tick")

    with pytest.raises(HubError) as error:
        asyncio.run(forward())

    assert error.value.code == "device_unreachable"


def test_clock_loop_survives_unexpected_tick_error(client, monkeypatch):
    supervisor = client.app.state.supervisor
    tick = supervisor._tick
    failures = [RuntimeError("awaria")]

    async def flaky_tick():
        if failures:
            raise failures.pop()
        await tick()

    monkeypatch.setattr(supervisor, "_tick", flaky_tick)
    before = client.get("/home/clock").json()["sim_time"]

    client.put("/home/clock", json={"running": True, "speed": 36000})

    _wait_until(lambda: client.get("/home/clock").json()["sim_time"] != before)
    assert failures == []


def test_failed_background_loop_does_not_block_stopping_devices(settings):
    app = create_app(settings)

    async def failing_loop():
        raise RuntimeError("awaria")

    app.state.supervisor.run_health_loop = failing_loop
    with TestClient(app, headers=HEADERS) as client:
        _put(client, [_lamp()])
        process = app.state.supervisor.devices["dev_lt_01"].process

    assert process.poll() is not None


def test_dead_device_does_not_block_tick_of_others(client):
    _put(client, [_lamp("dev_a"), _lamp("dev_b")])
    _set_clock(client)
    client.post("/home/devices/dev_b/commands", json={"command": "on"})
    device = client.app.state.supervisor.devices["dev_a"]
    device.process.kill()
    device.process.wait()

    _tick(client, 4)

    assert client.get("/home/clock").json()["sim_time"] == "2026-10-19T13:00:00+02:00"
    assert _device_status(client, "dev_b")["energy_kwh"] == pytest.approx(0.06)
    errors = _events(client, "dev_a", "device_error")
    assert len(errors) == 4
    assert errors[0]["data"]["code"] == "device_unreachable"


def test_device_with_exhausted_restarts_is_skipped_by_tick(client):
    _put(client, [_lamp()])
    _set_clock(client)
    supervisor = client.app.state.supervisor
    supervisor.devices["dev_lt_01"].failed = True

    _tick(client)

    assert _events(client, "dev_lt_01", "device_error") == []


def test_restarted_device_continues_at_clock_time(client):
    _put(client, [_lamp()])
    _set_clock(client)
    _tick(client, 2)
    device = client.app.state.supervisor.devices["dev_lt_01"]
    device.process.kill()
    device.process.wait()

    client.portal.call(client.app.state.supervisor.check_health)

    response = httpx.get(f"http://127.0.0.1:{device.port}/status").json()
    assert response["sim_time"] == "2026-10-19T12:30:00+02:00"


def test_running_clock_ticks_devices_and_pause_stops_energy(client):
    _put(client, [_lamp()])
    _set_clock(client)
    client.post("/home/devices/dev_lt_01/commands", json={"command": "on"})

    client.put("/home/clock", json={"running": True, "speed": 36000})
    _wait_until(lambda: _device_status(client, "dev_lt_01")["energy_kwh"] >= 0.03)
    paused = client.put("/home/clock", json={"running": False}).json()
    energy = _device_status(client, "dev_lt_01")["energy_kwh"]

    time.sleep(0.2)

    assert client.get("/home/clock").json() == paused
    assert _device_status(client, "dev_lt_01")["energy_kwh"] == energy
    quarters = (datetime.fromisoformat(paused["sim_time"]) - datetime.fromisoformat("2026-10-19T12:00:00+02:00")) / TICK_STEP
    assert energy == pytest.approx(0.06 * quarters / 4)


def test_speed_change_keeps_scheduled_command(client):
    _put(client, [_washing_machine()])
    _set_clock(client)
    _start_program(client, "2026-10-19T14:00:00+02:00")

    client.put("/home/clock", json={"running": True, "speed": 3600})
    client.put("/home/clock", json={"speed": 36000})
    client.put("/home/clock", json={"speed": 18000})

    _wait_until(lambda: _device_status(client, "dev_wm_01")["state"] != "off")
    client.put("/home/clock", json={"running": False})
    assert _device_status(client, "dev_wm_01")["program_started_at"] == "2026-10-19T14:00:00+02:00"


def test_stopping_hub_with_running_clock_shuts_down_cleanly(settings):
    with TestClient(create_app(settings), headers=HEADERS) as client:
        _put(client, [_lamp()])
        client.put("/home/clock", json={"running": True, "speed": 36000})
        process = client.app.state.supervisor.devices["dev_lt_01"].process

    assert process.poll() is not None


@pytest.mark.parametrize(("midnight", "next_day", "quarters"), [
    ("2026-03-29T00:00:00+01:00", "2026-03-30", 92),
    ("2026-10-25T00:00:00+02:00", "2026-10-26", 100),
    ("2026-10-19T00:00:00+02:00", "2026-10-20", 96),
])
def test_day_has_correct_length_at_time_change(midnight, next_day, quarters):
    clock = SimClock()
    clock.set_time(datetime.fromisoformat(midnight))

    steps = 0
    while clock.sim_time.date().isoformat() != next_day:
        clock.advance()
        steps += 1

    assert steps == quarters
    assert clock.sim_time.isoformat().startswith(f"{next_day}T00:00:00+")


def test_device_energy_follows_day_with_extra_hour(client):
    _put(client, [_lamp()])
    _set_clock(client, "2026-10-25T00:00:00+02:00")
    client.post("/home/devices/dev_lt_01/commands", json={"command": "on"})

    _tick(client, 100)

    assert client.get("/home/clock").json()["sim_time"] == "2026-10-26T00:00:00+01:00"
    assert _device_status(client, "dev_lt_01")["energy_kwh"] == pytest.approx(0.06 * 25)
    assert client.app.state.supervisor.clock.sim_time.tzinfo is SIM_TIMEZONE


def test_step_progress_survives_pause():
    async def scenario() -> None:
        clock = SimClock()
        clock.configure(running=True, speed=TICK_STEP / timedelta(seconds=0.4))
        waiting = asyncio.create_task(clock.wait_for_step())
        await asyncio.sleep(0.3)
        clock.configure(running=False, speed=None)
        await asyncio.sleep(0.2)
        assert not waiting.done()

        clock.configure(running=True, speed=None)
        await asyncio.wait_for(waiting, 0.3)

    asyncio.run(scenario())


def test_tick_time_counts_towards_next_step():
    async def scenario() -> None:
        clock = SimClock()
        clock.configure(running=True, speed=TICK_STEP / timedelta(seconds=0.4))
        clock.spend(0.3)

        await asyncio.wait_for(clock.wait_for_step(), 0.25)

    asyncio.run(scenario())


def test_exhausted_step_waits_for_resume_when_paused():
    async def scenario() -> None:
        clock = SimClock()
        clock.spend(3600)
        waiting = asyncio.create_task(clock.wait_for_step())
        await asyncio.sleep(0.05)
        assert not waiting.done()

        clock.configure(running=True, speed=None)
        await asyncio.wait_for(waiting, 1)

    asyncio.run(scenario())


def test_command_sent_during_tick_waits_for_it_and_starts_at_new_time(settings):
    supervisor = DeviceSupervisor(settings)
    supervisor.devices["dev_wm_01"] = ManagedDevice(DeviceConfig(**_washing_machine()), port=FIRST_PORT)
    calls = []

    async def scenario():
        tick_started, release_tick = asyncio.Event(), asyncio.Event()

        async def forward(device, path, method="POST", payload=None):
            calls.append((path, supervisor.clock.sim_time))
            if path == "/tick":
                tick_started.set()
                await release_tick.wait()
            return {"state": "running"}

        supervisor._forward = forward
        before = supervisor.clock.sim_time
        tick = asyncio.create_task(supervisor.tick())
        await tick_started.wait()
        command = asyncio.create_task(
            supervisor.send_command("dev_wm_01", DeviceCommand(command="start_program", program_id="cotton_60"))
        )
        await asyncio.sleep(0.05)

        # Komenda czeka na koniec ticka, zamiast trafić do urządzenia, które dostało już czas kolejnego kwadransa.
        assert [path for path, _ in calls] == ["/tick"]
        release_tick.set()
        await tick
        result = await command

        assert result["status"] == "accepted"
        assert calls[1] == ("/programs/cotton_60/start", before + TICK_STEP)

    asyncio.run(scenario())


# Webhook zdarzeń do backendu


def _energy_reports(client: TestClient, device_id: str) -> list[dict]:
    return _events(client, device_id, "energy_report")


def test_energy_reports_sum_to_device_energy(client):
    _put(client, [_washing_machine(), _lamp()])
    _set_clock(client)
    _start_program(client)
    client.post("/home/devices/dev_lt_01/commands", json={"command": "on"})

    _tick(client, 10)

    washer_reports = _energy_reports(client, "dev_wm_01")
    finished, = _events(client, "dev_wm_01", "device_finished")
    assert len(washer_reports) == 8
    assert sum(report["data"]["energy_kwh"] for report in washer_reports) == pytest.approx(finished["data"]["energy_kwh"])
    assert sum(report["data"]["energy_kwh"] for report in washer_reports) == pytest.approx(
        _device_status(client, "dev_wm_01")["energy_kwh"]
    )
    lamp_reports = _energy_reports(client, "dev_lt_01")
    assert len(lamp_reports) == 10
    assert sum(report["data"]["energy_kwh"] for report in lamp_reports) == pytest.approx(
        _device_status(client, "dev_lt_01")["energy_kwh"]
    )


def test_energy_report_covers_one_quarter_of_device_time(client):
    _put(client, [_lamp()])
    _set_clock(client)
    client.post("/home/devices/dev_lt_01/commands", json={"command": "on"})

    _tick(client, 2)

    first, second = _energy_reports(client, "dev_lt_01")
    assert first["data"] == {"interval_start": "2026-10-19T12:00:00+02:00", "energy_kwh": pytest.approx(0.015)}
    assert first["sim_time"] == "2026-10-19T12:15:00+02:00"
    assert second["data"]["interval_start"] == first["sim_time"]


def test_idle_device_sends_no_energy_reports(client):
    _put(client, [_lamp()])
    _set_clock(client)

    _tick(client, 3)

    assert _delivered(client) == []


def test_tick_sends_events_of_all_devices_in_one_batch(client):
    _put(client, [_lamp("dev_a"), _lamp("dev_b")])
    _set_clock(client)
    client.post("/home/devices/dev_a/commands", json={"command": "on"})
    client.post("/home/devices/dev_b/commands", json={"command": "on"})
    _tick(client)
    batches_before = len(client.backend.batches)

    _tick(client)

    _delivered(client)
    last, = client.backend.batches[batches_before:]
    assert sorted(event["device_id"] for event in last) == ["dev_a", "dev_b"]
    assert {event["type"] for event in last} == {"energy_report"}


def test_device_started_carries_command_id(client):
    _put(client, [_washing_machine(), _lamp()])
    _set_clock(client)
    now = _start_program(client).json()["command_id"]
    later = client.post("/home/devices/dev_wm_01/commands", json={
        "command": "start_program", "program_id": "cotton_60", "start_at": "2026-10-19T15:00:00+02:00",
    }).json()["command_id"]
    lamp = client.post("/home/devices/dev_lt_01/commands", json={"command": "on"}).json()["command_id"]

    _tick(client, 13)

    first, second = _events(client, "dev_wm_01", "device_started")
    assert first["data"] == {"program_id": "cotton_60", "command_id": now}
    assert second["data"] == {"program_id": "cotton_60", "command_id": later}
    assert second["sim_time"] == "2026-10-19T15:00:00+02:00"
    started_lamp, = _events(client, "dev_lt_01", "device_started")
    assert started_lamp["data"] == {"program_id": None, "command_id": lamp}


def test_events_have_unique_ids_and_simulation_of_their_run(client):
    _put(client, [_lamp()])
    _set_clock(client)
    first_run = client.get("/home/clock").json()["simulation_id"]
    client.post("/home/devices/dev_lt_01/commands", json={"command": "on"})
    _tick(client, 2)

    _set_clock(client, "2026-10-19T08:00:00+02:00")
    second_run = client.get("/home/clock").json()["simulation_id"]
    client.post("/home/devices/dev_lt_01/commands", json={"command": "on"})
    _tick(client, 2)

    events = _delivered(client)
    assert second_run != first_run
    assert len({event["event_id"] for event in events}) == len(events)
    assert [event["simulation_id"] for event in _energy_reports(client, "dev_lt_01")] == [first_run] * 2 + [second_run] * 2


def test_same_sim_time_keeps_simulation(client):
    _set_clock(client)
    simulation_id = client.get("/home/clock").json()["simulation_id"]

    _set_clock(client)

    assert client.get("/home/clock").json()["simulation_id"] == simulation_id


def test_stopping_hub_sends_waiting_events(settings, backend):
    unavailable = {"down": True}

    def handle(request: httpx.Request) -> httpx.Response:
        if unavailable["down"]:
            return httpx.Response(503, json={"detail": "Chwilowo niedostępny"})
        return backend.handle(request)

    # Długa przerwa przed ponowieniem: zdarzenia może dowieźć tylko wysyłka przy zamykaniu.
    slow_retry = replace(settings, backend_url=BACKEND_URL, webhook_retry_min_seconds=3600)
    app = create_app(slow_retry, webhook_transport=httpx.MockTransport(handle))
    with TestClient(app, headers=HEADERS) as client:
        _put(client, [_lamp()])
        _set_clock(client)
        client.post("/home/devices/dev_lt_01/commands", json={"command": "on"})
        _tick(client)
        assert client.app.state.supervisor.publisher.pending
        unavailable["down"] = False

    assert [event["type"] for event in backend.events] == ["device_started", "energy_report"]
