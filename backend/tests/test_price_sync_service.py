import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.locks import LockNotAcquiredError
from app.models.PriceSyncRun import PriceSyncStatus, PriceSyncTrigger
from app.providers.prices.base import (
    PriceDataNotAvailableError,
    PricePoint,
    PriceProviderError,
    expected_intervals,
)
from app.services.price_sync_service import PriceSyncService, SyncAlreadyRunningError


NOW = datetime(2026, 10, 11, 13, 0, tzinfo=timezone.utc)  # 15:00 w Warszawie


def _points(day: date, price=Decimal("100"), count=96):
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - timedelta(hours=2)
    return [
        PricePoint("fake", start + timedelta(minutes=15 * i), 15, day, price)
        for i in range(count)
    ]


class FakeProvider:
    source = "fake"

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.requested = []

    def fetch_day(self, business_date):
        self.requested.append(business_date)
        response = self.responses.get(business_date, PriceDataNotAvailableError("brak danych"))
        if isinstance(response, Exception):
            raise response
        return response


class FakePriceRepository:
    """Odwzorowuje semantykę upsertu: klucz (source, interval_start)."""

    def __init__(self):
        self.rows = {}

    def upsert_many(self, points):
        for p in points:
            self.rows[(p.source, p.interval_start)] = p
        return len(points)

    def count_by_business_date(self, source, date_from, date_to):
        counts = {}
        for (row_source, _), p in self.rows.items():
            if row_source == source and date_from <= p.business_date <= date_to:
                counts[p.business_date] = counts.get(p.business_date, 0) + 1
        return counts


class FakeRunRepository:
    def __init__(self):
        self.runs = []

    def start(self, **kwargs):
        run = SimpleNamespace(id=len(self.runs) + 1, status=PriceSyncStatus.RUNNING, finished_at=None, **kwargs)
        self.runs.append(run)
        return run

    def finish(self, run, **kwargs):
        for key, value in kwargs.items():
            setattr(run, key, value)
        return run

    def get_latest(self, source):
        return self.runs[-1] if self.runs else None

    def get_latest_with_status(self, source, status):
        return next((r for r in reversed(self.runs) if r.status == status), None)


class FakeLock:
    def __init__(self, busy=False):
        self.busy = busy

    @contextmanager
    def acquire(self):
        if self.busy:
            raise LockNotAcquiredError("zajęte")
        yield


def _service(provider, prices=None, runs=None, lock=None):
    return PriceSyncService(
        provider=provider,
        price_repository=prices or FakePriceRepository(),
        run_repository=runs or FakeRunRepository(),
        lock=lock or FakeLock(),
        clock=lambda: NOW,
        catchup_days=2,
    )


def test_sync_range_success_saves_prices_and_records_run():
    day = date(2026, 10, 10)
    prices = FakePriceRepository()
    service = _service(FakeProvider({day: _points(day)}), prices=prices)

    run = service.sync_range(day, day, trigger=PriceSyncTrigger.MANUAL)

    assert run.status == PriceSyncStatus.SUCCESS
    assert run.records_upserted == 96
    assert run.days_synced == 1
    assert run.error_message is None
    assert run.finished_at == NOW
    assert len(prices.rows) == 96


def test_provider_error_is_logged_and_visible_in_status(caplog):
    day = date(2026, 10, 10)
    runs = FakeRunRepository()
    service = _service(FakeProvider({day: PriceProviderError("API PSE zwróciło HTTP 503")}), runs=runs)

    with caplog.at_level(logging.ERROR):
        run = service.sync_range(day, day)

    assert run.status == PriceSyncStatus.FAILED
    assert "HTTP 503" in run.error_message
    assert "HTTP 503" in caplog.text
    assert service.get_status().last_run is run
    assert service.get_status().last_successful_run is None


def test_missing_data_gives_no_data_status():
    day = date(2026, 10, 12)
    run = _service(FakeProvider()).sync_range(day, day)

    assert run.status == PriceSyncStatus.NO_DATA
    assert "2026-10-12" in run.error_message


def test_partial_status_when_only_some_days_synced():
    ok_day, failed_day = date(2026, 10, 9), date(2026, 10, 10)
    provider = FakeProvider({ok_day: _points(ok_day), failed_day: PriceProviderError("timeout")})

    run = _service(provider).sync_range(ok_day, failed_day)

    assert run.status == PriceSyncStatus.PARTIAL
    assert run.days_synced == 1
    assert "2026-10-10: timeout" in run.error_message


def test_sync_missing_fetches_only_incomplete_days_and_tomorrow():
    today = date(2026, 10, 11)
    complete_day = today - timedelta(days=1)
    prices = FakePriceRepository()
    prices.upsert_many(_points(complete_day))
    provider = FakeProvider()

    _service(provider, prices=prices).sync_missing()

    assert provider.requested == [today - timedelta(days=2), today, today + timedelta(days=1)]


def test_lock_held_raises_sync_already_running():
    runs = FakeRunRepository()
    service = _service(FakeProvider(), runs=runs, lock=FakeLock(busy=True))

    with pytest.raises(SyncAlreadyRunningError):
        service.sync_missing()
    assert runs.runs == []


def test_unexpected_error_marks_run_failed_and_reraises():
    day = date(2026, 10, 10)

    class BrokenRepository(FakePriceRepository):
        def upsert_many(self, points):
            raise RuntimeError("baza padła")

    runs = FakeRunRepository()
    service = _service(FakeProvider({day: _points(day)}), prices=BrokenRepository(), runs=runs)

    with pytest.raises(RuntimeError):
        service.sync_range(day, day)
    assert runs.runs[0].status == PriceSyncStatus.FAILED
    assert "baza padła" in runs.runs[0].error_message


def test_sync_without_range_fills_missing_days_and_with_range_refetches():
    day = date(2026, 10, 10)
    provider = FakeProvider({day: _points(day)})
    service = _service(provider)

    service.sync(trigger=PriceSyncTrigger.MANUAL)
    assert day in provider.requested

    provider.requested.clear()
    service.sync(day, day)
    assert provider.requested == [day]


def test_sync_requires_both_dates_or_none():
    with pytest.raises(ValueError):
        _service(FakeProvider()).sync(date(2026, 10, 1), None)


def test_invalid_range_is_rejected():
    with pytest.raises(ValueError):
        _service(FakeProvider()).sync_range(date(2026, 10, 2), date(2026, 10, 1))


@pytest.mark.parametrize("day, expected", [
    (date(2026, 10, 11), 96),
    (date(2026, 3, 29), 92),   # zmiana czasu na letni
    (date(2026, 10, 25), 100),  # zmiana czasu na zimowy
])
def test_expected_intervals_handles_dst(day, expected):
    assert expected_intervals(day) == expected
