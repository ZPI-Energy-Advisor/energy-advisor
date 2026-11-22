import random
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.schemas.calculation import CalculationDetails, TariffData
from app.schemas.other import DistributionOperatorEnum, PhaseTypeEnum, TariffTypeEnum as T
from app.services.pv_service import DynamicMarketPriceResolver
from app.services.quarter_prices import (
    FeeParameters,
    MissingTariffRates,
    QuarterPriceService,
    quarter_prices,
)
from app.services.tariff_engine import BillingContext, ZonedTariffCalculationStrategy, money
from timing import TIME_LIMIT_SCALE
from tariff_helpers import HOURS, definition, period

WARSAW = ZoneInfo("Europe/Warsaw")
SLOT = timedelta(minutes=15)
JANUARY = (date(2026, 1, 1), date(2026, 1, 31))
FROM_FEBRUARY = (date(2026, 2, 1), date(2026, 12, 31))
PERIOD = period(quality="0.0313", renewable="0.0073", cogeneration="0.003", excise="0.005",
                capacity=("2.50", "6.00", "10.00"))
FEES = FeeParameters(phase_type=PhaseTypeEnum.SINGLE_PHASE, billing_cycle_months=1, annual_kwh=Decimal("3000"))


def _utc(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WARSAW).astimezone(timezone.utc)


def _local_naive(slot_utc: datetime) -> datetime:
    return slot_utc.astimezone(WARSAW).replace(tzinfo=None)


def _market(slot_utc: datetime) -> float:
    local = slot_utc.astimezone(WARSAW)
    return ((local.hour * 7 + local.minute) % 50 - 10) / 100


def _readings(first: date, days: int, seed: int = 7) -> list[tuple[datetime, float]]:
    rng = random.Random(seed)
    start = datetime.combine(first, datetime.min.time())
    return [(start + index * SLOT, round(rng.uniform(0, 0.6), 3)) for index in range(days * 96)]


def _engine_bill(definitions, readings, *, market=None, cycles=((date(2026, 1, 1)), date(2026, 2, 1))):
    engine = ZonedTariffCalculationStrategy()
    if market is not None:
        engine.set_dynamic_price_resolver(lambda timestamp: market(timestamp.replace(tzinfo=WARSAW).astimezone(timezone.utc)))
    used_cycles = [
        (datetime.combine(start, datetime.min.time()),
         [(moment, value) for moment, value in readings if (moment.year, moment.month) == (start.year, start.month)])
        for start in cycles
    ]
    details = CalculationDetails(
        used_energy_cycles=used_cycles,
        tariff_data=TariffData(
            tariff_type=definitions[0].tariff_code,
            billing_cycle=1,
            billing_period_start_date=cycles[0],
            distribution_operator=DistributionOperatorEnum.PGE,
            phase_type="1_phase",
            contracted_power_kw=10,
        ),
    )
    context = BillingContext(
        regulatory_periods=[PERIOD], annual_kwh=FEES.annual_kwh, first_day=cycles[0],
        last_day=date(2026, 2, 28), raw_cycles=used_cycles,
    )
    return engine.calculate(details, definitions, context)


def _bill_from_quarters(prices, readings, month: int) -> Decimal:
    energy = sum(
        (Decimal(str(value)) * prices.prices[_utc(moment.date(), moment.hour, moment.minute)].gross
         for moment, value in readings if moment.month == month),
        Decimal("0"),
    )
    fees = sum(
        (item.fees.gross for item in prices.monthly_fees if item.valid_from.month <= month <= item.valid_to.month),
        Decimal("0"),
    )
    return energy + fees


def test_zone_tariff_price_of_each_quarter_with_components():
    g12 = definition(T.G12, ["0.60", "0.40"], ["0.40", "0.05"])

    result = quarter_prices([g12], [PERIOD], _utc(date(2026, 3, 4), 0), _utc(date(2026, 3, 5), 0))

    day = result.prices[_utc(date(2026, 3, 4), 10)]
    night = result.prices[_utc(date(2026, 3, 4), 23, 45)]
    assert len(result.prices) == 96 and result.missing == ()
    assert (day.zone, day.energy, day.network) == (1, Decimal("0.60"), Decimal("0.40"))
    assert (night.zone, night.energy, night.network) == (2, Decimal("0.40"), Decimal("0.05"))
    assert (day.excise, day.quality, day.renewable, day.cogeneration) == (
        Decimal("0.005"), Decimal("0.0313"), Decimal("0.0073"), Decimal("0.003"),
    )
    assert day.gross == (Decimal("0.60") + Decimal("0.40") + Decimal("0.0466")) * Decimal("1.23")
    assert result.gross()[_utc(date(2026, 3, 4), 23, 45)] == pytest.approx(0.4966 * 1.23, abs=1e-5)


def test_dynamic_tariff_price_is_market_price_with_margin_and_distribution_of_the_group():
    offer = definition(T.DYNAMIC, ["0.08", "0.08"], ["0.40", "0.05"], hours=HOURS[T.G12], distribution_group=T.G12,
                       market_price_floor_mwh=Decimal("0"))
    market = {_utc(date(2026, 3, 4), 10): 0.35, _utc(date(2026, 3, 4), 13): -0.20}

    result = quarter_prices([offer], [PERIOD], _utc(date(2026, 3, 4), 10), _utc(date(2026, 3, 4), 13, 15),
                            market_price=lambda slot: market.get(slot, 0.30))

    assert result.prices[_utc(date(2026, 3, 4), 10)].energy == Decimal("0.35") + Decimal("0.08")
    assert result.prices[_utc(date(2026, 3, 4), 10)].network == Decimal("0.40")
    # Ujemna cena rynkowa ograniczona do 0 (dolny limit oferty), 13:00 to strefa nocna G12.
    assert result.prices[_utc(date(2026, 3, 4), 13)].energy == Decimal("0.08")
    assert result.prices[_utc(date(2026, 3, 4), 13)].network == Decimal("0.05")


def test_dynamic_tariff_requires_market_prices():
    offer = definition(T.DYNAMIC, ["0.08"], ["0.30"])

    with pytest.raises(ValueError, match="RCE"):
        quarter_prices([offer], [PERIOD], _utc(date(2026, 3, 4), 0), _utc(date(2026, 3, 5), 0))


def test_rate_change_within_range_switches_price_at_local_midnight_and_splits_monthly_fees():
    january = definition(T.G11, ["0.50"], ["0.30"], fixed="10", subscription="5", valid=JANUARY)
    february = definition(T.G11, ["0.62"], ["0.33"], fixed="12", subscription="5", valid=FROM_FEBRUARY)

    result = quarter_prices([february, january], [PERIOD], _utc(date(2026, 1, 31), 0), _utc(date(2026, 2, 2), 0),
                            fee_parameters=FEES)

    assert result.prices[_utc(date(2026, 1, 31), 23, 45)].energy == Decimal("0.50")
    assert result.prices[_utc(date(2026, 2, 1), 0)].energy == Decimal("0.62")
    assert [(item.valid_from, item.valid_to) for item in result.monthly_fees] == [
        (date(2026, 1, 31), date(2026, 1, 31)), (date(2026, 2, 1), date(2026, 2, 1)),
    ]
    first, second = (item.fees for item in result.monthly_fees)
    # Opłata mocowa z progu 1200+ kWh rocznie: 10,00 zł.
    assert (first.fixed_network, first.subscription, first.capacity) == (Decimal("10"), Decimal("5"), Decimal("10.00"))
    assert second.fixed_network == Decimal("12")


def test_quarters_without_market_price_are_reported_as_missing():
    offer = definition(T.DYNAMIC, ["0.08"], ["0.30"])
    gap = _utc(date(2026, 3, 4), 5)

    def market(slot):
        if slot == gap:
            raise ValueError("Brak ceny RCE")
        return 0.30

    result = quarter_prices([offer], [PERIOD], _utc(date(2026, 3, 4), 0), _utc(date(2026, 3, 5), 0), market_price=market)

    assert result.missing == (gap,)
    assert len(result.prices) == 95


def test_quarters_without_rates_or_regulatory_fees_are_reported_as_missing():
    january = definition(T.G11, ["0.50"], ["0.30"], valid=JANUARY)
    january_fees = period(valid=JANUARY)

    result = quarter_prices([january], [january_fees], _utc(date(2026, 1, 31), 23), _utc(date(2026, 2, 1), 1))

    assert len(result.prices) == 4 and len(result.missing) == 4


@pytest.mark.parametrize("change_rates", [False, True], ids=["stale-stawki", "zmiana-stawek-1-lutego"])
def test_sum_of_quarters_and_monthly_fees_equals_bill_of_each_cycle(change_rates):
    if change_rates:
        definitions = [
            definition(T.G12, ["0.60", "0.40"], ["0.40", "0.05"], fixed="10", subscription="5", valid=JANUARY),
            definition(T.G12, ["0.66", "0.42"], ["0.43", "0.06"], fixed="12", subscription="6", valid=FROM_FEBRUARY),
        ]
    else:
        definitions = [definition(T.G12, ["0.60", "0.40"], ["0.40", "0.05"], fixed="10", subscription="5")]
    readings = _readings(date(2026, 1, 1), 59)

    bill = _engine_bill(definitions, readings)
    prices = quarter_prices(definitions, [PERIOD], _utc(date(2026, 1, 1), 0), _utc(date(2026, 3, 1), 0),
                            fee_parameters=FEES)

    assert [money(_bill_from_quarters(prices, readings, month)) for month in (1, 2)] == [
        cycle.gross_total for cycle in bill.cycles
    ]


def test_sum_of_quarters_equals_bill_for_dynamic_offer():
    offer = definition(T.DYNAMIC, ["0.08"], ["0.30"], fixed="10", subscription="0", trade_fee_monthly=Decimal("9.99"),
                       market_price_floor_mwh=Decimal("0"))
    readings = _readings(date(2026, 1, 1), 59, seed=11)

    bill = _engine_bill([offer], readings, market=_market)
    prices = quarter_prices([offer], [PERIOD], _utc(date(2026, 1, 1), 0), _utc(date(2026, 3, 1), 0),
                            market_price=_market, fee_parameters=FEES)

    assert prices.monthly_fees[0].fees.trade == Decimal("9.99")
    assert [money(_bill_from_quarters(prices, readings, month)) for month in (1, 2)] == [
        cycle.gross_total for cycle in bill.cycles
    ]


@pytest.mark.parametrize("code", [T.G13, T.DYNAMIC])
@pytest.mark.perf
def test_year_of_quarters_for_one_tariff_takes_under_a_second(code):
    tariff = definition(code, ["0.9", "0.6", "0.3"] if code == T.G13 else ["0.08"],
                        ["0.2", "0.1", "0.05"] if code == T.G13 else ["0.30"])
    market = {}
    slot = _utc(date(2026, 1, 1), 0)
    while slot < _utc(date(2027, 1, 1), 0):
        market[slot] = 0.3
        slot += SLOT

    started = time.perf_counter()
    result = quarter_prices([tariff], [PERIOD], _utc(date(2026, 1, 1), 0), _utc(date(2027, 1, 1), 0),
                            market_price=market.__getitem__, fee_parameters=FEES)
    elapsed = time.perf_counter() - started

    assert len(result.prices) == 365 * 96
    assert elapsed < 1.0 * TIME_LIMIT_SCALE


class _PriceRepository:
    def __init__(self):
        self.calls = []

    def get_prices_between(self, source, start_utc, end_utc):
        self.calls.append((start_utc, end_utc))
        prices, slot = {}, start_utc
        while slot < end_utc:
            prices[slot] = Decimal("300")
            slot += SLOT
        return prices


def test_market_prices_of_whole_range_are_loaded_with_one_query():
    repository = _PriceRepository()
    resolver = DynamicMarketPriceResolver(repository)

    resolver.preload_rce(_utc(date(2026, 1, 15), 0), _utc(date(2026, 4, 10), 0))
    prices = [resolver.rce(_utc(date(2026, month, 3), 12)) for month in (1, 2, 3, 4)]

    assert len(repository.calls) == 1
    assert repository.calls[0] == (_utc(date(2026, 1, 1), 0), _utc(date(2026, 5, 1), 0))
    assert prices == [0.3] * 4


def _service(definitions, market=None):
    repository = SimpleNamespace(
        list_for_period=lambda **kwargs: list(definitions), list_regulatory_periods=lambda **kwargs: [PERIOD],
    )
    return QuarterPriceService(repository, market)


def test_service_prices_any_tariff_of_the_operator():
    g11 = definition(T.G11, ["0.50"], ["0.30"])
    g12 = definition(T.G12, ["0.60", "0.40"], ["0.40", "0.05"])

    result = _service([g11, g12]).for_tariff(
        operator=DistributionOperatorEnum.PGE, tariff_code=T.G12, distribution_group=T.G12,
        start_utc=_utc(date(2026, 3, 4), 0), end_utc=_utc(date(2026, 3, 5), 0), fee_parameters=FEES,
    )

    assert result.prices[_utc(date(2026, 3, 4), 10)].energy == Decimal("0.60")
    assert len(result.monthly_fees) == 1


def test_service_preloads_market_prices_for_dynamic_offer():
    offer = definition(T.DYNAMIC, ["0.08"], ["0.30"])
    repository = _PriceRepository()

    result = _service([offer], DynamicMarketPriceResolver(repository)).for_tariff(
        operator=DistributionOperatorEnum.PGE, tariff_code=T.DYNAMIC, distribution_group=T.G11,
        start_utc=_utc(date(2026, 3, 4), 0), end_utc=_utc(date(2026, 3, 6), 0),
    )

    assert len(repository.calls) == 1
    assert result.prices[_utc(date(2026, 3, 5), 18)].energy == Decimal("0.3") + Decimal("0.08")


def test_service_reports_tariff_without_rates():
    with pytest.raises(MissingTariffRates):
        _service([definition(T.G11, ["0.50"], ["0.30"])]).for_tariff(
            operator=DistributionOperatorEnum.PGE, tariff_code=T.G13, distribution_group=T.G13,
            start_utc=_utc(date(2026, 3, 4), 0), end_utc=_utc(date(2026, 3, 5), 0),
        )
