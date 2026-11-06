import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from device.api import create_app
from device.driver import DeviceDriver
from device.models import DeviceConfig


HUB_DIR = Path(__file__).resolve().parents[1]
WASHING_MACHINE = {
    "device_id": "dev_wm_01",
    "device_name": "Pralka Bosch",
    "device_type": "washing_machine",
    "device_category": "AGD",
    "flexibility": {"mode": "shiftable", "allowed_window": {"from": "07:00", "to": "22:00"}},
    "programs": [{
        "program_id": "cotton_60",
        "program_name": "Bawełna 60°C",
        "duration_min": 120,
        "profile_kwh": [0.45, 0.45, 0.3, 0.1, 0.1, 0.15, 0.2, 0.2],
    }],
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(DeviceDriver(DeviceConfig.model_validate(WASHING_MACHINE))))


def _tick(client: TestClient, sim_time: str):
    return client.post("/tick", json={"sim_time": sim_time})


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "device_id": "dev_wm_01"}


def test_get_config_returns_device_object_with_file_names(client):
    assert client.get("/config").json() == WASHING_MACHINE


def test_program_flow_through_http(client):
    _tick(client, "2026-10-19T13:00:00+02:00")

    started = client.post("/programs/cotton_60/start")
    assert started.status_code == 200
    assert started.json()["state"] == "running"

    finished = _tick(client, "2026-10-19T15:00:00+02:00").json()
    assert finished["state"] == "idle"
    assert finished["energy_kwh"] == pytest.approx(1.95)
    assert [event["type"] for event in finished["events"]] == ["device_started", "device_finished"]

    energy = client.get("/energy").json()
    assert energy["total_kwh"] == pytest.approx(1.95)
    assert energy["last_action"]["ended_at"] == "2026-10-19T15:00:00+02:00"


def test_on_and_off_return_status(client):
    assert client.post("/on").json()["state"] == "idle"
    assert client.post("/off").json()["state"] == "off"


def test_device_errors_use_contract_format(client):
    response = client.post("/programs/nie_ma/start")

    assert response.status_code == 404
    assert response.json()["code"] == "program_not_found"
    assert response.json()["detail"]


def test_second_program_returns_409(client):
    client.post("/programs/cotton_60/start")

    response = client.post("/programs/cotton_60/start")

    assert response.status_code == 409
    assert response.json()["code"] == "invalid_state"


def test_stale_tick_returns_409(client):
    _tick(client, "2026-10-19T13:00:00+02:00")

    response = _tick(client, "2026-10-19T12:45:00+02:00")

    assert response.status_code == 409
    assert response.json()["code"] == "stale_tick"


def test_tick_without_timezone_returns_422(client):
    response = _tick(client, "2026-10-19T13:00:00")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize("body", [{}, {"sim_time": "wczoraj"}])
def test_malformed_tick_returns_400(client, body):
    response = client.post("/tick", json=body)

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"


def test_put_config_changes_name(client):
    response = client.put("/config", json={"device_name": "Pralka w łazience"})

    assert response.status_code == 200
    assert response.json()["device_name"] == "Pralka w łazience"
    assert client.get("/config").json()["device_name"] == "Pralka w łazience"


def test_put_config_rejects_other_fields(client):
    response = client.put("/config", json={"max_power_kw": 3.0})

    assert response.status_code == 409
    assert response.json()["code"] == "config_requires_restart"


def test_process_starts_from_config_file(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    config_path = tmp_path / "device.json"
    config_path.write_text(
        json.dumps({**WASHING_MACHINE, "port": port, "bind_host": "127.0.0.1"}, ensure_ascii=False),
        encoding="utf-8",
    )
    process = subprocess.Popen([sys.executable, "-m", "device", "--config", str(config_path)], cwd=HUB_DIR)
    try:
        assert _wait_for_health(port) == {"status": "ok", "device_id": "dev_wm_01"}
    finally:
        process.terminate()
        process.wait(timeout=10)


def _wait_for_health(port: int) -> dict:
    deadline = time.monotonic() + 15
    while True:
        try:
            return httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).json()
        except httpx.TransportError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)


def test_reset_returns_device_to_initial_state(client):
    _tick(client, "2026-10-19T13:00:00+02:00")
    client.post("/programs/cotton_60/start")
    _tick(client, "2026-10-19T13:15:00+02:00")

    response = client.post("/reset")

    assert response.status_code == 200
    assert response.json()["state"] == "off"
    assert response.json()["energy_kwh"] == 0
    assert response.json()["sim_time"] is None
    assert client.get("/energy").json()["last_action"] is None
    assert _tick(client, "2026-10-19T08:00:00+02:00").status_code == 200
    assert _tick(client, "2026-10-19T08:15:00+02:00").json()["events"] == []
