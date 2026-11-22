"""ZP-145: szybki silnik rachunku na sumach dziennych, z tym samym wynikiem co liczenie kwadrans po kwadransie."""
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.schemas.calculation import CalculationDetails, TariffData
from app.schemas.other import DistributionOperatorEnum, TariffTypeEnum
from app.services.new_calculations_service import CalculationsService
from app.services.pv_service import PVBalancingEngine
from app.services.quarter_prices import TariffRates
from app.services.tariff_engine import (
    BillingContext,
    ZonedTariffCalculationStrategy,
    money,
    prepare_days,
    zone_runs,
    zone_totals,
)
from app.services.tariff_zones import ZoneSchedule
from tariff_helpers import HOURS, FlatTariffRepository, definition, period
from test_tariff_comparison import (
    TIME_LIMIT_SCALE,
    _definitions,
    _MarketRepository,
    _periods,
    _profile,
    _readings,
    _Repository,
    _usage,
)

G12, G12W, DYNAMIC = TariffTypeEnum.G12, TariffTypeEnum.G12W, TariffTypeEnum.DYNAMIC
JANUARY = (date(2026, 1, 1), date(2026, 1, 31))
PERIOD = period(quality="0.03", renewable="0.007", cogeneration="0.003", excise="0.005")


def _engine_result(definitions, records, *, market=None, prosumer=False):
    engine = ZonedTariffCalculationStrategy()
    if market is not None:
        engine.set_dynamic_price_resolver(market)
    details = CalculationDetails(
        used_energy_cycles=[(datetime(2026, 1, 1), records)],
        tariff_data=TariffData(
            tariff_type=definitions[0].tariff_code, billing_cycle=1, billing_period_start_date=date(2026, 1, 1),
            distribution_operator=DistributionOperatorEnum.PGE, phase_type="1_phase", contracted_power_kw=10,
        ),
    )
    context = BillingContext(
        regulatory_periods=[PERIOD], annual_kwh=Decimal("3000"), first_day=date(2026, 1, 1),
        last_day=date(2026, 1, 31), prosumer=prosumer,
    )
    return engine.calculate(details, definitions, context)


@pytest.mark.parametrize(
    "day", [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 10), date(2026, 3, 29), date(2026, 10, 25)],
    ids=["poniedzialek", "swieto", "sobota", "zmiana-na-letni", "zmiana-na-zimowy"],
)
def test_zone_of_each_quarter_matches_zone_hours(day):
    schedule = ZoneSchedule([definition(G12W, ["0.7", "0.4"], ["0.4", "0.1"], valid=(date(2026, 1, 1), date(2026, 12, 31)))])

    zones = schedule.quarter_zones(day)

    assert zones == tuple(
        schedule.zone_index(datetime.combine(day, datetime.min.time()) + timedelta(minutes=15 * quarter))
        for quarter in range(96)
    )


def test_zone_runs_group_consecutive_quarters():
    assert zone_runs((2, 2, 1, 1, 1, 2)) == ((2, 0, 2), (1, 2, 5), (2, 5, 6))
    assert zone_runs((1,) * 96) == ((1, 0, 96),)


def test_day_prefix_gives_energy_of_any_quarter_range():
    records = [(datetime(2026, 1, 5) + timedelta(minutes=15 * quarter), 0.1 * quarter) for quarter in range(96)]
    day = prepare_days(records)[date(2026, 1, 5)]

    prefix = day.quarter_prefix()

    assert prefix[10] - prefix[4] == sum((Decimal(str(0.1 * quarter)) for quarter in range(4, 10)), Decimal("0"))
    assert prefix[96] == day.total


def test_readings_off_quarter_boundaries_are_billed_in_their_zone():
    g12 = definition(G12, ["0.70", "0.40"], ["0.40", "0.10"], valid=JANUARY)
    schedule = ZoneSchedule([g12])
    records = [(datetime(2026, 1, 5, hour, minute), 0.25) for hour in range(24) for minute in (0, 7, 30, 52)]

    result = _engine_result([g12], records)

    zones = zone_totals(records, schedule)
    expected = zones[0] * Decimal("0.70") + zones[1] * Decimal("0.40")
    assert result.cycles[0].active_energy_net == money(expected)
    assert result.cycles[0].active_energy_kwh == sum(zones, Decimal("0"))
    assert prepare_days(records)[date(2026, 1, 5)].quarter_prefix() is None


def test_dynamic_offer_on_daily_sums_equals_quarter_by_quarter_with_limits_and_prosumer_margin():
    offer = definition(DYNAMIC, ["0.08", "0.08"], ["0.40", "0.10"], hours=HOURS[G12], valid=JANUARY,
                       market_price_floor_mwh=Decimal("0"), market_price_cap_mwh=Decimal("500"),
                       prosumer_margin_per_kwh=Decimal("0.02"))
    offer.distribution_group = G12
    schedule = ZoneSchedule([offer])
    records = [(datetime(2026, 1, 1) + timedelta(minutes=15 * index), round(0.05 + (index % 7) * 0.031, 3))
               for index in range(31 * 96)]

    def market(timestamp):
        return round(-0.1 + (timestamp.hour * 4 + timestamp.minute // 15) * 0.0075, 4)

    result = _engine_result([offer], records, market=market, prosumer=True)

    rates = TariffRates(offer, PERIOD)
    prices = [rates.price(schedule.zone_index(timestamp), market(timestamp), True) for timestamp, _ in records]
    active = sum((Decimal(str(value)) * price.energy for (_, value), price in zip(records, prices)), Decimal("0"))
    network = sum((Decimal(str(value)) * price.network for (_, value), price in zip(records, prices)), Decimal("0"))
    assert result.cycles[0].active_energy_net == money(active)
    assert result.cycles[0].variable_network_net == money(network)


def test_dynamic_offer_reports_first_quarter_without_market_price():
    offer = definition(DYNAMIC, ["0.08"], ["0.35"], valid=JANUARY)
    records = [(datetime(2026, 1, 3) + timedelta(minutes=15 * index), 0.2) for index in range(96)]
    missing = datetime(2026, 1, 3, 5, 15)

    def market(timestamp):
        if timestamp >= missing:
            raise ValueError(f"Brak ceny RCE dla interwału {timestamp.isoformat()}.")
        return 0.4

    with pytest.raises(ValueError, match="2026-01-03T05:15:00"):
        _engine_result([offer], records, market=market)


def test_net_billing_is_balanced_once_and_only_for_the_same_cycles():
    engine = PVBalancingEngine(lambda timestamp, kind: 0.3)
    calls = []
    original = engine._apply_net_billing

    def counted(*args):
        calls.append(args)
        return original(*args)

    engine._apply_net_billing = counted
    first_pv = [(datetime(2026, 1, 1), [(datetime(2026, 1, 1, 12), 1.0)])]
    first_used = [(datetime(2026, 1, 1), [(datetime(2026, 1, 1, 12), 0.2)])]
    other_used = [(datetime(2026, 1, 1), [(datetime(2026, 1, 1, 12), 0.9)])]

    once = engine._net_billing_once(first_pv, first_used, "RCE")
    other = engine._net_billing_once(first_pv, other_used, "RCE")
    again = engine._net_billing_once(first_pv, first_used, "RCE")

    assert len(calls) == 2
    assert once is again
    assert other[1] != once[1]


def test_reused_engine_does_not_mix_up_readings_of_different_calls():
    g12 = definition(G12, ["0.70", "0.40"], ["0.40", "0.10"], valid=JANUARY)
    first = [(datetime(2026, 1, 5) + timedelta(minutes=15 * index), 0.25) for index in range(96)]
    second = [(timestamp, 0.5) for timestamp, _ in first]
    engine = ZonedTariffCalculationStrategy()

    def bill(records, strategy):
        details = CalculationDetails(
            used_energy_cycles=[(datetime(2026, 1, 1), records)],
            tariff_data=TariffData(
                tariff_type=G12, billing_cycle=1, billing_period_start_date=date(2026, 1, 1),
                distribution_operator=DistributionOperatorEnum.PGE, phase_type="1_phase", contracted_power_kw=10,
            ),
        )
        context = BillingContext(
            regulatory_periods=[PERIOD], annual_kwh=Decimal("3000"), first_day=date(2026, 1, 1),
            last_day=date(2026, 1, 31),
        )
        return strategy.calculate(details, [g12], context).gross_total

    assert bill(first, engine) == bill(first, ZonedTariffCalculationStrategy())
    assert bill(second, engine) == bill(second, ZonedTariffCalculationStrategy())
    assert bill(second, engine) > bill(first, engine)


def _service(readings, profile=None):
    return CalculationsService(
        _Repository(get_profile=profile or _profile(start="2026-01-01")),
        _Repository(get_by_id_for_user=SimpleNamespace(status="completed", STATUS_COMPLETED="completed")),
        _Repository(list_for_file=readings),
        FlatTariffRepository(_definitions(), _periods()),
        market_price_repository=_MarketRepository(),
    )


def _best_time(readings, **kwargs):
    best = float("inf")
    for _ in range(3):
        service = _service(readings)
        started = time.perf_counter()
        service.perform_tariff_calculations(None, None, **kwargs)
        best = min(best, time.perf_counter() - started)
    return best


def test_year_of_every_tariff_is_billed_quickly():
    year = _readings(_usage(date(2026, 1, 1), 365))

    assert _best_time(year) < 0.5 * TIME_LIMIT_SCALE
    assert _best_time(year, selected_only=True) < 0.15 * TIME_LIMIT_SCALE


def test_month_of_every_tariff_is_billed_quickly():
    month = _readings(_usage(date(2026, 3, 1), 31))

    assert _best_time(month) < 0.1 * TIME_LIMIT_SCALE
