import math
import os
import random
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.schemas.other import TariffTypeEnum
from app.services.new_calculations_service import CalculationsService
from app.services.pv_service import DynamicMarketPriceResolver
from app.services.tariff_costs import PricingProfile, TariffCostService
from tariff_helpers import FlatTariffRepository, definition, period

WARSAW = ZoneInfo("Europe/Warsaw")
TIME_LIMIT_SCALE = 2.0 if os.getenv("CI") else 1.0
JANUARY = (date(2026, 1, 1), date(2026, 1, 31))
FROM_FEBRUARY = (date(2026, 2, 1), date(2026, 12, 31))
YEAR = (date(2026, 1, 1), date(2026, 12, 31))
G11, G12, G13, DYNAMIC = TariffTypeEnum.G11, TariffTypeEnum.G12, TariffTypeEnum.G13, TariffTypeEnum.DYNAMIC


def _with_cycles(item, fee="0.75"):
    item.subscription_fees = [
        SimpleNamespace(billing_cycle_months=months, monthly_fee_net_pln=Decimal(fee)) for months in (1, 2, 6, 12)
    ]
    return item


def _definitions():
    dynamic = _with_cycles(definition(DYNAMIC, ["0.08"], ["0.35"], fixed="4.5", valid=YEAR), "0")
    dynamic.trade_fee_monthly = Decimal("29.99")
    dynamic.required_billing_cycle_months = 1
    dynamic.name = "Oferta dynamiczna"
    return [
        _with_cycles(definition(G11, ["0.62"], ["0.35"], fixed="4.5", valid=JANUARY)),
        _with_cycles(definition(G11, ["0.70"], ["0.38"], fixed="5.1", valid=FROM_FEBRUARY)),
        _with_cycles(definition(G12, ["0.70", "0.40"], ["0.40", "0.10"], fixed="4.5", valid=YEAR)),
        _with_cycles(definition(G13, ["0.80", "0.60", "0.35"], ["0.45", "0.30", "0.08"], fixed="4.5", valid=YEAR)),
        dynamic,
    ]


def _periods():
    return [
        period(quality="0.0313", renewable="0.0073", cogeneration="0.003", excise="0.005",
               capacity=("2.5", "6", "10"), transition=("0.33", "1.2", "2.5"), valid=YEAR),
    ]


class _MarketRepository:
    """Ceny RCE (zł/MWh) każdego kwadransa; `missing` to kwadranse bez ceny."""

    def __init__(self, missing=()):
        self.missing = set(missing)
        self.queries = 0

    def get_prices_between(self, source, start_utc, end_utc):
        self.queries += 1
        prices, slot = {}, start_utc
        while slot < end_utc:
            if slot not in self.missing:
                prices[slot] = Decimal(str(round(400 + 250 * math.sin(slot.timestamp() / 7200), 2)))
            slot += timedelta(minutes=15)
        return prices

    def get_rcem_price(self, source, month):
        return None


def _usage(first: date, days: int, seed: int = 3) -> dict[str, list[float | None]]:
    generator = random.Random(seed)
    return {
        (first + timedelta(days=offset)).isoformat(): [round(generator.uniform(0.0, 0.6), 4) for _ in range(96)]
        for offset in range(days)
    }


def _readings(usage):
    return [
        SimpleNamespace(
            measured_at=datetime.fromisoformat(day) + timedelta(minutes=15 * slot),
            energy_kwh=Decimal(str(kwh)),
            exported_kwh=Decimal("0"),
        )
        for day, slots in usage.items()
        for slot, kwh in enumerate(slots)
        if kwh is not None
    ]


def _profile(tariff="G12", dynamic=False, billing_cycle=2, start="2025-12-01", operator="TAURON", phase="3_phase"):
    return SimpleNamespace(
        base_info={
            "type_of_property": "apartment", "year_of_construction": 2000, "heating_area_m2": 60,
            "number_of_residents": 2, "town": "Wrocław", "postal_code": "50-370", "distribution_operator": operator,
            "phase_type": phase, "contracted_power_kw": 5, "billing_cycle": billing_cycle,
            "billing_period_start_date": start,
        },
        consumption_and_tariff={"tariff_type": tariff, "dynamic_price": dynamic},
        pv_config={"mode": "none"},
    )


class _Repository:
    def __init__(self, **results):
        for name, result in results.items():
            setattr(self, name, lambda *args, _result=result, **kwargs: _result)


def _engine_bills(profile, usage, market):
    service = CalculationsService(
        _Repository(get_profile=profile),
        _Repository(get_by_id_for_user=SimpleNamespace(status="completed", STATUS_COMPLETED="completed")),
        _Repository(list_for_file=_readings(usage)),
        FlatTariffRepository(_definitions(), _periods()),
        market_price_repository=market,
    )
    details = service.perform_tariff_calculations(None, None)
    bills = {key: result["payable_gross"] for key, result in details.tariff_calculations.items()}
    bills.update({f"{group}-dynamic": result["payable_gross"] for group, result in (details.dynamic_calculations or {}).items()})
    return bills


def _costs(profile, usage, market=None):
    service = TariffCostService(
        FlatTariffRepository(_definitions(), _periods()),
        market_prices=DynamicMarketPriceResolver(market or _MarketRepository()),
    )
    return service.usage_costs(PricingProfile.from_saved(profile), usage)


@pytest.mark.parametrize(
    "billing_cycle, start",
    [(2, "2025-12-01"), (1, "2026-01-01"), (6, "2026-03-15"), (12, "2025-07-01")],
    ids=["2-mies", "1-mies", "6-mies-od-15", "12-mies"],
)
def test_cost_of_every_tariff_equals_bill_from_calculation_results(billing_cycle, start):
    usage = _usage(date(2026, 1, 10), 100)
    profile = _profile(billing_cycle=billing_cycle, start=start)

    costs = _costs(profile, usage)

    assert {key: item["estimated_cost_pln"] for key, item in costs.tariffs.items()} == _engine_bills(
        profile, usage, _MarketRepository()
    )
    assert list(costs.tariffs) == ["G11", "G12", "G13", "G11-dynamic"]


def test_cost_includes_spring_time_change_like_calculation_results():
    usage = _usage(date(2026, 3, 27), 5)

    costs = _costs(_profile(), usage)

    assert costs.tariffs["G13"]["price_coverage"] == 1.0
    assert {key: item["estimated_cost_pln"] for key, item in costs.tariffs.items()} == _engine_bills(
        _profile(), usage, _MarketRepository()
    )


def test_monthly_fees_are_reported_separately_from_cost_of_kwh():
    usage = _usage(date(2026, 1, 1), 59)

    tariff = _costs(_profile(), usage).tariffs["G12"]

    assert tariff["energy_cost_pln"] + tariff["monthly_fees_pln"] == pytest.approx(tariff["estimated_cost_pln"], abs=1e-9)
    assert tariff["monthly_fees_pln"] > 0
    assert tariff["monthly_fee_gross"] == pytest.approx((4.5 + 0.75 + 10 + 2.5) * 1.23, abs=0.01)
    assert sum(tariff["cost_breakdown"].values()) == pytest.approx(tariff["energy_cost_pln"], abs=0.03)
    assert tariff["billing_cycle_months"] == 2


def test_dynamic_offer_is_billed_monthly_with_trade_fee():
    usage = _usage(date(2026, 2, 1), 28)

    offer = _costs(_profile(), usage).tariffs["G11-dynamic"]

    assert offer["billing_cycle_months"] == 1
    assert offer["type"] == "dynamiczna"
    assert offer["name"] == "Oferta dynamiczna"
    assert offer["monthly_fee_gross"] == pytest.approx((4.5 + 29.99 + 10 + 2.5) * 1.23, abs=0.01)


def test_profile_tariff_is_marked_and_selected():
    costs = _costs(_profile("G13"), _usage(date(2026, 2, 1), 3))

    assert [key for key, item in costs.tariffs.items() if item["is_profile"]] == ["G13"]
    assert costs.pricing == {
        "operator": "TAURON", "from_profile": True, "profile_tariff": "G13",
        "tariff_key": "G13", "tariff_label": "G13", "note": None, "all_tariffs": True,
    }


def test_dynamic_profile_selects_offer_of_its_distribution_group():
    costs = _costs(_profile("G11", dynamic=True), _usage(date(2026, 2, 1), 3))

    assert costs.pricing["tariff_key"] == "G11-dynamic"
    assert costs.pricing["tariff_label"] == "G11 z ceną dynamiczną"
    assert costs.tariffs["G11-dynamic"]["is_profile"] is True


def test_profile_tariff_without_rates_falls_back_to_g11_with_note():
    costs = _costs(_profile("G12w"), _usage(date(2026, 2, 1), 3))

    assert costs.pricing["tariff_key"] == "G11"
    assert "nie ma w cenniku stawek taryfy G12w" in costs.pricing["note"]
    assert not any(item["is_profile"] for item in costs.tariffs.values())


def test_without_profile_costs_are_for_pge_g11():
    service = TariffCostService(FlatTariffRepository(_definitions(), _periods()), _Repository(get_profile=None))

    profile = service.profile("user")
    costs = service.usage_costs(profile, _usage(date(2026, 2, 1), 3))

    assert (profile.operator.value, profile.key, profile.from_profile) == ("PGE", "G11", False)
    assert costs.pricing["tariff_key"] == "G11" and costs.pricing["from_profile"] is False
    assert not any(item["is_profile"] for item in costs.tariffs.values())


def test_outdated_profile_is_treated_as_missing():
    outdated = _profile()
    del outdated.base_info["billing_period_start_date"]

    assert PricingProfile.from_saved(outdated) == PricingProfile()


def test_missing_market_prices_are_reported_and_estimated_from_priced_quarters():
    usage = _usage(date(2026, 2, 2), 2)
    start = datetime(2026, 2, 2, tzinfo=WARSAW).astimezone(timezone.utc)
    missing = {start + timedelta(minutes=15 * index) for index in range(48)}

    offer = _costs(_profile(), usage, _MarketRepository(missing)).tariffs["G11-dynamic"]
    chart = _costs(_profile(), usage, _MarketRepository(missing)).slot_prices["G11-dynamic"]["prices_by_day"]

    assert offer["missing_price_intervals"] == sum(1 for kwh in usage["2026-02-02"][:48] if kwh > 0)
    assert offer["price_coverage"] < 1
    assert offer["estimated_cost_pln"] is not None
    assert chart["2026-02-02"][:48] == [None] * 48 and None not in chart["2026-02-03"]


def test_tariff_without_rates_for_profile_billing_cycle_is_reported_without_cost():
    definitions = _definitions()
    definitions[2].subscription_fees = [SimpleNamespace(billing_cycle_months=1, monthly_fee_net_pln=Decimal("1"))]
    service = TariffCostService(FlatTariffRepository(definitions, _periods()), market_prices=DynamicMarketPriceResolver(_MarketRepository()))

    costs = service.usage_costs(PricingProfile.from_saved(_profile()), _usage(date(2026, 2, 1), 3))

    assert costs.tariffs["G12"]["estimated_cost_pln"] is None
    assert "abonamentowej" in costs.tariffs["G12"]["note"]
    assert "G12" not in costs.slot_prices


def test_empty_usage_has_no_costs():
    costs = _costs(_profile(), {"2026-02-01": [None] * 96})

    assert costs.tariffs == {} and costs.slot_prices == {}
    assert costs.pricing["tariff_key"] is None


def test_year_of_all_tariffs_of_operator_is_priced_quickly():
    usage = _usage(date(2026, 1, 1), 365)

    started = time.perf_counter()
    costs = _costs(_profile(), usage)
    elapsed = time.perf_counter() - started

    assert all(item["estimated_cost_pln"] is not None for item in costs.tariffs.values())
    assert elapsed < 2.0 * TIME_LIMIT_SCALE


def test_days_before_operator_rates_are_cut_off_like_in_calculation_results():
    usage = _usage(date(2025, 12, 20), 40)

    costs = _costs(_profile(start="2025-12-01"), usage)

    assert {key: item["estimated_cost_pln"] for key, item in costs.tariffs.items()} == _engine_bills(
        _profile(start="2025-12-01"), usage, _MarketRepository()
    )
    assert costs.tariffs["G12"]["price_coverage"] == 1.0
    assert costs.tariffs["G12"]["total_usage_kwh"] == pytest.approx(
        sum(sum(slots) for day, slots in usage.items() if day >= "2026-01-01"), abs=0.01
    )
    assert "Dni przed 01.01.2026 nie liczymy — koszty obejmują 01.01.2026 – 28.01.2026." in costs.pricing["note"]
    assert costs.pricing["tariff_key"] == "G12"
    assert all(day >= "2026-01-01" for day in costs.slot_prices["G12"]["prices_by_day"])


def test_period_only_before_operator_rates_has_no_costs():
    costs = _costs(_profile(), _usage(date(2025, 11, 1), 10))

    assert costs.tariffs == {} and costs.slot_prices == {}
    assert costs.pricing["tariff_key"] is None
    assert costs.pricing["note"] == (
        "Koszty u operatora TAURON liczymy od 01.01.2026, a wybrany okres obejmuje tylko wcześniejsze dni "
        "(01.11.2025 – 10.11.2025)."
    )


def test_offer_available_later_than_period_start_is_left_out_like_in_calculation_results():
    definitions = _definitions()
    definitions[-1].valid_from = date(2026, 2, 1)
    usage = _usage(date(2026, 1, 10), 40)
    service = TariffCostService(
        FlatTariffRepository(definitions, _periods()), market_prices=DynamicMarketPriceResolver(_MarketRepository())
    )

    offer = service.usage_costs(PricingProfile.from_saved(_profile()), usage).tariffs["G11-dynamic"]

    assert offer["estimated_cost_pln"] is None
    assert offer["note"] == "Oferta dynamiczna: oferta dostępna od 01.02.2026, a okres zaczyna się 10.01.2026."


def test_only_profile_tariff_is_priced_when_others_are_not_needed():
    usage = _usage(date(2026, 2, 1), 10)

    everything = _costs(_profile("G13"), usage)
    service = TariffCostService(
        FlatTariffRepository(_definitions(), _periods()), market_prices=DynamicMarketPriceResolver(_MarketRepository())
    )
    only_profile = service.usage_costs(PricingProfile.from_saved(_profile("G13")), usage, all_tariffs=False)

    assert list(only_profile.tariffs) == ["G13"] and list(only_profile.slot_prices) == ["G13"]
    assert only_profile.tariffs["G13"] == everything.tariffs["G13"]
    assert only_profile.pricing == {**everything.pricing, "all_tariffs": False}


def test_only_fallback_tariff_is_priced_when_profile_tariff_has_no_rates():
    service = TariffCostService(FlatTariffRepository(_definitions(), _periods()))

    costs = service.usage_costs(PricingProfile.from_saved(_profile("G12w")), _usage(date(2026, 2, 1), 3), all_tariffs=False)

    assert list(costs.tariffs) == ["G11"]
    assert costs.pricing["tariff_key"] == "G11" and "G12w" in costs.pricing["note"]
