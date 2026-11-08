"""Ceny kwadransów dla optymalizacji: nowy cennik według taryfy z profilu (strefa, cena dynamiczna, opłaty za kWh)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.schemas.other import TariffTypeEnum as T
from app.services.schedule_prices import SchedulePriceService
from tariff_helpers import HOURS, definition, period

WARSAW = ZoneInfo("Europe/Warsaw")
BASE_INFO = {
    "type_of_property": "single_family_house", "year_of_construction": 2010, "heating_area_m2": 120.0,
    "number_of_residents": 3, "town": "Kraków", "postal_code": "30-001", "distribution_operator": "TAURON",
    "phase_type": "1_phase", "contracted_power_kw": 10.0, "billing_cycle": 2, "billing_period_start_date": "2026-01-01",
}
G12 = definition(T.G12, ["0.60", "0.40"], ["0.40", "0.05"])
DYNAMIC_G12 = definition(T.DYNAMIC, ["0.10", "0.10"], ["0.40", "0.05"], hours=HOURS[T.G12],
                         distribution_group=T.G12, market_price_floor_mwh=Decimal("0"))
PERIOD = period(quality="0.03", renewable="0.007", cogeneration="0.003", excise="0.005")


def _service(dynamic=False, definitions=(G12, DYNAMIC_G12), market=lambda slot: 0.30, pv_mode="none"):
    profile = SimpleNamespace(
        base_info=BASE_INFO,
        consumption_and_tariff={"tariff_type": "G12", "dynamic_price": dynamic},
        pv_config={"mode": pv_mode},
    )
    return SchedulePriceService(
        SimpleNamespace(get_profile=lambda user_id: profile),
        SimpleNamespace(list_for_period=lambda **kwargs: list(definitions), list_regulatory_periods=lambda **kwargs: [PERIOD]),
        market,
    )


def _local(hour):
    return datetime(2026, 11, 6, hour, tzinfo=WARSAW).astimezone(timezone.utc)


def _prices(service):
    return service.for_user(None, _local(0), _local(0) + timedelta(days=1))


def test_regular_tariff_slot_price_is_zone_energy_and_distribution_with_fees_and_vat():
    result = _prices(_service())

    # Opłaty za kWh: akcyza 0,005 + jakościowa 0,03 + OZE 0,007 + kogeneracyjna 0,003 = 0,045.
    assert result.prices[_local(10)] == pytest.approx((0.60 + 0.40 + 0.045) * 1.23)  # strefa dzienna
    assert result.prices[_local(23)] == pytest.approx((0.40 + 0.05 + 0.045) * 1.23)  # strefa nocna
    assert len(result.prices) == 96
    assert result.description == "TAURON, G12"


def test_dynamic_price_uses_market_price_margin_and_distribution_of_the_group():
    result = _prices(_service(dynamic=True, market=lambda slot: -0.10 if slot == _local(13) else 0.30))

    assert result.prices[_local(10)] == pytest.approx((0.30 + 0.10 + 0.40 + 0.045) * 1.23)
    assert result.prices[_local(23)] == pytest.approx((0.30 + 0.10 + 0.05 + 0.045) * 1.23)
    # Ujemna cena rynkowa liczona jak 0 (dolny limit oferty), 13:00 to strefa nocna G12.
    assert result.prices[_local(13)] == pytest.approx((0 + 0.10 + 0.05 + 0.045) * 1.23)
    assert result.description == "TAURON, G12 z ceną dynamiczną"


def test_slots_without_market_price_are_left_out():
    def market(slot):
        if slot.astimezone(WARSAW).hour == 5:
            raise ValueError("Brak ceny RCE")
        return 0.30

    result = _prices(_service(dynamic=True, market=market))

    assert len(result.prices) == 92
    assert _local(5) not in result.prices


def test_missing_rates_for_profile_tariff_are_reported():
    with pytest.raises(HTTPException) as error:
        _prices(_service(dynamic=True, definitions=(G12,)))

    assert error.value.status_code == 422
    assert "G12 z ceną dynamiczną" in error.value.detail


def test_slot_with_pv_surplus_costs_value_of_lost_export_in_net_billing():
    surplus = {_local(12): 0.8}
    service = _service(market=lambda slot: 0.35, pv_mode="net_billing")

    result = service.for_user(None, _local(0), _local(0) + timedelta(days=1), surplus)

    # Kwadrans z nadwyżką: RCE 0,35 zł/kWh (tyle traci depozyt), pozostałe po cenie z sieci.
    assert result.prices[_local(12)] == pytest.approx(0.35)
    assert result.prices[_local(10)] == pytest.approx((0.60 + 0.40 + 0.045) * 1.23)


def test_slot_with_pv_surplus_in_net_metering_costs_share_not_returned():
    service = _service(pv_mode="net_metering")
    service.user_repository.get_profile(None).pv_config["power_of_pv_kwp"] = 6

    result = service.for_user(None, _local(0), _local(0) + timedelta(days=1), {_local(10): 1.0})

    # Oddaną energię odbiera się w 80%, więc zużycie nadwyżki od razu kosztuje 20% ceny z sieci.
    assert result.prices[_local(10)] == pytest.approx((0.60 + 0.40 + 0.045) * 1.23 * 0.2)

