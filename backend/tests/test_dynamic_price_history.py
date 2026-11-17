import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.models.RcePriceObservation import RcePriceObservation
from app.providers.prices.base import PricePoint, local_day_bounds_utc
from app.repositories.dynamic_price_repository import DynamicPriceRepository
from app.schemas.dynamic_price import PriceResolution
from app.schemas.other import TariffTypeEnum
from app.services.dynamic_price_service import DynamicPriceService, DynamicTariffNotFoundError
from app.services.tariff_costs import TariffCostService
from tariff_helpers import TEST_YEARS, FlatTariffRepository, flat_definition, period


try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1 FROM rce_price_observations LIMIT 1"))
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
    session.query(RcePriceObservation).filter(RcePriceObservation.source == session.test_source).delete()
    session.commit()
    session.close()


def _day_points(source, day, price_for_slot, slots=None):
    start, _ = local_day_bounds_utc(day)
    count = 96 if slots is None else slots
    return [
        PricePoint(source, start + timedelta(minutes=15 * i), 15, day, Decimal(price_for_slot(i)))
        for i in range(count)
    ]


def _offer(margin="0", group=TariffTypeEnum.G11):
    item = flat_definition(TariffTypeEnum.DYNAMIC, energy=(margin,), distribution_group=group)
    item.name = "Oferta dynamiczna"
    return item


def _service(db, definitions=None, vat="0", profile=None):
    # Domyślnie oferta bez marży, dystrybucji i VAT: cena brutto = RCE / 1000, co upraszcza oczekiwane wartości.
    repository = FlatTariffRepository(
        [_offer()] if definitions is None else definitions, [period(vat=vat, valid=TEST_YEARS)]
    )
    users = SimpleNamespace(get_profile=lambda user_id: profile)
    return DynamicPriceService(DynamicPriceRepository(db), source=db.test_source, tariff_costs=TariffCostService(repository, users))


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


def test_prices_include_margin_distribution_fees_and_vat(db):
    _seed(db)
    offer = flat_definition(TariffTypeEnum.DYNAMIC, energy=("0.40",), network=("0.20",))
    periods = [period(quality="0.01", renewable="0.02", vat="0.23", valid=TEST_YEARS)]
    users = SimpleNamespace(get_profile=lambda user_id: None)
    service = DynamicPriceService(
        DynamicPriceRepository(db), source=db.test_source,
        tariff_costs=TariffCostService(FlatTariffRepository([offer], periods), users),
    )

    rce_only = _service(db).get_history(DAY_1, DAY_2, PriceResolution.DAY)
    full = service.get_history(DAY_1, DAY_2, PriceResolution.DAY)

    def to_consumer(price):
        return pytest.approx((price + 0.40 + 0.20 + 0.03) * 1.23, abs=1e-5)

    assert (full.operator, full.distribution_group, full.from_profile) == ("PGE", "G11", False)
    assert full.points[0].price_pln_kwh == to_consumer(rce_only.points[0].price_pln_kwh)
    assert full.average_price_pln_kwh == to_consumer(rce_only.average_price_pln_kwh)
    assert full.min_price_pln_kwh == to_consumer(rce_only.min_price_pln_kwh)
    assert full.max_price_pln_kwh == to_consumer(rce_only.max_price_pln_kwh)
    assert full.days == rce_only.days
    parts = full.price_breakdown
    assert parts.distribution == pytest.approx(0.20) and parts.fees == pytest.approx(0.03)
    assert parts.energy == pytest.approx(rce_only.average_price_pln_kwh + 0.40, abs=1e-5)
    assert parts.energy + parts.distribution + parts.fees + parts.vat == pytest.approx(full.average_price_pln_kwh, abs=1e-4)


def test_offer_follows_distribution_group_from_profile(db):
    _seed(db)
    profile = SimpleNamespace(
        base_info={
            "type_of_property": "apartment", "year_of_construction": 2000, "heating_area_m2": 60,
            "number_of_residents": 2, "town": "Wrocław", "postal_code": "50-370", "distribution_operator": "TAURON",
            "phase_type": "1_phase", "contracted_power_kw": 5, "billing_cycle": 2,
            "billing_period_start_date": "2025-01-01",
        },
        consumption_and_tariff={"tariff_type": "G12", "dynamic_price": False},
        pv_config={"mode": "none"},
    )
    g12 = _offer("0.10", TariffTypeEnum.G12)
    g12.distribution_group = TariffTypeEnum.G12

    history = _service(db, [_offer(), g12], profile=profile).get_history(DAY_1, DAY_1, PriceResolution.DAY, user_id="u")

    assert (history.operator, history.distribution_group, history.from_profile, history.note) == ("TAURON", "G12", True, None)
    assert history.average_price_pln_kwh == pytest.approx(0.2)


def test_operator_without_dynamic_offer_raises(db):
    _seed(db)

    with pytest.raises(DynamicTariffNotFoundError):
        _service(db, [flat_definition()]).get_history(DAY_1, DAY_1, PriceResolution.DAY)


def test_days_before_offer_have_no_price_and_note(db):
    _seed(db)
    offer = _offer()
    offer.valid_from = DAY_2

    history = _service(db, [offer]).get_history(DAY_1, DAY_4, PriceResolution.DAY)

    assert history.points[0].price_pln_kwh is None and history.points[0].complete is True
    assert history.points[1].price_pln_kwh == 0.3
    assert history.note == "Pełną cenę kWh tej oferty liczymy od 07.01.2025, więc wcześniejsze dni nie mają ceny na wykresie."
