from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.v1.deps import (
    get_authenticated_user,
    get_dynamic_price_repository,
    get_price_sync_admin_key,
    get_price_sync_service,
)
from app.services.price_sync_service import PriceSyncStatusSummary, SyncAlreadyRunningError
from main import app


ADMIN_KEY = "test-admin-key"


def _run(status="success", **overrides):
    values = dict(
        id=1, source="pse_rce", trigger="manual", status=status,
        date_from=date(2026, 10, 10), date_to=date(2026, 10, 12),
        days_requested=3, days_synced=3, records_upserted=288, error_message=None,
        started_at=datetime(2026, 10, 11, 13, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 10, 11, 13, 0, 5, tzinfo=timezone.utc),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class StubSyncService:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def sync(self, date_from, date_to, trigger):
        self.calls.append((date_from, date_to, trigger))
        if self.error:
            raise self.error
        return _run()

    def get_status(self):
        failed = _run(id=2, status="failed", error_message="Błędy dostawcy: 2026-10-12: HTTP 503")
        return PriceSyncStatusSummary(source="pse_rce", last_run=failed, last_successful_run=_run())


@pytest.fixture
def stub():
    service = StubSyncService()
    app.dependency_overrides[get_price_sync_service] = lambda: service
    app.dependency_overrides[get_price_sync_admin_key] = lambda: ADMIN_KEY
    app.dependency_overrides[get_authenticated_user] = lambda: SimpleNamespace(id="user")
    yield service
    app.dependency_overrides.clear()


client = TestClient(app)


def test_manual_sync_requires_admin_key(stub):
    assert client.post("/api/v1/dynamic-prices/sync").status_code == 401
    assert client.post("/api/v1/dynamic-prices/sync", headers={"X-Admin-Key": "wrong-key"}).status_code == 401
    assert stub.calls == []


def test_manual_sync_disabled_without_configured_key(stub):
    app.dependency_overrides[get_price_sync_admin_key] = lambda: None

    response = client.post("/api/v1/dynamic-prices/sync", headers={"X-Admin-Key": ADMIN_KEY})

    assert response.status_code == 503


def test_manual_sync_without_range_runs_worker_job(stub):
    response = client.post("/api/v1/dynamic-prices/sync", headers={"X-Admin-Key": ADMIN_KEY})

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert stub.calls == [(None, None, "manual")]


def test_manual_sync_with_range(stub):
    response = client.post(
        "/api/v1/dynamic-prices/sync",
        headers={"X-Admin-Key": ADMIN_KEY},
        json={"date_from": "2026-10-01", "date_to": "2026-10-05"},
    )

    assert response.status_code == 200
    assert stub.calls == [(date(2026, 10, 1), date(2026, 10, 5), "manual")]


@pytest.mark.parametrize("payload", [
    {"date_from": "2026-10-05", "date_to": "2026-10-01"},
    {"date_from": "2026-10-05"},
    {"date_from": "2026-01-01", "date_to": "2026-03-01"},  # > 31 dni
])
def test_manual_sync_rejects_invalid_range(stub, payload):
    response = client.post("/api/v1/dynamic-prices/sync", headers={"X-Admin-Key": ADMIN_KEY}, json=payload)

    assert response.status_code == 422
    assert stub.calls == []


def test_manual_sync_conflict_when_already_running(stub):
    stub.error = SyncAlreadyRunningError("Synchronizacja cen jest już w toku")

    response = client.post("/api/v1/dynamic-prices/sync", headers={"X-Admin-Key": ADMIN_KEY})

    assert response.status_code == 409


def test_sync_status_shows_last_error(stub):
    response = client.get("/api/v1/dynamic-prices/sync/status")

    assert response.status_code == 200
    body = response.json()
    assert body["last_run"]["status"] == "failed"
    assert "HTTP 503" in body["last_run"]["error_message"]
    assert body["last_successful_run"]["status"] == "success"


class _FakeDynamicPriceRepository:
    def get_for_business_date(self, source, business_date):
        start = datetime(2025, 1, 14, 23, 0, tzinfo=timezone.utc)
        return [
            SimpleNamespace(interval_start=start, interval_minutes=15, price_pln_mwh=Decimal("461.2300")),
            SimpleNamespace(interval_start=start, interval_minutes=15, price_pln_mwh=Decimal("-34.7800")),
        ]


def test_get_day_prices_returns_mwh_and_kwh(stub):
    app.dependency_overrides[get_dynamic_price_repository] = lambda: _FakeDynamicPriceRepository()

    response = client.get("/api/v1/dynamic-prices", params={"business_date": "2025-01-15"})

    assert response.status_code == 200
    body = response.json()
    assert body["business_date"] == "2025-01-15"
    assert body["timezone"] == "UTC"
    assert [p["price_pln_kwh"] for p in body["prices"]] == ["0.46123", "-0.03478"]


def test_get_day_prices_requires_business_date(stub):
    assert client.get("/api/v1/dynamic-prices").status_code == 422


def test_sync_status_requires_authentication():
    app.dependency_overrides.clear()
    assert client.get("/api/v1/dynamic-prices/sync/status").status_code == 401
