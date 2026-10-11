from contextlib import contextmanager
from datetime import date

from sqlalchemy.exc import OperationalError, ProgrammingError

from app.workers import price_sync_worker


class _FakeEngine:
    def __init__(self, errors):
        self.errors = list(errors)
        self.attempts = 0

    @contextmanager
    def connect(self):
        self.attempts += 1
        if self.errors:
            raise self.errors.pop(0)
        yield self

    def execute(self, statement):
        return None


def test_wait_for_database_retries_until_db_and_tables_are_ready(monkeypatch):
    engine = _FakeEngine([
        OperationalError("SELECT 1", {}, Exception("connection refused")),
        ProgrammingError("SELECT 1", {}, Exception("relation does not exist")),
    ])
    monkeypatch.setattr(price_sync_worker, "engine", engine)
    sleeps = []

    assert price_sync_worker.wait_for_database(timeout_seconds=60, interval_seconds=5, sleep=sleeps.append) is True
    assert engine.attempts == 3
    assert sleeps == [5, 5]


def test_wait_for_database_gives_up_after_timeout(monkeypatch):
    engine = _FakeEngine([OperationalError("SELECT 1", {}, Exception("connection refused"))] * 100)
    monkeypatch.setattr(price_sync_worker, "engine", engine)

    assert price_sync_worker.wait_for_database(timeout_seconds=0, sleep=lambda _: None) is False


def test_split_into_chunks_covers_range_without_gaps_or_overlaps():
    chunks = price_sync_worker.split_into_chunks(date(2025, 1, 1), date(2025, 3, 5), 31)

    assert chunks == [
        (date(2025, 1, 1), date(2025, 1, 31)),
        (date(2025, 2, 1), date(2025, 3, 3)),
        (date(2025, 3, 4), date(2025, 3, 5)),
    ]


def test_split_into_chunks_single_day():
    assert price_sync_worker.split_into_chunks(date(2025, 1, 1), date(2025, 1, 1), 31) == [
        (date(2025, 1, 1), date(2025, 1, 1)),
    ]
