from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.NewModels import TariffDefinition
from app.schemas.calculation import CalculationDetails, PVDetails, TariffData
from app.schemas.other import DistributionOperatorEnum, TariffTypeEnum, TypeOfMarketEnergyEnum
from app.services.pv_service import PVBalancingEngine
from app.services.tariff_engine import ZonedTariffCalculationStrategy
from app.services.tariff_zones import ZONE_COUNTS, zone_for


CYCLE_START = datetime(2026, 11, 1)
FRIDAY = date(2026, 11, 6)
SATURDAY = date(2026, 11, 7)


def _at(day: date, clock: str) -> datetime:
    return datetime.combine(day, datetime.strptime(clock, "%H:%M").time())


def _definition(code, energy, network, fixed="0", subscription="0", zones=None):
    """Definicja taryfy jak z bazy; strefa i stawki numerowane od 1, jak zone_index."""
    return SimpleNamespace(
        tariff_code=code,
        number_of_zones=zones or len(network),
        fixed_network_fee_1phase_monthly=Decimal(fixed),
        fixed_network_fee_3phase_monthly=Decimal(fixed),
        supplier_ure_rates=[
            SimpleNamespace(zone_index=index, energy_price_per_kwh_net_pln=Decimal(rate))
            for index, rate in enumerate(energy, start=1)
        ],
        variable_network_rates=[
            SimpleNamespace(zone_index=index, rate_per_kwh_net_pln=Decimal(rate))
            for index, rate in enumerate(network, start=1)
        ],
        subscription_fees=[SimpleNamespace(billing_cycle_months=1, monthly_fee_net_pln=Decimal(subscription))],
    )


def _details(tariff_type, readings, pv_details=None) -> CalculationDetails:
    return CalculationDetails(
        used_energy_cycles=[(CYCLE_START, readings)],
        tariff_data=TariffData(
            tariff_type=tariff_type,
            billing_cycle=1,
            billing_period_start_date=CYCLE_START.date(),
            distribution_operator=DistributionOperatorEnum.PGE,
            phase_type="1_phase",
            contracted_power_kw=10,
        ),
        pv_details=pv_details,
    )


def _cycle(definition, readings, prices=None):
    engine = ZonedTariffCalculationStrategy()
    if prices is not None:
        engine.set_dynamic_price_resolver(lambda timestamp: prices[timestamp])
    return engine.calculate(_details(definition.tariff_code, readings), definition).cycles[0]


def test_g11_bill_with_fees_and_vat():
    definition = _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"], fixed="10", subscription="5")
    readings = [(_at(FRIDAY, "08:00"), 2.0), (_at(FRIDAY, "23:00"), 3.0)]

    cycle = _cycle(definition, readings)

    # energia 5 × 0,50 + dystrybucja 5 × 0,30 + opłata stała 10 + abonament 5 = 19,00 netto
    assert cycle.active_energy_kwh == Decimal("5")
    assert cycle.active_energy_net == Decimal("2.50")
    assert cycle.variable_network_net == Decimal("1.50")
    assert cycle.net_total == Decimal("19.00")
    assert cycle.vat == Decimal("4.37")
    assert cycle.gross_total == Decimal("23.37")


def test_g12_counts_afternoon_break_as_cheaper_zone():
    definition = _definition(TariffTypeEnum.G12, ["1.00", "0.40"], ["0.20", "0.10"])
    readings = [(_at(FRIDAY, "10:00"), 1.0), (_at(FRIDAY, "14:00"), 2.0), (_at(FRIDAY, "23:00"), 1.0)]

    cycle = _cycle(definition, readings)

    # strefa dzienna 1 kWh, tańsza 3 kWh (13-15 i noc)
    assert cycle.active_energy_net == Decimal("2.20")  # 1 × 1,00 + 3 × 0,40
    assert cycle.variable_network_net == Decimal("0.50")  # 1 × 0,20 + 3 × 0,10


def test_g12w_counts_whole_weekend_as_cheaper_zone():
    definition = _definition(TariffTypeEnum.G12W, ["1.00", "0.40"], ["0", "0"])
    readings = [(_at(FRIDAY, "10:00"), 1.0), (_at(SATURDAY, "10:00"), 2.0)]

    assert _cycle(definition, readings).active_energy_net == Decimal("1.80")  # 1 × 1,00 + 2 × 0,40


def test_g13_puts_morning_and_evening_peak_in_most_expensive_zone():
    definition = _definition(TariffTypeEnum.G13, ["0.90", "0.60", "0.30"], ["0", "0", "0"])
    readings = [
        (_at(FRIDAY, "08:00"), 1.0),  # szczyt przedpołudniowy
        (_at(FRIDAY, "17:00"), 1.0),  # szczyt popołudniowy
        (_at(FRIDAY, "14:00"), 1.0),  # strefa środkowa
        (_at(FRIDAY, "21:30"), 1.0),  # strefa środkowa
        (_at(FRIDAY, "02:00"), 1.0),  # pozostałe godziny
    ]

    assert _cycle(definition, readings).active_energy_net == Decimal("3.30")  # 2 × 0,90 + 2 × 0,60 + 0,30


def test_g14d_uses_four_zones():
    definition = _definition(TariffTypeEnum.G14D, ["1.00", "0.70", "0.50", "0.30"], ["0", "0", "0", "0"])
    readings = [(_at(FRIDAY, clock), 1.0) for clock in ("08:00", "14:00", "18:00", "23:00")]

    assert _cycle(definition, readings).active_energy_net == Decimal("2.50")


def test_dynamic_tariff_adds_supplier_margin_to_rce():
    definition = _definition(TariffTypeEnum.DYNAMIC, ["0.40"], ["0.25"])
    readings = [(_at(FRIDAY, "10:00"), 2.0), (_at(FRIDAY, "11:00"), 1.0)]
    prices = {_at(FRIDAY, "10:00"): 0.50, _at(FRIDAY, "11:00"): -0.10}

    cycle = _cycle(definition, readings, prices)

    # 2 × (0,50 + 0,40) + 1 × (-0,10 + 0,40); ujemna cena RCE obniża koszt energii
    assert cycle.active_energy_net == Decimal("2.10")
    assert cycle.variable_network_net == Decimal("0.75")


def test_dynamic_tariff_without_margin_is_rejected():
    definition = _definition(TariffTypeEnum.DYNAMIC, [], ["0.25"])

    with pytest.raises(ValueError, match="Brak kompletu stawek"):
        _cycle(definition, [(_at(FRIDAY, "10:00"), 1.0)], {_at(FRIDAY, "10:00"): 0.5})


def test_definition_with_wrong_number_of_zones_is_rejected():
    definition = _definition(TariffTypeEnum.G13, ["0.90", "0.30"], ["0", "0"])

    with pytest.raises(ValueError, match="ma 2 stref"):
        _cycle(definition, [(_at(FRIDAY, "10:00"), 1.0)])


def test_cycle_without_consumption_pays_only_fixed_fees():
    definition = _definition(TariffTypeEnum.G12, ["1.00", "0.40"], ["0.20", "0.10"], fixed="10", subscription="5")

    cycle = _cycle(definition, [])

    assert cycle.active_energy_kwh == Decimal("0")
    assert cycle.net_total == Decimal("15.00")


@pytest.mark.parametrize("tariff_type", [code for code in ZONE_COUNTS if code != TariffTypeEnum.DYNAMIC])
def test_engine_and_pv_balancer_use_the_same_zones(tariff_type):
    week = [CYCLE_START + timedelta(minutes=15 * index) for index in range(7 * 96)]
    readings = [(moment, 1.0) for moment in week]

    engine_totals = ZonedTariffCalculationStrategy._zone_totals(readings, tariff_type)
    pv_totals = PVBalancingEngine.get_grouped_energy_by_zones(readings, tariff_type)

    assert engine_totals == [Decimal(str(total)) for total in pv_totals]


def test_bill_is_the_same_with_and_without_pv_when_nothing_is_exported():
    definition = _definition(TariffTypeEnum.G12, ["1.00", "0.40"], ["0.20", "0.10"], fixed="10", subscription="5")
    readings = [(_at(FRIDAY, "10:00"), 1.0), (_at(FRIDAY, "14:00"), 2.0), (_at(FRIDAY, "23:00"), 1.0)]
    pv_details = PVDetails(
        pv_energy_cycles=[(CYCLE_START, [])],
        mode="net_billing",
        type_of_market_energy=TypeOfMarketEnergyEnum.RCE,
    )
    engine = ZonedTariffCalculationStrategy()

    without_pv = engine.calculate(_details(TariffTypeEnum.G12, readings), definition)
    balanced = PVBalancingEngine().balance_pv(_details(TariffTypeEnum.G12, readings, pv_details))
    with_pv = engine.calculate(balanced, definition)

    assert with_pv == without_pv


def test_zone_hours_are_local_clock_hours():
    assert zone_for(_at(FRIDAY, "12:45"), TariffTypeEnum.G12) == 0
    assert zone_for(_at(FRIDAY, "13:00"), TariffTypeEnum.G12) == 1
    assert zone_for(_at(FRIDAY, "14:45"), TariffTypeEnum.G12) == 1
    assert zone_for(_at(FRIDAY, "15:00"), TariffTypeEnum.G12) == 0
    assert zone_for(_at(FRIDAY, "22:00"), TariffTypeEnum.G12) == 1
    assert zone_for(_at(FRIDAY, "05:45"), TariffTypeEnum.G12) == 1
    assert zone_for(_at(FRIDAY, "06:00"), TariffTypeEnum.G12) == 0


def test_net_billing_values_export_at_negative_rce_as_zero():
    prices = {_at(FRIDAY, "12:00"): -0.20, _at(FRIDAY, "13:00"): 0.50}
    balancer = PVBalancingEngine(lambda timestamp, kind: prices[timestamp])

    _, overpayment = balancer._apply_net_billing(
        pv_energy_cycles=[(CYCLE_START, [(_at(FRIDAY, "12:00"), 2.0), (_at(FRIDAY, "13:00"), 1.0)])],
        used_energy_cycles=[(CYCLE_START, [])],
        type_of_market_energy=TypeOfMarketEnergyEnum.RCE,
    )

    assert overpayment == [{"2026-11": pytest.approx(0.50)}]  # 2 kWh × 0 zł + 1 kWh × 0,50 zł


def test_tariff_definition_for_stoen_can_be_saved(db):
    definition = TariffDefinition(
        osd_operator=DistributionOperatorEnum.STOEN,
        tariff_code=TariffTypeEnum.G11,
        number_of_zones=1,
        valid_from=date(2099, 1, 1),
        valid_to=date(2099, 12, 31),
        fixed_network_fee_1phase_monthly=Decimal("8.50"),
        fixed_network_fee_3phase_monthly=Decimal("16.50"),
    )
    db.add(definition)
    db.flush()

    assert db.get(TariffDefinition, definition.id).osd_operator == DistributionOperatorEnum.STOEN
