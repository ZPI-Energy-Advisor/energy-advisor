import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.models.DynamicPriceObservation import DynamicPriceObservation
from app.models.Tariff import Tariff
from app.providers.prices.base import PricePoint, local_day_bounds_utc
from app.repositories.dynamic_price_repository import DynamicPriceRepository
from app.repositories.tariff_repository import TariffRepository
from app.schemas.dynamic_price import PriceResolution
from app.services.dynamic_price_service import DynamicPriceService, DynamicTariffNotFoundError


try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1 FROM dynamic_price_observations LIMIT 1"))
except Exception as exc:
    pytest.skip(f"Baza danych niedostępna: {exc}", allow_module_level=True)


DAY_1 = date(2025, 1, 6)
DAY_2 = date(2025, 1, 7)
DAY_3 = date(2025, 1, 8)
DAY_4 = date(2025, 1, 9)


@pytest.fixture
def db():
    session = SessionLocal()
    session.test_source = f"test_{uuid.uuid4().hex[:12]}"
    yield session
    session.rollback()
    session.query(DynamicPriceObservation).filter(DynamicPriceObservation.source == session.test_source).delete()
    session.commit()
    session.close()


def _day_points(source, day, price_for_slot, slots=None):
    start, _ = local_day_bounds_utc(day)
    count = 96 if slots is None else slots
    return [
        PricePoint(source, start + timedelta(minutes=15 * i), 15, day, Decimal(price_for_slot(i)))
        for i in range(count)
    ]


class _FakeTariffRepository:
    def __init__(self, tariff):
        self.tariff = tariff

    def get_first_by_type(self, tariff_type):
        return self.tariff if self.tariff and self.tariff.type == tariff_type else None


def _tariff(markup="0", vat="0"):
    return SimpleNamespace(name="Dynamiczna", type="dynamiczna", markup_pln_kwh=Decimal(markup), vat_rate=Decimal(vat))


def _service(db, tariff=None):
    # Domyślnie taryfa bez narzutu i VAT: cena w taryfie = RCE / 1000, co upraszcza oczekiwane wartości.
    tariff = tariff if tariff is not None else _tariff()
    return DynamicPriceService(DynamicPriceRepository(db), source=db.test_source, tariff_repository=_FakeTariffRepository(tariff))


def _seed(db):
    repository = DynamicPriceRepository(db)
    repository.upsert_many(_day_points(db.test_source, DAY_1, lambda i: 100))
    repository.upsert_many(_day_points(db.test_source, DAY_2, lambda i: 300, slots=48))
    repository.upsert_many(_day_points(db.test_source, DAY_4, lambda i: 200))


def test_average_uses_only_observations_in_range(db):
    _seed(db)

    only_first_day = _service(db).get_history(DAY_1, DAY_1, PriceResolution.DAY)
    first_two_days = _service(db).get_history(DAY_1, DAY_2, PriceResolution.DAY)

    assert only_first_day.average_price_pln_kwh == 0.1
    assert first_two_days.average_price_pln_kwh == pytest.approx((96 * 0.1 + 48 * 0.3) / 144, abs=1e-5)
    assert first_two_days.min_price_pln_kwh == 0.1
    assert first_two_days.max_price_pln_kwh == 0.3


def test_new_day_changes_average_without_any_migration(db):
    repository = DynamicPriceRepository(db)
    repository.upsert_many(_day_points(db.test_source, DAY_1, lambda i: 100))
    before = _service(db).get_history(DAY_1, DAY_4, PriceResolution.DAY).average_price_pln_kwh

    repository.upsert_many(_day_points(db.test_source, DAY_4, lambda i: 300))
    after = _service(db).get_history(DAY_1, DAY_4, PriceResolution.DAY).average_price_pln_kwh

    assert before == 0.1
    assert after == 0.2


def test_daily_points_mark_incomplete_and_missing_days(db):
    _seed(db)

    history = _service(db).get_history(DAY_1, DAY_4, PriceResolution.DAY)

    assert [p.price_pln_kwh for p in history.points] == [0.1, 0.3, None, 0.2]
    assert [p.complete for p in history.points] == [True, False, False, True]
    assert history.points[1].intervals == 48 and history.points[1].expected_intervals == 96
    assert history.days.total == 4
    assert history.days.complete == 2
    assert history.days.incomplete == [DAY_2]
    assert history.days.missing == [DAY_3]


def test_hourly_points_average_quarter_hours_and_cover_whole_range(db):
    repository = DynamicPriceRepository(db)
    repository.upsert_many(_day_points(db.test_source, DAY_1, lambda i: 100 * (i % 4 + 1)))

    history = _service(db).get_history(DAY_1, DAY_2, PriceResolution.HOUR)

    assert len(history.points) == 48
    assert {p.price_pln_kwh for p in history.points[:24]} == {0.25}
    assert all(p.price_pln_kwh is None and not p.complete for p in history.points[24:])
    assert history.points[0].start == datetime(2025, 1, 6, 0, 0, tzinfo=history.points[0].start.tzinfo)
    assert history.points[0].start.utcoffset() == timedelta(hours=1)


def test_quarter_hour_resolution_returns_raw_prices(db):
    repository = DynamicPriceRepository(db)
    repository.upsert_many(_day_points(db.test_source, DAY_1, lambda i: i))

    history = _service(db).get_history(DAY_1, DAY_1, PriceResolution.QUARTER_HOUR)

    assert len(history.points) == 96
    assert history.points[5].price_pln_kwh == 0.005
    assert all(p.expected_intervals == 1 for p in history.points)


def test_dst_day_has_25_hourly_points_with_repeated_hour_kept_separate(db):
    autumn_change = date(2025, 10, 26)
    repository = DynamicPriceRepository(db)
    repository.upsert_many(_day_points(db.test_source, autumn_change, lambda i: i, slots=100))

    history = _service(db).get_history(autumn_change, autumn_change, PriceResolution.HOUR)

    assert len(history.points) == 25
    repeated = [p for p in history.points if p.start.hour == 2]
    assert len(repeated) == 2
    assert {p.start.utcoffset() for p in repeated} == {timedelta(hours=2), timedelta(hours=1)}
    assert history.days.incomplete == [] and history.days.missing == []


def test_default_range_is_last_7_days_with_data(db):
    repository = DynamicPriceRepository(db)
    first_day = date(2025, 1, 1)
    for offset in range(10):
        repository.upsert_many(_day_points(db.test_source, first_day + timedelta(days=offset), lambda i: 100))

    history = _service(db).get_history(None, None, PriceResolution.DAY)

    assert history.available_from == date(2025, 1, 1)
    assert history.available_to == date(2025, 1, 10)
    assert (history.date_from, history.date_to) == (date(2025, 1, 4), date(2025, 1, 10))
    assert len(history.points) == 7
    assert history.last_updated_at is not None and history.last_updated_at.tzinfo is not None


def test_default_range_is_clipped_to_first_day_with_data(db):
    _seed(db)  # tylko 4 dni danych

    history = _service(db).get_history(None, None, PriceResolution.DAY)

    assert (history.date_from, history.date_to) == (DAY_1, DAY_4)


def test_no_data_at_all_returns_empty_history(db):
    history = _service(db).get_history(None, None, PriceResolution.HOUR)

    assert history.points == []
    assert history.average_price_pln_kwh is None
    assert history.date_from is None and history.available_to is None


def test_range_without_data_returns_gaps_not_zeros(db):
    _seed(db)

    history = _service(db).get_history(date(2024, 12, 1), date(2024, 12, 2), PriceResolution.DAY)

    assert [p.price_pln_kwh for p in history.points] == [None, None]
    assert history.average_price_pln_kwh is None
    assert history.days.missing == [date(2024, 12, 1), date(2024, 12, 2)]


def test_prices_include_tariff_markup_and_vat(db):
    _seed(db)

    rce_only = _service(db).get_history(DAY_1, DAY_2, PriceResolution.DAY)
    with_markup = _service(db, _tariff("0.40", "0.23")).get_history(DAY_1, DAY_2, PriceResolution.DAY)

    def to_consumer(price):
        return pytest.approx((price + 0.40) * 1.23, abs=1e-5)

    assert with_markup.tariff_name == "Dynamiczna"
    assert with_markup.markup_pln_kwh == 0.40 and with_markup.vat_rate == pytest.approx(0.23)
    assert with_markup.points[0].price_pln_kwh == to_consumer(rce_only.points[0].price_pln_kwh)
    assert with_markup.average_price_pln_kwh == to_consumer(rce_only.average_price_pln_kwh)
    assert with_markup.min_price_pln_kwh == to_consumer(rce_only.min_price_pln_kwh)
    assert with_markup.max_price_pln_kwh == to_consumer(rce_only.max_price_pln_kwh)
    assert with_markup.days == rce_only.days


def test_history_without_dynamic_tariff_raises(db):
    _seed(db)
    service = DynamicPriceService(DynamicPriceRepository(db), source=db.test_source, tariff_repository=_FakeTariffRepository(None))

    with pytest.raises(DynamicTariffNotFoundError):
        service.get_history(DAY_1, DAY_1, PriceResolution.DAY)


def test_tariff_repository_finds_tariff_by_type(db):
    tariff_type = f"test_{uuid.uuid4().hex[:8]}"
    first = Tariff(name="Pierwsza", type=tariff_type, markup_pln_kwh=Decimal("0.40"), vat_rate=Decimal("0.23"))
    second = Tariff(name="Druga", type=tariff_type)
    db.add_all([first, second])
    db.commit()
    try:
        found = TariffRepository(db).get_first_by_type(tariff_type)

        assert found.id == first.id
        assert found.markup_pln_kwh == Decimal("0.4000")
        assert TariffRepository(db).get_first_by_type(f"{tariff_type}_brak") is None
    finally:
        db.query(Tariff).filter(Tariff.type == tariff_type).delete()
        db.commit()
