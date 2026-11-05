import json
import os
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from hub.api import create_app
from hub.config import HubSettings


API_KEY = "test-hub-key"
HEADERS = {"X-Hub-Api-Key": API_KEY}
FIRST_PORT = 19101
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


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), headers=HEADERS) as test_client:
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


def test_device_that_keeps_failing_gets_error_after_restart_limit(settings):
    limited = replace(settings, max_restarts=2, device_start_timeout_seconds=0.01)
    with TestClient(create_app(limited), headers=HEADERS) as client:
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


def test_start_at_is_rejected_instead_of_starting_now(client):
    _put(client, [_washing_machine()])

    response = client.post("/home/devices/dev_wm_01/commands", json={
        "command": "start_program",
        "program_id": "cotton_60",
        "start_at": "2026-10-19T13:00:00+02:00",
    })

    assert response.status_code == 422
    assert response.json()["code"] == "start_at_not_supported"
    assert _device_status(client, "dev_wm_01")["state"] == "off"


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
