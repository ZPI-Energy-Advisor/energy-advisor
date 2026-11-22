import math
import random
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.schemas.other import TariffTypeEnum
from app.services.energy_file_service import EnergyFileService
from app.services.new_calculations_service import CalculationsService
from app.services.pv_service import DynamicMarketPriceResolver
from app.services.tariff_comparison import Reading, comparison, readings_from_usage, recommendation
from app.services.tariff_costs import PricingProfile, TariffCostService
from timing import TIME_LIMIT_SCALE
from tariff_helpers import FlatTariffRepository, definition, period

WARSAW = ZoneInfo("Europe/Warsaw")
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


PV_CONFIGS = {
    "none": {"mode": "none"},
    "net_billing": {"mode": "net_billing", "type_of_price": "RCE"},
    "net_metering": {"mode": "net_metering", "power_of_pv_kwp": 5},
}


def _with_pv(profile, mode):
    profile.pv_config = PV_CONFIGS[mode]
    return profile


def _with_export(readings, seed=5):
    generator = random.Random(seed)
    return [
        SimpleNamespace(
            measured_at=reading.measured_at,
            energy_kwh=reading.energy_kwh if not 10 <= reading.measured_at.hour < 15 else Decimal("0"),
            exported_kwh=Decimal(str(round(generator.uniform(0.1, 0.9), 4))) if 10 <= reading.measured_at.hour < 15
            else Decimal("0"),
        )
        for reading in readings
    ]


def _calculations(profile, readings=None, definitions=None, market=None):
    return CalculationsService(
        _Repository(get_profile=profile),
        _Repository(get_by_id_for_user=SimpleNamespace(status="completed", STATUS_COMPLETED="completed")),
        _Repository(list_for_file=readings),
        FlatTariffRepository(definitions if definitions is not None else _definitions(), _periods()),
        market_price_repository=market or _MarketRepository(),
    )


def _engine_bills(profile, readings, definitions=None):
    details = _calculations(profile, readings, definitions).perform_tariff_calculations(None, None)
    bills = {key: result["payable_gross"] for key, result in details.tariff_calculations.items()}
    bills.update({f"{group}-dynamic": result["payable_gross"] for group, result in (details.dynamic_calculations or {}).items()})
    return bills


def _data_tariffs(profile, readings, *, all_tariffs=False, definitions=None, market=None):
    files = EnergyFileService(None, None, None, None, _calculations(profile, None, definitions, market))
    first_day = min((reading.measured_at for reading in readings), default=datetime(2026, 1, 1)).date()
    return files._usage_tariffs("user", readings, first_day, all_tariffs)


def _comparison(profile, readings, *, all_tariffs=True, definitions=None, market=None):
    service = _calculations(profile, None, definitions, market)
    inputs = service.profile_inputs("user", readings[0].measured_at.date())
    return comparison(service.calculate(readings, inputs, selected_only=not all_tariffs, fallback=True))


def _all_tariffs(profile, readings, *, definitions=None, market=None):
    return {
        entry["key"]: entry
        for entry in _comparison(profile, readings, definitions=definitions, market=market)["tariffs"]
    }


def _chart_prices(profile, usage, keys, market=None):
    service = TariffCostService(
        FlatTariffRepository(_definitions(), _periods()),
        market_prices=DynamicMarketPriceResolver(market or _MarketRepository()),
    )
    return service.chart_prices(PricingProfile.from_saved(profile), usage, keys)


def _estimates(tariffs):
    return {key: item["payable_gross"] for key, item in tariffs.items()}


@pytest.mark.parametrize(
    "billing_cycle, start",
    [(2, "2025-12-01"), (1, "2026-01-01"), (6, "2026-03-15"), (12, "2025-07-01")],
    ids=["2-mies", "1-mies", "6-mies-od-15", "12-mies"],
)
def test_cost_of_every_tariff_equals_bill_from_calculation_results(billing_cycle, start):
    readings = _readings(_usage(date(2026, 1, 10), 100))
    profile = _profile(billing_cycle=billing_cycle, start=start)

    tariffs = _all_tariffs(profile, readings)

    assert _estimates(tariffs) == _engine_bills(profile, readings)
    assert list(tariffs) == ["G11", "G12", "G13", "G11-dynamic"]


@pytest.mark.parametrize("mode", ["net_billing", "net_metering"])
def test_with_pv_cost_equals_calculation_results_and_splits_into_kwh_and_monthly_fees(mode):
    readings = _with_export(_readings(_usage(date(2026, 3, 1), 61)))
    profile = _with_pv(_profile(), mode)

    _, pricing = _data_tariffs(profile, readings)
    compared = _comparison(profile, readings)
    tariffs = {entry["key"]: entry for entry in compared["tariffs"]}

    priced = {key: value for key, value in _estimates(tariffs).items() if value is not None}
    assert priced == _engine_bills(profile, readings)
    assert compared["pv_mode"] == mode
    for item in tariffs.values():
        if item["payable_gross"] is not None:
            assert item["energy_cost_pln"] + item["monthly_fees_pln"] == pytest.approx(item["payable_gross"], abs=1e-9)
            assert item["energy_cost_pln"] >= 0
    assert pricing["tariff_key"] == "G12"
    if mode == "net_metering":
        assert "net-meteringu" in tariffs["G11-dynamic"]["note"]


def test_net_billing_deposit_lowers_cost_of_kwh():
    readings = _with_export(_readings(_usage(date(2026, 6, 1), 30)))

    compared = _comparison(_with_pv(_profile(), "net_billing"), readings)

    g12 = next(entry for entry in compared["tariffs"] if entry["key"] == "G12")
    assert g12["deposit_applied"] > 0
    assert g12["payable_gross"] == pytest.approx(g12["gross_total"] - g12["deposit_applied"], abs=0.005)
    assert g12["energy_cost_pln"] + g12["monthly_fees_pln"] == pytest.approx(g12["payable_gross"], abs=1e-9)


def test_export_without_pv_in_profile_is_reported():
    readings = _with_export(_readings(_usage(date(2026, 3, 1), 5)))

    _, pricing = _data_tariffs(_profile(), readings)
    compared = _comparison(_profile(), readings)

    assert compared["pv_mode"] is None
    assert any("energii oddanej do sieci" in warning for warning in compared["warnings"])
    assert "energii oddanej do sieci" in pricing["note"]


def test_monthly_fees_are_reported_separately_from_cost_of_kwh():
    tariff = _data_tariffs(_profile(), _readings(_usage(date(2026, 1, 1), 59)))[0]["G12"]

    assert tariff["energy_cost_pln"] + tariff["monthly_fees_pln"] == pytest.approx(tariff["estimated_cost_pln"], abs=1e-9)
    assert tariff["monthly_fees_pln"] > 0
    assert tariff["monthly_fee_gross"] == pytest.approx((4.5 + 0.75 + 10 + 2.5) * 1.23, abs=0.01)
    assert sum(tariff["cost_breakdown"].values()) == pytest.approx(tariff["energy_cost_pln"], abs=0.03)
    assert tariff["billing_cycle_months"] == 2


def test_dynamic_offer_is_billed_monthly_with_trade_fee():
    offer = _all_tariffs(_profile(), _readings(_usage(date(2026, 2, 1), 28)))["G11-dynamic"]

    assert offer["billing_cycle_months"] == 1
    assert offer["type"] == "dynamiczna"
    assert offer["name"] == "Oferta dynamiczna"
    assert offer["monthly_fee_gross"] == pytest.approx((4.5 + 29.99 + 10 + 2.5) * 1.23, abs=0.01)


def test_profile_tariff_is_marked_and_selected():
    readings = _readings(_usage(date(2026, 2, 1), 3))

    tariffs, pricing = _data_tariffs(_profile("G13"), readings)

    assert [key for key, item in tariffs.items() if item["is_profile"]] == ["G13"]
    assert [key for key, item in _all_tariffs(_profile("G13"), readings).items() if item["is_profile"]] == ["G13"]
    assert pricing == {
        "operator": "TAURON", "from_profile": True, "profile_tariff": "G13",
        "tariff_key": "G13", "tariff_label": "G13", "note": None, "all_tariffs": False,
    }


def test_dynamic_profile_selects_offer_of_its_distribution_group():
    tariffs, pricing = _data_tariffs(_profile("G11", dynamic=True), _readings(_usage(date(2026, 2, 1), 3)))

    assert pricing["tariff_key"] == "G11-dynamic"
    assert pricing["tariff_label"] == "G11 z ceną dynamiczną"
    assert tariffs["G11-dynamic"]["is_profile"] is True


def test_profile_tariff_without_rates_falls_back_to_g11_with_note():
    tariffs, pricing = _data_tariffs(_profile("G12w"), _readings(_usage(date(2026, 2, 1), 3)))

    assert pricing["tariff_key"] == "G11"
    assert "nie ma w cenniku stawek taryfy G12w" in pricing["note"]
    assert not any(item["is_profile"] for item in tariffs.values())


def test_without_profile_costs_are_for_pge_g11():
    tariffs, pricing = _data_tariffs(None, _readings(_usage(date(2026, 2, 1), 3)))

    assert (pricing["operator"], pricing["profile_tariff"], pricing["from_profile"]) == ("PGE", "G11", False)
    assert pricing["tariff_key"] == "G11"
    assert tariffs["G11"]["billing_cycle_months"] == 2
    assert not any(item["is_profile"] for item in tariffs.values())


def test_outdated_profile_is_treated_as_missing():
    outdated = _profile()
    del outdated.base_info["billing_period_start_date"]

    assert PricingProfile.from_saved(outdated) == PricingProfile()
    assert _calculations(outdated).profile_inputs("user", date(2026, 2, 3)) == (
        CalculationsService.default_inputs(date(2026, 2, 3))
    )


def test_missing_market_prices_leave_dynamic_offer_without_cost_and_gaps_in_chart():
    usage = _usage(date(2026, 2, 2), 2)
    start = datetime(2026, 2, 2, tzinfo=WARSAW).astimezone(timezone.utc)
    missing = {start + timedelta(minutes=15 * index) for index in range(48)}

    tariffs = _all_tariffs(_profile(), _readings(usage), market=_MarketRepository(missing))
    chart = _chart_prices(_profile(), usage, None, _MarketRepository(missing))["G11-dynamic"]["prices_by_day"]

    assert tariffs["G11-dynamic"]["payable_gross"] is None
    assert "RCE" in tariffs["G11-dynamic"]["note"]
    assert tariffs["G12"]["payable_gross"] is not None
    assert chart["2026-02-02"][:48] == [None] * 48 and None not in chart["2026-02-03"]


def test_tariff_without_rates_for_profile_billing_cycle_is_reported_without_cost():
    definitions = _definitions()
    definitions[2].subscription_fees = [SimpleNamespace(billing_cycle_months=1, monthly_fee_net_pln=Decimal("1"))]

    tariffs = _all_tariffs(_profile(), _readings(_usage(date(2026, 2, 1), 3)), definitions=definitions)

    assert tariffs["G12"]["payable_gross"] is None
    assert "abonamentowej" in tariffs["G12"]["note"]


def test_empty_usage_has_no_costs():
    tariffs, pricing = _data_tariffs(_profile(), [])

    assert tariffs == {}
    assert pricing["tariff_key"] is None
    assert _chart_prices(_profile(), {"2026-02-01": [None] * 96}, ["G11"]) == {}


@pytest.mark.perf
def test_year_of_all_tariffs_of_operator_is_priced_quickly():
    usage = _usage(date(2026, 1, 1), 365)
    readings = _readings(usage)

    started = time.perf_counter()
    tariffs = _all_tariffs(_profile(), readings)
    chart = _chart_prices(_profile(), usage, None)
    elapsed = time.perf_counter() - started

    assert all(item["payable_gross"] is not None for item in tariffs.values())
    assert set(chart) == set(tariffs)
    assert elapsed < 2.0 * TIME_LIMIT_SCALE


def test_days_before_operator_rates_are_cut_off_like_in_calculation_results():
    usage = _usage(date(2025, 12, 20), 40)
    readings = _readings(usage)

    tariffs, pricing = _data_tariffs(_profile(start="2025-12-01"), readings)
    chart = _chart_prices(_profile(start="2025-12-01"), usage, None)

    assert _estimates(_all_tariffs(_profile(start="2025-12-01"), readings)) == (
        _engine_bills(_profile(start="2025-12-01"), readings)
    )
    assert tariffs["G12"]["total_usage_kwh"] == pytest.approx(
        sum(sum(slots) for day, slots in usage.items() if day >= "2026-01-01"), abs=0.01
    )
    assert "Dni przed 01.01.2026 nie liczymy — rachunek obejmuje 01.01.2026 – 28.01.2026." in pricing["note"]
    assert pricing["tariff_key"] == "G12"
    assert all(day >= "2026-01-01" for day in chart["G12"]["prices_by_day"])


def test_period_only_before_operator_rates_has_no_costs():
    tariffs, pricing = _data_tariffs(_profile(), _readings(_usage(date(2025, 11, 1), 10)))

    assert tariffs == {}
    assert pricing["tariff_key"] is None
    assert pricing["note"] == (
        "Rachunki u operatora TAURON liczymy od 01.01.2026, a plik obejmuje tylko wcześniejsze dni "
        "(01.11.2025 – 10.11.2025)."
    )
    assert _chart_prices(_profile(), _usage(date(2025, 11, 1), 10), ["G12"]) == {}


def test_offer_available_later_than_period_start_is_left_out_like_in_calculation_results():
    definitions = _definitions()
    definitions[-1].valid_from = date(2026, 2, 1)

    tariffs = _all_tariffs(_profile(), _readings(_usage(date(2026, 1, 10), 40)), definitions=definitions)

    assert tariffs["G11-dynamic"]["payable_gross"] is None
    assert tariffs["G11-dynamic"]["note"] == "Oferta dynamiczna: oferta dostępna od 01.02.2026, a plik zaczyna się 10.01.2026."


def test_data_bills_only_profile_tariff_also_when_chart_has_every_tariff():
    readings = _readings(_usage(date(2026, 2, 1), 10))

    with_every_chart, every_pricing = _data_tariffs(_profile("G13"), readings, all_tariffs=True)
    only_profile, pricing = _data_tariffs(_profile("G13"), readings)

    assert list(only_profile) == list(with_every_chart) == ["G13"]
    assert only_profile["G13"]["estimated_cost_pln"] == _all_tariffs(_profile("G13"), readings)["G13"]["payable_gross"]
    assert pricing == {**every_pricing, "all_tariffs": False}


def test_only_fallback_tariff_is_priced_when_profile_tariff_has_no_rates():
    tariffs, pricing = _data_tariffs(_profile("G12w"), _readings(_usage(date(2026, 2, 1), 3)))

    assert list(tariffs) == ["G11"]
    assert pricing["tariff_key"] == "G11" and "G12w" in pricing["note"]


def test_comparison_shows_cheapest_tariff_and_difference_to_profile_tariff():
    readings = _readings(_usage(date(2026, 2, 1), 28))

    compared = _comparison(_profile("G13"), readings)

    payable = {entry["key"]: entry["payable_gross"] for entry in compared["tariffs"]}
    assert compared["selected_tariff"] == compared["profile_tariff"] == "G13"
    assert compared["cheapest_tariff"] == min(payable, key=payable.get)
    assert {entry["key"]: entry["difference_to_profile"] for entry in compared["tariffs"]} == {
        key: round(value - payable["G13"], 2) for key, value in payable.items()
    }
    g13 = next(entry for entry in compared["tariffs"] if entry["key"] == "G13")
    assert g13["is_profile"] and g13["billing_cycle_months"] == 2
    assert g13["cycles"] and set(g13["cycles"][0]) >= {"cycle_start", "active_energy_net", "gross_total"}
    assert compared["annual_consumption"].days == 28
    assert (compared["billed_from"], compared["billed_to"]) == (date(2026, 2, 1), date(2026, 2, 28))


def test_comparison_of_profile_tariff_only_equals_its_entry_in_full_comparison():
    readings = _with_export(_readings(_usage(date(2026, 4, 1), 30)))
    profile = _with_pv(_profile("G12"), "net_billing")

    everything = _comparison(profile, readings)
    only_profile = _comparison(profile, readings, all_tariffs=False)

    assert [entry["key"] for entry in only_profile["tariffs"]] == ["G12"]
    assert only_profile["tariffs"][0] == next(entry for entry in everything["tariffs"] if entry["key"] == "G12")


def test_readings_from_usage_skip_quarters_without_measurement():
    readings = readings_from_usage({"2026-02-01": [0.5, None] + [0.0] * 94})

    assert readings[0] == Reading(datetime(2026, 2, 1), 0.5, 0.0)
    assert readings[1].measured_at == datetime(2026, 2, 1, 0, 30)
    assert len(readings) == 95


def _priced(key, payable):
    return {"key": key, "payable_gross": payable}


@pytest.mark.parametrize(
    "entries, reference, days, expected",
    [
        (
            [_priced("G11", 400.0), _priced("G12", 330.0)], "G11", 61,
            {"tariff": "G12", "is_current": False, "saving": 70.0, "saving_percent": 17.5,
             "monthly_saving_estimate": round(70 * 365.25 / 12 / 61, 2), "difference_to_cheapest": 70.0},
        ),
        (
            [_priced("G11", 300.0), _priced("G12", 330.0)], "G11", 61,
            {"tariff": "G11", "is_current": True, "saving": 0.0, "saving_percent": 0.0,
             "monthly_saving_estimate": None, "difference_to_cheapest": 0.0},
        ),
        (
            [_priced("G11", 300.5), _priced("G12", 299.6)], "G11", 61,
            {"tariff": "G11", "is_current": True, "saving": 0.0, "saving_percent": 0.0,
             "monthly_saving_estimate": None, "difference_to_cheapest": 0.9},
        ),
        (
            [_priced("G11", 301.0), _priced("G12", 300.0)], "G11", 10,
            {"tariff": "G12", "is_current": False, "saving": 1.0, "saving_percent": 0.3,
             "monthly_saving_estimate": None, "difference_to_cheapest": 1.0},
        ),
        (
            [_priced("G11", 400.0), _priced("G12", 330.0)], None, 61,
            {"tariff": "G12", "is_current": False, "saving": None, "saving_percent": None,
             "monthly_saving_estimate": None, "difference_to_cheapest": None},
        ),
    ],
    ids=["oszczednosc", "aktualna-najtansza", "remis-ponizej-zlotowki", "krotki-okres-bez-szacunku", "bez-profilu"],
)
def test_recommendation_rules(entries, reference, days, expected):
    assert recommendation(entries, reference, days) == {**expected, "skipped_tariffs": []}


def test_recommendation_skips_tariffs_without_full_price_and_unpriced_profile_tariff():
    entries = [_priced("G11", None), _priced("G12", 330.0), _priced("G11-dynamic", None)]

    result = recommendation(entries, "G11", 61)

    assert result["tariff"] == "G12" and result["saving"] is None and result["is_current"] is False
    assert result["skipped_tariffs"] == ["G11", "G11-dynamic"]
    assert recommendation([_priced("G11", None)], "G11", 61) is None


def test_recommendation_without_percent_when_profile_tariff_costs_nothing():
    result = recommendation([_priced("G11", 0.0), _priced("G12", -5.0)], "G11", 61)

    assert result["saving"] == 5.0 and result["saving_percent"] is None


def _recommended(profile, readings, **kwargs):
    compared = _comparison(profile, readings, **kwargs)
    return compared, compared["recommendation"]


def test_recommendation_compares_payable_amounts_against_profile_tariff():
    readings = _readings(_usage(date(2026, 2, 1), 59))

    compared, recommended = _recommended(_profile("G11"), readings)

    payable = {entry["key"]: entry["payable_gross"] for entry in compared["tariffs"]}
    cheapest = min(payable, key=payable.get)
    assert recommended["tariff"] == cheapest != "G11"
    assert recommended["saving"] == round(payable["G11"] - payable[cheapest], 2)
    assert recommended["saving_percent"] == round(recommended["saving"] / payable["G11"] * 100, 1)
    assert recommended["monthly_saving_estimate"] == round(recommended["saving"] * 365.25 / 12 / 59, 2)


def test_cheapest_profile_tariff_is_confirmed():
    readings = _readings(_usage(date(2026, 2, 1), 28))
    payable = {entry["key"]: entry["payable_gross"] for entry in _comparison(_profile("G11"), readings)["tariffs"]}
    cheapest = min(payable, key=payable.get)
    profile = _profile(cheapest.removesuffix("-dynamic"), dynamic=cheapest.endswith("-dynamic"))

    _, recommended = _recommended(profile, readings)

    assert recommended == {
        "tariff": cheapest, "is_current": True, "saving": 0.0, "saving_percent": 0.0,
        "monthly_saving_estimate": None, "difference_to_cheapest": 0.0, "skipped_tariffs": [],
    }


@pytest.mark.parametrize("mode", ["net_billing", "net_metering"])
def test_recommendation_with_pv_uses_amounts_after_deposit(mode):
    readings = _with_export(_readings(_usage(date(2026, 3, 1), 61)))

    compared, recommended = _recommended(_with_pv(_profile("G11"), mode), readings)

    payable = {entry["key"]: entry["payable_gross"] for entry in compared["tariffs"] if entry["payable_gross"] is not None}
    assert recommended["tariff"] == min(payable, key=payable.get)
    assert recommended["saving"] == round(payable["G11"] - payable[recommended["tariff"]], 2)


def test_without_profile_recommends_cheapest_without_saving():
    compared, recommended = _recommended(None, _readings(_usage(date(2026, 2, 1), 28)))

    assert compared["from_profile"] is False
    assert recommended["tariff"] == compared["cheapest_tariff"]
    assert recommended["saving"] is None and recommended["is_current"] is False


def test_profile_tariff_without_rates_gives_no_saving_against_fallback():
    compared, recommended = _recommended(_profile("G12w"), _readings(_usage(date(2026, 2, 1), 28)))

    assert compared["selected_tariff"] == "G11" and compared["profile_tariff"] == "G12w"
    assert recommended["tariff"] == compared["cheapest_tariff"] and recommended["saving"] is None


def test_offer_without_market_prices_is_not_recommended():
    usage = _usage(date(2026, 2, 2), 2)
    start = datetime(2026, 2, 2, tzinfo=WARSAW).astimezone(timezone.utc)
    missing = {start + timedelta(minutes=15 * index) for index in range(48)}

    compared, recommended = _recommended(_profile("G11"), _readings(usage), market=_MarketRepository(missing))

    assert recommended["skipped_tariffs"] == ["G11-dynamic"]
    assert recommended["tariff"] != "G11-dynamic"
