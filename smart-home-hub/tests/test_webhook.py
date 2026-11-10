"""Kolejka i wysyłka zdarzeń huba do backendu (POST /api/v1/home/events)."""
import asyncio
import json

import httpx
import pytest

from hub.config import HubSettings
from hub.webhook import EventPublisher


API_KEY = "test-hub-key"
SIMULATION_ID = "sim_test"


def _settings(tmp_path, **overrides) -> HubSettings:
    values = {
        "api_key": API_KEY,
        "state_dir": tmp_path,
        "backend_url": "http://backend.test",
        "webhook_retry_min_seconds": 0.001,
        "webhook_retry_max_seconds": 0.002,
    } | overrides
    return HubSettings(**values)


def _report(index: int) -> dict:
    return {
        "type": "energy_report",
        "device_id": "dev_lt_01",
        "sim_time": f"2026-10-19T12:{index % 4 * 15:02d}:00+02:00",
        "data": {"interval_start": "2026-10-19T12:00:00+02:00", "energy_kwh": 0.015},
    }


class Backend:
    """Odpowiada kolejnymi statusami z `responses`; potem 202. Zapisuje każdą odebraną partię."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.batches: list[list[dict]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url == "http://backend.test/api/v1/home/events"
        assert request.headers["X-Hub-Api-Key"] == API_KEY
        self.batches.append(json.loads(request.content)["events"])
        response = self.responses.pop(0) if self.responses else 202
        if isinstance(response, Exception):
            raise response
        return httpx.Response(response, json={"detail": "test"})


async def _deliver(publisher: EventPublisher) -> None:
    """Uruchamia pętlę wysyłki do opróżnienia kolejki."""
    task = asyncio.create_task(publisher.run())
    try:
        for _ in range(1000):
            if not publisher.pending:
                return
            await asyncio.sleep(0.001)
        raise AssertionError("kolejka nie została opróżniona")
    finally:
        task.cancel()
        await publisher.close()


def _run(tmp_path, backend: Backend, events: list[dict], **settings) -> EventPublisher:
    publisher = EventPublisher(_settings(tmp_path, **settings), httpx.MockTransport(backend.handle))
    publisher.publish(SIMULATION_ID, events)
    asyncio.run(_deliver(publisher))
    return publisher


def test_published_event_gets_id_and_simulation(tmp_path):
    backend = Backend()

    _run(tmp_path, backend, [_report(0)])

    event, = backend.batches[0]
    assert event["event_id"].startswith("evt_")
    assert event["simulation_id"] == SIMULATION_ID
    assert {key: event[key] for key in _report(0)} == _report(0)


@pytest.mark.parametrize("failure", [
    500, 503, 429, httpx.ConnectError("Connection refused"), httpx.ReadTimeout("timeout"),
])
def test_failed_batch_is_retried_with_same_event_ids(tmp_path, failure):
    backend = Backend(failure, failure)

    _run(tmp_path, backend, [_report(0), _report(1)])

    assert len(backend.batches) == 3
    assert backend.batches[0] == backend.batches[1] == backend.batches[2]


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_api_key_is_not_retried(tmp_path, status, caplog):
    backend = Backend(status)

    publisher = _run(tmp_path, backend, [_report(0)])

    assert len(backend.batches) == 1
    assert publisher.pending == []
    assert "HUB_API_KEY" in caplog.text


def test_invalid_batch_is_dropped_and_next_one_is_sent(tmp_path):
    backend = Backend(422)

    _run(tmp_path, backend, [_report(index) for index in range(3)], webhook_batch_size=2)

    assert [len(batch) for batch in backend.batches] == [2, 1]


def test_events_go_in_batches_in_order(tmp_path):
    backend = Backend()
    events = [_report(index) for index in range(5)]

    _run(tmp_path, backend, events, webhook_batch_size=2)

    assert [len(batch) for batch in backend.batches] == [2, 2, 1]
    sent = [event for batch in backend.batches for event in batch]
    assert [event["sim_time"] for event in sent] == [event["sim_time"] for event in events]


def test_full_queue_drops_oldest_events(tmp_path):
    publisher = EventPublisher(_settings(tmp_path, event_buffer_size=3))

    publisher.publish(SIMULATION_ID, [_report(index) for index in range(5)])

    assert [event["sim_time"] for event in publisher.pending] == [_report(index)["sim_time"] for index in (2, 3, 4)]
    assert publisher.dropped == 2


def test_acknowledged_batch_does_not_remove_events_published_during_send(tmp_path):
    """Pełna kolejka odrzuca początek partii w trakcie wysyłki; potwierdzenie nie może zabrać nowych zdarzeń."""
    settings = _settings(tmp_path, event_buffer_size=2, webhook_batch_size=2)
    publisher: EventPublisher

    def handle(request: httpx.Request) -> httpx.Response:
        publisher.publish(SIMULATION_ID, [_report(2)])
        return httpx.Response(202, json={"accepted": 2})

    publisher = EventPublisher(settings, httpx.MockTransport(handle))
    publisher.publish(SIMULATION_ID, [_report(0), _report(1)])

    async def send_once():
        await publisher._send_batch()
        await publisher.close()

    asyncio.run(send_once())

    assert [event["sim_time"] for event in publisher.pending] == [_report(2)["sim_time"]]


def test_publisher_without_backend_url_keeps_nothing(tmp_path):
    publisher = EventPublisher(_settings(tmp_path, backend_url=None))

    publisher.publish(SIMULATION_ID, [_report(0)])

    assert not publisher.enabled
    assert publisher.pending == []


def test_flush_stops_at_first_failure(tmp_path):
    backend = Backend(503)
    publisher = EventPublisher(_settings(tmp_path, webhook_batch_size=1), httpx.MockTransport(backend.handle))
    publisher.publish(SIMULATION_ID, [_report(0), _report(1)])

    async def flush():
        await publisher.flush()
        await publisher.close()

    asyncio.run(flush())

    assert len(backend.batches) == 1
    assert len(publisher.pending) == 2


def test_backend_url_comes_from_env(monkeypatch):
    monkeypatch.setenv("HUB_API_KEY", API_KEY)
    monkeypatch.setenv("BACKEND_URL", "http://backend:8000/")

    assert HubSettings.from_env().backend_url == "http://backend:8000"

    monkeypatch.setenv("BACKEND_URL", "")
    assert HubSettings.from_env().backend_url is None
