from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.NewModels import TariffDefinition
from app.schemas.calculation import CalculationDetails, PVDetails, TariffData
from app.schemas.other import DistributionOperatorEnum, TariffTypeEnum, TypeOfMarketEnergyEnum
from app.services.new_calculations_service import CalculationsService
from app.services.pv_service import PVBalancingEngine
from app.services.tariff_engine import BillingContext, ZonedTariffCalculationStrategy
from app.services.tariff_zones import ZONE_COUNTS, zone_for


CYCLE_START = datetime(2026, 11, 1)
CYCLE_END = date(2026, 11, 30)
FRIDAY = date(2026, 11, 6)
SATURDAY = date(2026, 11, 7)
YEAR_2026 = (date(2026, 1, 1), date(2026, 12, 31))


def _at(day: date, clock: str) -> datetime:
    return datetime.combine(day, datetime.strptime(clock, "%H:%M").time())


def _definition(code, energy, network, fixed="0", subscription="0", zones=None, valid=YEAR_2026, cycle_months=1):
    """Definicja taryfy jak z bazy; strefa i stawki numerowane od 1, jak zone_index."""
    return SimpleNamespace(
        tariff_code=code,
        number_of_zones=zones or len(network),
        valid_from=valid[0],
        valid_to=valid[1],
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
        subscription_fees=[SimpleNamespace(billing_cycle_months=cycle_months, monthly_fee_net_pln=Decimal(subscription))],
    )


def _thresholds(*fees):
    """Progi rocznego zużycia jak w seedzie: do 500, do 1200 i powyżej 1200 kWh."""
    bounds = [(0, 500), (500, 1200), (1200, None)]
    return [
        SimpleNamespace(min_kwh_annual=Decimal(low), max_kwh_annual=None if high is None else Decimal(high),
                        monthly_fee_net_pln=Decimal(fee))
        for (low, high), fee in zip(bounds, fees)
    ]


def _period(quality="0", renewable="0", cogeneration="0", capacity=("0", "0", "0"), transition=("0", "0", "0"),
            vat="0.23", valid=YEAR_2026):
    return SimpleNamespace(
        valid_from=valid[0],
        valid_to=valid[1],
        quality_fee_per_kwh=Decimal(quality),
        renewable_energy_fee_per_kwh=Decimal(renewable),
        cogeneration_fee_per_kwh=Decimal(cogeneration),
        vat_rate=Decimal(vat),
        capacity_thresholds=_thresholds(*capacity),
        transition_thresholds=_thresholds(*transition),
    )


def _context(periods=None, annual="1000", first=CYCLE_START.date(), last=CYCLE_END, raw_cycles=()):
    return BillingContext(
        regulatory_periods=periods or [_period()],
        annual_kwh=Decimal(annual),
        first_day=first,
        last_day=last,
        raw_cycles=raw_cycles,
    )


def _details(tariff_type, readings, pv_details=None, cycle_start=CYCLE_START, cycle_months=1) -> CalculationDetails:
    return CalculationDetails(
        used_energy_cycles=[(cycle_start, readings)],
        tariff_data=TariffData(
            tariff_type=tariff_type,
            billing_cycle=cycle_months,
            billing_period_start_date=cycle_start.date(),
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
    return engine.calculate(_details(definition.tariff_code, readings), [definition], _context()).cycles[0]


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

    without_pv = engine.calculate(_details(TariffTypeEnum.G12, readings), [definition], _context())
    balanced = PVBalancingEngine().balance_pv(_details(TariffTypeEnum.G12, readings, pv_details))
    with_pv = engine.calculate(balanced, [definition], _context())

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


# --- ZP-89: opłaty regulacyjne, zmiana cennika w okresie, opłaty za dni z pliku ---

PROFILE = {
    "type_of_property": "single_family_house",
    "year_of_construction": 2010,
    "heating_area_m2": 120.0,
    "number_of_residents": 3,
    "town": "Warszawa",
    "postal_code": "00-001",
    "distribution_operator": "PGE",
    "phase_type": "1_phase",
    "contracted_power_kw": 10.0,
    "billing_cycle": 1,
    "billing_period_start_date": "2026-01-01",
}
YEAR_2027 = (date(2027, 1, 1), date(2027, 12, 31))
DECEMBER_START = datetime(2026, 12, 1)


class _Repository:
    def __init__(self, **methods):
        for name, result in methods.items():
            setattr(self, name, lambda *args, _result=result, **kwargs: _result)


def _service(readings, definitions, periods):
    rows = [
        SimpleNamespace(measured_at=moment, energy_kwh=Decimal(str(kwh)), exported_kwh=Decimal("0"))
        for moment, kwh in readings
    ]
    return CalculationsService(
        _Repository(get_profile=SimpleNamespace(
            base_info=PROFILE, consumption_and_tariff={"tariff_type": "G11"}, pv_config={"mode": "none"},
        )),
        _Repository(get_by_id_for_user=SimpleNamespace(status="completed", STATUS_COMPLETED="completed")),
        _Repository(list_for_file=rows),
        _Repository(list_for_period=definitions, list_regulatory_periods=periods),
    )


def test_bill_lists_every_regulatory_fee_separately():
    definition = _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"], fixed="10", subscription="5")
    period = _period(quality="0.01", renewable="0.002", cogeneration="0.003",
                     capacity=("3", "8", "15"), transition=("0", "1", "2"))
    engine = ZonedTariffCalculationStrategy()

    cycle = engine.calculate(
        _details(TariffTypeEnum.G11, [(_at(FRIDAY, "08:00"), 100.0)]), [definition], _context([period], annual="1000"),
    ).cycles[0]

    assert cycle.active_energy_net == Decimal("50.00")
    assert cycle.variable_network_net == Decimal("30.00")
    assert cycle.quality_net == Decimal("1.00")
    assert cycle.renewable_net == Decimal("0.20")
    assert cycle.cogeneration_net == Decimal("0.30")
    assert cycle.fixed_network_net == Decimal("10.00")
    assert cycle.subscription_net == Decimal("5.00")
    assert cycle.capacity_net == Decimal("8.00")  # 1000 kWh rocznie: próg 500-1200
    assert cycle.transition_net == Decimal("1.00")
    assert cycle.net_total == Decimal("105.50")
    assert cycle.vat == Decimal("24.27")
    assert cycle.gross_total == Decimal("129.77")


def test_cycle_across_new_year_uses_rates_valid_on_each_day():
    definitions = [
        _definition(TariffTypeEnum.G11, ["0.50"], ["0"], fixed="10", cycle_months=2, valid=YEAR_2026),
        _definition(TariffTypeEnum.G11, ["0.60"], ["0"], fixed="12", cycle_months=2, valid=YEAR_2027),
    ]
    periods = [_period(quality="0.01", valid=YEAR_2026), _period(quality="0.02", valid=YEAR_2027)]
    readings = [(_at(date(2026, 12, 15), "10:00"), 2.0), (_at(date(2027, 1, 15), "10:00"), 3.0)]
    details = _details(TariffTypeEnum.G11, readings, cycle_start=DECEMBER_START, cycle_months=2)

    cycle = ZonedTariffCalculationStrategy().calculate(
        details, definitions, _context(periods, first=date(2026, 12, 1), last=date(2027, 1, 31)),
    ).cycles[0]

    assert (cycle.days_billed, cycle.days_in_cycle) == (62, 62)
    assert cycle.active_energy_net == Decimal("2.80")  # 2 × 0,50 + 3 × 0,60
    assert cycle.quality_net == Decimal("0.08")  # 2 × 0,01 + 3 × 0,02
    assert cycle.fixed_network_net == Decimal("22.00")  # 10 × 2 × 31/62 + 12 × 2 × 31/62


def test_monthly_fees_are_charged_only_for_days_in_file():
    definition = _definition(TariffTypeEnum.G11, ["0.50"], ["0"], fixed="10", cycle_months=2)
    period = _period(capacity=("8", "8", "8"))
    details = _details(TariffTypeEnum.G11, [(_at(date(2026, 10, 10), "10:00"), 1.0)],
                       cycle_start=datetime(2026, 10, 1), cycle_months=2)

    cycle = ZonedTariffCalculationStrategy().calculate(
        details, [definition], _context([period], first=date(2026, 10, 1), last=date(2026, 10, 30)),
    ).cycles[0]

    # okres 1.10-30.11 (61 dni), plik 30 dni: opłata miesięczna × 2 miesiące × 30/61
    assert (cycle.days_billed, cycle.days_in_cycle) == (30, 61)
    assert cycle.fixed_network_net == Decimal("9.84")
    assert cycle.capacity_net == Decimal("7.87")


@pytest.mark.parametrize(
    ("annual", "fee"),
    [("0", "3"), ("499.99", "3"), ("500", "8"), ("1199.99", "8"), ("1200", "15"), ("30000", "15")],
)
def test_capacity_fee_threshold_by_annual_consumption(annual, fee):
    thresholds = _thresholds("3", "8", "15")

    assert ZonedTariffCalculationStrategy._threshold_fee(thresholds, Decimal(annual), "mocowej") == Decimal(fee)


def test_short_file_is_scaled_to_a_year_for_thresholds():
    days = [date(2026, 10, 1) + timedelta(days=offset) for offset in range(30)]
    readings = [SimpleNamespace(measured_at=_at(day, "12:00"), energy_kwh=Decimal("100") / 30) for day in days]

    consumption = CalculationsService._annual_consumption(readings)

    assert (consumption.days, consumption.scaled) == (30, True)
    assert consumption.annual_kwh == pytest.approx(100 * 365 / 30)
    # 100 kWh w pliku to rocznie ok. 1217 kWh, więc próg powyżej 1200, a nie do 500
    assert ZonedTariffCalculationStrategy._threshold_fee(
        _thresholds("3", "8", "15"), Decimal(str(consumption.annual_kwh)), "mocowej"
    ) == Decimal("15")


def test_full_year_file_is_not_scaled():
    days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(365)]
    readings = [SimpleNamespace(measured_at=_at(day, "12:00"), energy_kwh=Decimal("2")) for day in days]

    consumption = CalculationsService._annual_consumption(readings)

    assert (consumption.days, consumption.scaled, consumption.annual_kwh) == (365, False, 730)


def test_missing_regulatory_period_is_reported_instead_of_billing_without_fees():
    readings = [(_at(date(2026, 12, 31), "10:00"), 1.0), (_at(date(2027, 1, 2), "10:00"), 1.0)]
    definitions = [
        _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"], valid=YEAR_2026),
        _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"], valid=YEAR_2027),
    ]

    with pytest.raises(HTTPException) as error:
        _service(readings, definitions, [_period(valid=YEAR_2026)]).perform_tariff_calculations(None, None)

    assert error.value.status_code == 409
    assert "2027-01-01 – 2027-01-02" in error.value.detail


def test_days_without_tariff_rates_are_named_in_error():
    definition = _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"], cycle_months=2, valid=YEAR_2026)
    details = _details(TariffTypeEnum.G11, [(_at(date(2026, 12, 31), "10:00"), 1.0)],
                       cycle_start=DECEMBER_START, cycle_months=2)

    with pytest.raises(ValueError, match="Brak stawek taryfy G11 dla dni: 2027-01-01 – 2027-01-02"):
        ZonedTariffCalculationStrategy().calculate(
            details, [definition], _context([_period(valid=(date(2026, 1, 1), date(2027, 12, 31)))],
                                            first=date(2026, 12, 31), last=date(2027, 1, 2)),
        )


def test_service_reports_annual_consumption_and_itemized_bill():
    days = [date(2026, 11, 1) + timedelta(days=offset) for offset in range(30)]
    readings = [(_at(day, "10:00"), 2.0) for day in days]
    definition = _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"], fixed="10", subscription="5")

    result = _service(readings, [definition], [_period(quality="0.01")]).perform_tariff_calculations(None, None)

    assert result.annual_consumption.annual_kwh == pytest.approx(730)
    cycle = result.tariff_calculation["cycles"][0]
    assert cycle["quality_net"] == pytest.approx(0.60)  # 60 kWh × 0,01
    assert cycle["days_billed"] == 30


def test_balanced_zone_energy_is_split_between_rate_periods_by_consumption_before_pv():
    definitions = [
        _definition(TariffTypeEnum.G11, ["0.50"], ["0"], cycle_months=2, valid=YEAR_2026),
        _definition(TariffTypeEnum.G11, ["0.60"], ["0"], cycle_months=2, valid=YEAR_2027),
    ]
    raw = [(_at(date(2026, 12, 15), "10:00"), 1.0), (_at(date(2027, 1, 15), "10:00"), 3.0)]
    details = _details(TariffTypeEnum.G11, [10.0], cycle_start=DECEMBER_START, cycle_months=2)
    context = _context([_period(valid=(date(2026, 1, 1), date(2027, 12, 31)))], first=date(2026, 12, 1),
                       last=date(2027, 1, 31), raw_cycles=[(DECEMBER_START, raw)])

    cycle = ZonedTariffCalculationStrategy().calculate(details, definitions, context).cycles[0]

    # 10 kWh po net-meteringu: 2,5 kWh w grudniu i 7,5 kWh w styczniu (jak 1 : 3 przed bilansowaniem)
    assert cycle.active_energy_net == Decimal("5.75")


def test_net_billing_keeps_real_cycle_start():
    october = datetime(2026, 10, 1)
    details = CalculationDetails(
        used_energy_cycles=[(october, [(_at(date(2026, 10, 5), "10:00"), 1.0)])],
        tariff_data=TariffData(
            tariff_type=TariffTypeEnum.DYNAMIC, billing_cycle=1, billing_period_start_date=date(2026, 1, 1),
            distribution_operator=DistributionOperatorEnum.PGE, phase_type="1_phase", contracted_power_kw=10,
        ),
        pv_details=PVDetails(pv_energy_cycles=[(october, [])], mode="net_billing",
                             type_of_market_energy=TypeOfMarketEnergyEnum.RCE),
    )

    balanced = PVBalancingEngine(lambda timestamp, kind: 0.5).balance_pv(details)

    assert balanced.used_energy_cycles[0][0] == october
