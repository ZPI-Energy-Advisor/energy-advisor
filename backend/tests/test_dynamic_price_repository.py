import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.models.DynamicPriceObservation import DynamicPriceObservation
from app.providers.prices.base import PricePoint
from app.repositories.dynamic_price_repository import DynamicPriceRepository


try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1 FROM dynamic_price_observations LIMIT 1"))
except Exception as exc:  # brak bazy lub niewykonane migracje
    pytest.skip(f"Baza danych niedostępna: {exc}", allow_module_level=True)


DAY = date(2025, 1, 1)


@pytest.fixture
def db():
    session = SessionLocal()
    session.test_source = f"test_{uuid.uuid4().hex[:12]}"
    yield session
    session.rollback()
    session.query(DynamicPriceObservation).filter(DynamicPriceObservation.source == session.test_source).delete()
    session.commit()
    session.close()


def _points(source, price, count=4):
    start = datetime(2024, 12, 31, 23, 0, tzinfo=timezone.utc)
    return [PricePoint(source, start + timedelta(minutes=15 * i), 15, DAY, Decimal(price)) for i in range(count)]


def test_reimport_same_period_updates_instead_of_duplicating(db):
    repository = DynamicPriceRepository(db)

    repository.upsert_many(_points(db.test_source, "100.5"))
    repository.upsert_many(_points(db.test_source, "-12.25"))

    rows = repository.get_for_business_date(db.test_source, DAY)
    assert len(rows) == 4
    assert {row.price_pln_mwh for row in rows} == {Decimal("-12.25")}
    assert repository.count_by_business_date(db.test_source, DAY, DAY) == {DAY: 4}


def test_interval_start_is_stored_with_timezone(db):
    repository = DynamicPriceRepository(db)
    repository.upsert_many(_points(db.test_source, "1", count=1))

    stored = repository.get_prices_between(
        db.test_source,
        datetime(2024, 12, 31, 22, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    (interval_start,) = stored
    assert interval_start.utcoffset() == timedelta(0)
    assert interval_start == datetime(2024, 12, 31, 23, 0, tzinfo=timezone.utc)
