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
from app.services.tariff_engine import (
    BillingContext,
    FinancialSettlement,
    ZonedTariffCalculationStrategy,
    billing_cycle_months,
    zone_totals,
)
from app.services.tariff_zones import ZoneSchedule
from tariff_helpers import HOURS, YEAR_2026
from tariff_helpers import definition as _definition
from tariff_helpers import period as _period
from tariff_helpers import thresholds as _thresholds


CYCLE_START = datetime(2026, 11, 1)
CYCLE_END = date(2026, 11, 30)
FRIDAY = date(2026, 11, 6)
SATURDAY = date(2026, 11, 7)


def _at(day: date, clock: str) -> datetime:
    return datetime.combine(day, datetime.strptime(clock, "%H:%M").time())



def _context(periods=None, annual="1000", first=CYCLE_START.date(), last=CYCLE_END, raw_cycles=(), prosumer=False):
    return BillingContext(
        regulatory_periods=periods or [_period()],
        annual_kwh=Decimal(annual),
        first_day=first,
        last_day=last,
        raw_cycles=raw_cycles,
        prosumer=prosumer,
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


def _cycle(definition, readings, prices=None, periods=None, prosumer=False):
    engine = ZonedTariffCalculationStrategy()
    if prices is not None:
        engine.set_dynamic_price_resolver(lambda timestamp: prices[timestamp])
    context = _context(periods, prosumer=prosumer)
    return engine.calculate(_details(definition.tariff_code, readings), [definition], context).cycles[0]


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
    # definicja z 2 strefami, a godziny G13 wskazują też strefę 3 (noc)
    definition = _definition(TariffTypeEnum.G13, ["0.90", "0.30"], ["0", "0"])

    with pytest.raises(ValueError, match=r"wskazują strefę 3 spoza liczby stref definicji \(2\)"):
        _cycle(definition, [(_at(FRIDAY, "10:00"), 1.0)])


def test_cycle_without_consumption_pays_only_fixed_fees():
    definition = _definition(TariffTypeEnum.G12, ["1.00", "0.40"], ["0.20", "0.10"], fixed="10", subscription="5")

    cycle = _cycle(definition, [])

    assert cycle.active_energy_kwh == Decimal("0")
    assert cycle.net_total == Decimal("15.00")


def test_dynamic_cycle_without_consumption_pays_only_fixed_fees():
    definition = _definition(TariffTypeEnum.DYNAMIC, ["0.40"], ["0.25"], fixed="10", subscription="5")

    cycle = _cycle(definition, [], prices={})

    # miesiąc bez poboru (np. cały pokryty net-billingiem) nie jest błędem taryfy dynamicznej
    assert cycle.active_energy_kwh == Decimal("0")
    assert cycle.net_total == Decimal("15.00")


@pytest.mark.parametrize("tariff_type", [code for code in HOURS if code != TariffTypeEnum.DYNAMIC])
def test_engine_and_pv_balancer_use_the_same_zones(tariff_type):
    zones = max(hour.zone_index for hour in HOURS[tariff_type])
    schedule = ZoneSchedule([_definition(tariff_type, ["0"] * zones, ["0"] * zones)])
    # tydzień od niedzieli 1.11 (święto) z sobotą i dniami roboczymi
    week = [CYCLE_START + timedelta(minutes=15 * index) for index in range(7 * 96)]
    readings = [(moment, 1.0) for moment in week]

    engine_totals = zone_totals(readings, schedule)
    pv_totals = PVBalancingEngine.get_grouped_energy_by_zones(readings, schedule)

    assert engine_totals == [Decimal(str(total)) for total in pv_totals]
    assert sum(engine_totals) == len(week)


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
    balanced = PVBalancingEngine().balance_pv(
        _details(TariffTypeEnum.G12, readings, pv_details), ZoneSchedule([definition])
    )
    with_pv = engine.calculate(balanced, [definition], _context())

    assert with_pv == without_pv


def test_zone_hours_are_local_clock_hours():
    schedule = ZoneSchedule([_definition(TariffTypeEnum.G12, ["1.00", "0.40"], ["0", "0"])])

    # strefy numerowane od 1, jak zone_index stawek: 1 = dzienna, 2 = tańsza
    assert schedule.zone_index(_at(FRIDAY, "12:45")) == 1
    assert schedule.zone_index(_at(FRIDAY, "13:00")) == 2
    assert schedule.zone_index(_at(FRIDAY, "14:45")) == 2
    assert schedule.zone_index(_at(FRIDAY, "15:00")) == 1
    assert schedule.zone_index(_at(FRIDAY, "22:00")) == 2
    assert schedule.zone_index(_at(FRIDAY, "05:45")) == 2
    assert schedule.zone_index(_at(FRIDAY, "06:00")) == 1


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
        distribution_group=TariffTypeEnum.G11,
        number_of_zones=1,
        valid_from=date(2099, 1, 1),
        valid_to=date(2099, 12, 31),
        distribution_source="Taryfa OSD (dane testowe)",
        energy_source="Taryfa sprzedawcy (dane testowe)",
        fixed_network_fee_1phase_monthly=Decimal("8.50"),
        fixed_network_fee_3phase_monthly=Decimal("16.50"),
    )
    db.add(definition)
    db.flush()

    saved = db.get(TariffDefinition, definition.id)
    assert saved.osd_operator == DistributionOperatorEnum.STOEN
    # okresy części OSD i sprzedawcy domyślnie = okres definicji
    assert (saved.distribution_valid_from, saved.energy_valid_to) == (date(2099, 1, 1), date(2099, 12, 31))


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


class _Prices:
    """Ceny RCE: ta sama cena (zł/MWh) dla każdego kwadransa żądanego zakresu [start, koniec)."""

    def __init__(self, price_mwh="400"):
        self.price_mwh = Decimal(price_mwh)

    def get_prices_between(self, source, start_utc, end_utc):
        prices, moment = {}, start_utc
        while moment < end_utc:
            prices[moment] = self.price_mwh
            moment += timedelta(minutes=15)
        return prices


def _service(readings, definitions, periods, *, base_info=None, tariff="G11", dynamic_price=False, pv_config=None,
             first_valid_from=None, unsupported=(), prices=None):
    rows = [
        SimpleNamespace(measured_at=moment, energy_kwh=Decimal(str(kwh)), exported_kwh=Decimal("0"))
        for moment, kwh in readings
    ]
    return CalculationsService(
        _Repository(get_profile=SimpleNamespace(
            base_info={**PROFILE, **(base_info or {})},
            consumption_and_tariff={"tariff_type": tariff, "dynamic_price": dynamic_price},
            pv_config=pv_config or {"mode": "none"},
        )),
        _Repository(get_by_id_for_user=SimpleNamespace(status="completed", STATUS_COMPLETED="completed")),
        _Repository(list_for_file=rows),
        _Repository(
            list_for_period=definitions,
            list_regulatory_periods=periods,
            first_valid_from=first_valid_from,
            list_unsupported=list(unsupported),
        ),
        market_price_repository=prices,
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


def test_period_without_transition_thresholds_has_no_transition_fee():
    definition = _definition(TariffTypeEnum.G11, ["0.50"], ["0"])

    cycle = _cycle(definition, [(_at(FRIDAY, "10:00"), 1.0)], periods=[_period(transition=())])

    # od 2026 r. opłaty przejściowej nie ma: okres bez progów = 0 zł zamiast błędu „brak progu”
    assert cycle.transition_net == Decimal("0.00")


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
    assert (result.warnings, result.tariff_notes, result.unsupported_tariffs) == (None, None, None)


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
    schedule = ZoneSchedule([_definition(TariffTypeEnum.DYNAMIC, ["0.10"], ["0.25"])])

    balanced = PVBalancingEngine(lambda timestamp, kind: 0.5).balance_pv(details, schedule)

    assert balanced.used_energy_cycles[0][0] == october


# --- ZP-99/ZP-101: akcyza, cena maksymalna, oferty dynamiczne, okresy rozliczeniowe, strefy z cennika ---


def test_excise_is_a_separate_line_whether_or_not_energy_price_includes_it():
    periods = [_period(excise="0.005")]
    readings = [(_at(FRIDAY, "10:00"), 100.0)]
    without_excise = _definition(TariffTypeEnum.G11, ["0.50"], ["0"])
    with_excise = _definition(TariffTypeEnum.G11, ["0.505"], ["0"], energy_includes_excise=True)

    separate = _cycle(without_excise, readings, periods=periods)
    included = _cycle(with_excise, readings, periods=periods)

    # cena bez akcyzy: energia 100 × 0,50 = 50,00 zł, akcyza osobno 100 × 0,005 = 0,50 zł
    assert (separate.active_energy_net, separate.excise_net) == (Decimal("50.00"), Decimal("0.50"))
    # cena z akcyzą 0,505: silnik odejmuje 0,005 i dolicza akcyzę osobną pozycją — ten sam rachunek
    assert (included.active_energy_net, included.excise_net) == (Decimal("50.00"), Decimal("0.50"))
    assert included.net_total == separate.net_total == Decimal("50.50")


@pytest.mark.parametrize(
    ("includes_excise", "active"),
    [
        # strefa 1: 0,6288 → cena maksymalna 0,50; strefa 2: 0,4012 poniżej ceny maksymalnej bez zmian
        # 100 × 0,50 + 100 × 0,4012 = 90,12 zł
        (False, "90.12"),
        # najpierw odejmujemy akcyzę, potem cena maksymalna: min(0,6238; 0,50) = 0,50 i 0,4012 − 0,005 = 0,3962
        # 100 × 0,50 + 100 × 0,3962 = 89,62 zł
        (True, "89.62"),
    ],
)
def test_price_cap_limits_energy_price_without_excise_in_each_zone(includes_excise, active):
    definition = _definition(TariffTypeEnum.G12, ["0.6288", "0.4012"], ["0", "0"],
                             energy_price_cap_per_kwh=Decimal("0.50"), energy_includes_excise=includes_excise)
    readings = [(_at(FRIDAY, "10:00"), 100.0), (_at(FRIDAY, "23:00"), 100.0)]

    cycle = _cycle(definition, readings, periods=[_period(excise="0.005")])

    assert cycle.active_energy_net == Decimal(active)
    assert cycle.excise_net == Decimal("1.00")  # akcyza osobno: 200 × 0,005


def test_dynamic_market_price_is_clamped_to_floor_and_cap_before_margin():
    definition = _definition(TariffTypeEnum.DYNAMIC, ["0.05"], ["0"],
                             market_price_floor_mwh=Decimal("0"), market_price_cap_mwh=Decimal("500"))
    readings = [(_at(FRIDAY, clock), 1.0) for clock in ("10:00", "11:00", "12:00")]
    prices = {_at(FRIDAY, "10:00"): -0.10, _at(FRIDAY, "11:00"): 0.80, _at(FRIDAY, "12:00"): 0.30}

    cycle = _cycle(definition, readings, prices)

    # RCE -100 zł/MWh → 0 (dolne ograniczenie), 800 zł/MWh → 500 (górne), 300 zł/MWh bez zmian; do każdej
    # marża 0,05 zł/kWh: (0 + 0,05) + (0,50 + 0,05) + (0,30 + 0,05) = 0,95 zł
    assert cycle.active_energy_net == Decimal("0.95")


def test_prosumer_pays_prosumer_margin_and_trade_fee_in_dynamic_offer():
    definition = _definition(TariffTypeEnum.DYNAMIC, ["0.08"], ["0"], prosumer_margin_per_kwh=Decimal("0.12"),
                             trade_fee_monthly=Decimal("10"), prosumer_trade_fee_monthly=Decimal("15"))
    readings = [(_at(FRIDAY, "10:00"), 10.0)]
    prices = {_at(FRIDAY, "10:00"): 0.40}

    consumer = _cycle(definition, readings, prices)
    prosumer = _cycle(definition, readings, prices, prosumer=True)

    # odbiorca: 10 × (0,40 + 0,08) = 4,80 zł i opłata handlowa 10 zł
    assert (consumer.active_energy_net, consumer.trade_fee_net) == (Decimal("4.80"), Decimal("10.00"))
    # prosument: 10 × (0,40 + 0,12) = 5,20 zł i opłata handlowa prosumenta 15 zł
    assert (prosumer.active_energy_net, prosumer.trade_fee_net) == (Decimal("5.20"), Decimal("15.00"))


@pytest.mark.parametrize(
    ("months", "last_day", "prosumer", "fee"),
    [
        (1, date(2026, 1, 31), False, "10.00"),  # 10 zł × 1 mies.
        (1, date(2026, 1, 31), True, "12.00"),  # wariant prosumenta 12 zł × 1 mies.
        (2, date(2026, 2, 28), False, "20.00"),  # 10 zł × 2 mies.
        (6, date(2026, 6, 30), False, "60.00"),  # 10 zł × 6 mies.
    ],
)
def test_monthly_trade_fee_is_charged_for_each_month_of_the_cycle(months, last_day, prosumer, fee):
    definition = _definition(
        TariffTypeEnum.G11, ["0.50"], ["0"],
        subscription_fees=[
            SimpleNamespace(billing_cycle_months=cycle, monthly_fee_net_pln=Decimal("0")) for cycle in (1, 2, 6)
        ],
        trade_fee_monthly=Decimal("10"), prosumer_trade_fee_monthly=Decimal("12"),
    )
    start = datetime(2026, 1, 1)
    details = _details(TariffTypeEnum.G11, [], cycle_start=start, cycle_months=months)

    cycle = ZonedTariffCalculationStrategy().calculate(
        details, [definition], _context(first=start.date(), last=last_day, prosumer=prosumer),
    ).cycles[0]

    assert cycle.trade_fee_net == Decimal(fee)


def test_offer_billing_cycle_overrides_profile_cycle():
    regular = _definition(TariffTypeEnum.G11, ["0.50"], ["0"])
    monthly = _definition(TariffTypeEnum.DYNAMIC, ["0.10"], ["0"], required_billing_cycle_months=1)
    bimonthly = _definition(TariffTypeEnum.DYNAMIC, ["0.10"], ["0"], required_billing_cycle_months=2)

    assert billing_cycle_months([regular], 2) == 2
    assert billing_cycle_months([monthly], 2) == 1
    with pytest.raises(ValueError, match="różnych okresów rozliczeniowych"):
        billing_cycle_months([monthly, bimonthly], 2)


def test_settlement_keeps_offer_name_and_cycle():
    definition = _definition(TariffTypeEnum.DYNAMIC, ["0.10"], ["0"], name="Dynamiczna energia")
    engine = ZonedTariffCalculationStrategy()
    engine.set_dynamic_price_resolver(lambda timestamp: 0.40)
    result = engine.calculate(_details(TariffTypeEnum.DYNAMIC, [(_at(FRIDAY, "10:00"), 10.0)]), [definition],
                              _context())

    settled = FinancialSettlement().settle(result, [{"2026-11": 0.5}])

    assert (settled.name, settled.billing_cycle_months) == ("Dynamiczna energia", 1)
    assert settled.deposit_applied == Decimal("0.50")
    assert settled.as_dict()["name"] == "Dynamiczna energia"


def test_net_metering_covers_zone_with_highest_real_rate_first():
    # strefa 2 droższa od strefy 1: 0,50 + 0,20 = 0,70 zł/kWh wobec 0,30 + 0,10 = 0,40 zł/kWh
    definition = _definition(TariffTypeEnum.G12, ["0.30", "0.50"], ["0.10", "0.20"])
    schedule = ZoneSchedule([definition])
    pv_details = PVDetails(
        pv_energy_cycles=[(CYCLE_START, [(_at(FRIDAY, "12:00"), 1.25)])],
        mode="net_metering",
        power_of_pv_kwp=5.0,
    )
    readings = [(_at(FRIDAY, "10:00"), 2.0), (_at(FRIDAY, "23:00"), 2.0)]

    balanced = PVBalancingEngine().balance_pv(_details(TariffTypeEnum.G12, readings, pv_details), schedule)

    assert PVBalancingEngine.zone_priority(schedule, CYCLE_START) == [1, 0]
    # nadwyżka 1,25 kWh × 0,8 = 1 kWh pokrywa najpierw droższą strefę 2: zostaje 2 kWh w strefie 1 i 1 kWh w strefie 2
    assert balanced.used_energy_cycles[0][1] == pytest.approx([2.0, 1.0])


def test_zone_priority_uses_capped_rates_of_definition_valid_at_cycle_start():
    first_half = _definition(TariffTypeEnum.G12, ["0.70", "0.45"], ["0.05", "0.20"],
                             valid=(date(2026, 1, 1), date(2026, 6, 30)), energy_price_cap_per_kwh=Decimal("0.50"))
    second_half = _definition(TariffTypeEnum.G12, ["0.70", "0.45"], ["0.05", "0.20"],
                              valid=(date(2026, 7, 1), date(2026, 12, 31)))
    schedule = ZoneSchedule([second_half, first_half])

    # do 30.06 strefa 1 = min(0,70; 0,50) + 0,05 = 0,55 < strefa 2 = 0,45 + 0,20 = 0,65: najpierw strefa 2
    assert PVBalancingEngine.zone_priority(schedule, datetime(2026, 5, 1)) == [1, 0]
    # od 1.07 bez ceny maksymalnej strefa 1 = 0,70 + 0,05 = 0,75 > 0,65: najpierw strefa 1
    assert PVBalancingEngine.zone_priority(schedule, datetime(2026, 7, 1)) == [0, 1]
    # okres zaczęty przed pierwszą definicją: stawki z pierwszego dnia, od którego je mamy
    assert PVBalancingEngine.zone_priority(schedule, datetime(2025, 12, 1)) == [1, 0]


def test_service_bills_dynamic_offer_monthly_when_profile_has_two_month_cycle():
    readings = [(_at(date(2026, 1, 1), "10:00"), 10.0), (_at(date(2026, 2, 28), "10:00"), 20.0)]
    definitions = [
        _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"], cycle_months=2),
        _definition(TariffTypeEnum.DYNAMIC, ["0.10"], ["0.20"], cycle_months=1, required_billing_cycle_months=1),
    ]
    service = _service(readings, definitions, [_period()], prices=_Prices("400"),
                       base_info={"billing_cycle": 2, "billing_period_start_date": "2026-01-01"})

    result = service.perform_tariff_calculations(None, None)

    g11, dynamic = result.tariff_calculations["G11"], result.dynamic_calculations["G11"]
    assert g11["billing_cycle_months"] == 2
    assert [cycle["cycle_start"] for cycle in g11["cycles"]] == ["2026-01-01T00:00:00"]
    assert dynamic["billing_cycle_months"] == 1
    assert [(cycle["cycle_start"], cycle["days_in_cycle"], cycle["active_energy_kwh"]) for cycle in dynamic["cycles"]] == [
        ("2026-01-01T00:00:00", 31, 10.0),
        ("2026-02-01T00:00:00", 28, 20.0),
    ]
    # RCE 400 zł/MWh + marża 0,10 zł/kWh: 10 × 0,50 = 5,00 zł w styczniu i 20 × 0,50 = 10,00 zł w lutym
    assert [cycle["active_energy_net"] for cycle in dynamic["cycles"]] == [5.0, 10.0]
    # okres z profilu się nie zmienia
    assert result.tariff_data.billing_cycle == 2


def test_profile_with_pv_gets_prosumer_margin_and_trade_fee():
    readings = [(_at(date(2026, 1, 1), "10:00"), 5.0), (_at(date(2026, 1, 31), "10:00"), 5.0)]
    offer = _definition(TariffTypeEnum.DYNAMIC, ["0.08"], ["0"], prosumer_margin_per_kwh=Decimal("0.12"),
                        trade_fee_monthly=Decimal("10"), prosumer_trade_fee_monthly=Decimal("15"), required_billing_cycle_months=1)

    def bill(pv_config):
        service = _service(readings, [offer], [_period()], tariff="dynamic", pv_config=pv_config, prices=_Prices("400"))
        return service.perform_tariff_calculations(None, None).tariff_calculation["cycles"][0]

    consumer = bill({"mode": "none"})
    prosumer = bill({"mode": "net_billing"})

    # 10 kWh × (0,40 + marża): 0,08 bez PV, 0,12 z PV; opłata handlowa 10 zł bez PV, 15 zł z PV
    assert (consumer["active_energy_net"], consumer["trade_fee_net"]) == (4.80, 10.00)
    assert (prosumer["active_energy_net"], prosumer["trade_fee_net"]) == (5.20, 15.00)


def test_file_starting_before_first_rate_day_is_clipped_with_warning():
    readings = [
        (_at(date(2025, 12, 30), "10:00"), 5.0),
        (_at(date(2026, 1, 1), "10:00"), 1.0),
        (_at(date(2026, 1, 5), "10:00"), 3.0),
    ]
    definition = _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"])

    result = _service(readings, [definition], [_period()], first_valid_from=date(2026, 1, 1)).perform_tariff_calculations(
        None, None
    )

    assert result.warnings == [
        "Plik zaczyna się 30.12.2025, a stawki taryfowe mamy od 01.01.2026. Dni przed 01.01.2026 nie liczymy — "
        "rachunek obejmuje 01.01.2026 – 05.01.2026."
    ]
    cycles = result.tariff_calculation["cycles"]
    assert [(cycle["cycle_start"], cycle["days_billed"], cycle["active_energy_kwh"]) for cycle in cycles] == [
        ("2026-01-01T00:00:00", 5, 4.0),
    ]
    # zużycie z pominiętych dni nie wchodzi też do progów opłaty mocowej
    assert (result.annual_consumption.data_start, result.annual_consumption.consumption_kwh) == (date(2026, 1, 1), 4.0)


def test_file_entirely_before_first_rate_day_is_rejected():
    readings = [(_at(date(2025, 12, 1), "10:00"), 1.0), (_at(date(2025, 12, 31), "10:00"), 1.0)]
    definition = _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"])

    with pytest.raises(HTTPException) as error:
        _service(readings, [definition], [_period()], first_valid_from=date(2026, 1, 1)).perform_tariff_calculations(
            None, None
        )

    assert error.value.status_code == 409
    assert error.value.detail == (
        "Rachunki u operatora PGE liczymy od 01.01.2026, a plik obejmuje tylko wcześniejsze dni "
        "(01.12.2025 – 31.12.2025)."
    )


def test_profile_billing_cycle_not_offered_by_operator_is_rejected():
    readings = [(_at(date(2026, 1, 1), "10:00"), 1.0)]
    definitions = [
        _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"], cycle_months=2),
        # okres oferty dynamicznej (1 mies.) nie jest okresem grup G do wyboru w profilu
        _definition(TariffTypeEnum.DYNAMIC, ["0.10"], ["0.30"], cycle_months=1, required_billing_cycle_months=1),
    ]

    with pytest.raises(HTTPException) as error:
        _service(readings, definitions, [_period()]).perform_tariff_calculations(None, None)

    assert error.value.status_code == 409
    assert error.value.detail == (
        "Operator PGE nie oferuje w grupach G okresu rozliczeniowego 1 mies. (dostępne: 2 mies.). "
        "Zmień okres w profilu."
    )


def test_offer_starting_after_file_start_gets_note_instead_of_bill():
    readings = [(_at(date(2026, 1, 1), "10:00"), 1.0), (_at(date(2026, 3, 31), "10:00"), 1.0)]
    definitions = [
        _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"]),
        _definition(TariffTypeEnum.DYNAMIC, ["0.10"], ["0.30"], name="Dynamiczna energia",
                    valid=(date(2026, 3, 1), date(2026, 12, 31)), required_billing_cycle_months=1),
    ]

    result = _service(readings, definitions, [_period()]).perform_tariff_calculations(None, None)

    assert result.tariff_notes == {
        "dynamic": "Dynamiczna energia: oferta dostępna od 01.03.2026, a plik zaczyna się 01.01.2026."
    }
    assert list(result.tariff_calculations) == ["G11"]
    assert result.tariff_calculation_errors is None


def test_unsupported_tariffs_are_listed_once_per_code():
    readings = [(_at(date(2026, 1, 1), "10:00"), 1.0)]
    reason = "Taryfa antysmogowa — jeszcze jej nie liczymy."
    unsupported = [
        SimpleNamespace(tariff_code="G12as", name="G12as", reason=reason),
        # ta sama taryfa z drugiego okresu cennika
        SimpleNamespace(tariff_code="G12AS", name="G12as", reason=reason),
    ]

    result = _service(readings, [_definition(TariffTypeEnum.G11, ["0.50"], ["0.30"])], [_period()],
                      unsupported=unsupported).perform_tariff_calculations(None, None)

    assert [item.model_dump() for item in result.unsupported_tariffs] == [
        {"code": "G12as", "name": "G12as", "reason": reason}
    ]


def test_file_across_rate_and_regulatory_changes_bills_every_component_of_every_cycle():
    """Plik 1.11.2025–31.05.2026, okresy dwumiesięczne od 1.11.2025.

    Cennik G12 zmienia się 1.01.2026 (inne stawki, cena maksymalna 0,50 zł/kWh tylko do 31.12.2025), opłaty
    regulacyjne 1.01.2026 i 1.02.2026 (jakościowa, OZE, progi mocowej), opłata przejściowa tylko w 2025 r.
    """
    tariff_2025 = _definition(
        TariffTypeEnum.G12, ["0.62", "0.45"], ["0.30", "0.10"], fixed="8", subscription="1.5", cycle_months=2,
        valid=(date(2025, 1, 1), date(2025, 12, 31)), energy_price_cap_per_kwh=Decimal("0.50"),
        trade_fee_monthly=Decimal("4"),
    )
    tariff_2026 = _definition(
        TariffTypeEnum.G12, ["0.55", "0.40"], ["0.32", "0.12"], fixed="9", subscription="2", cycle_months=2,
        valid=YEAR_2026, trade_fee_monthly=Decimal("5"),
    )
    periods = [
        _period(quality="0.03", renewable="0.004", cogeneration="0.003", excise="0.005", capacity=("3", "6", "12"),
                transition=("0.5", "1.5", "4"), valid=(date(2025, 1, 1), date(2025, 12, 31))),
        _period(quality="0.04", renewable="0.007", cogeneration="0.003", excise="0.005", capacity=("3.5", "7", "13"),
                transition=(), valid=(date(2026, 1, 1), date(2026, 1, 31))),
        _period(quality="0.05", renewable="0.007", cogeneration="0.003", excise="0.005", capacity=("4", "8", "14"),
                transition=(), valid=(date(2026, 2, 1), date(2026, 12, 31))),
    ]
    readings = [
        (_at(date(2025, 11, 1), "10:00"), 100.0),  # strefa 1, pierwszy dzień pliku
        (_at(date(2025, 12, 20), "23:00"), 50.0),  # strefa 2
        (_at(date(2026, 1, 15), "10:00"), 80.0),  # strefa 1
        (_at(date(2026, 1, 15), "02:00"), 40.0),  # strefa 2
        (_at(date(2026, 2, 10), "10:00"), 60.0),  # strefa 1
        (_at(date(2026, 2, 10), "14:00"), 30.0),  # strefa 2 (przerwa 13–15)
        (_at(date(2026, 3, 10), "10:00"), 70.0),  # strefa 1
        (_at(date(2026, 4, 10), "23:00"), 40.0),  # strefa 2
        (_at(date(2026, 5, 10), "10:00"), 50.0),  # strefa 1
        (_at(date(2026, 5, 31), "23:45"), 30.0),  # strefa 2, ostatni kwadrans pliku
    ]
    service = _service(readings, [tariff_2025, tariff_2026], periods, tariff="G12",
                       base_info={"billing_cycle": 2, "billing_period_start_date": "2025-11-01"})

    result = service.perform_tariff_calculations(None, None)

    # 550 kWh w 212 dniach = 946,9 kWh rocznie: we wszystkich okresach próg 500–1200 kWh (mocowa, przejściowa)
    assert result.annual_consumption.annual_kwh == pytest.approx(550 * 365 / 212, abs=0.001)
    bill = result.tariff_calculation
    assert bill["cycles"] == [
        # 1.11–31.12.2025 (61 z 61 dni): cennik 2025 i opłaty 2025; strefa 1: 100 kWh, strefa 2: 50 kWh
        {
            "cycle_start": "2025-11-01T00:00:00", "cycle_end": "2025-12-31T00:00:00",
            "days_billed": 61, "days_in_cycle": 61, "active_energy_kwh": 150.0,
            "active_energy_net": 72.50,  # 100 × min(0,62; 0,50) + 50 × 0,45 = 50,00 + 22,50
            "excise_net": 0.75,  # 150 × 0,005
            "variable_network_net": 35.00,  # 100 × 0,30 + 50 × 0,10
            "quality_net": 4.50,  # 150 × 0,03
            "renewable_net": 0.60,  # 150 × 0,004
            "cogeneration_net": 0.45,  # 150 × 0,003
            "fixed_network_net": 16.00,  # 8 × 2 mies.
            "subscription_net": 3.00,  # 1,5 × 2
            "capacity_net": 12.00,  # 6 × 2
            "transition_net": 3.00,  # 1,5 × 2 — opłata przejściowa jeszcze w 2025 r.
            "trade_fee_net": 8.00,  # 4 × 2
            "net_total": 155.80,
            "vat": 35.83,  # 155,80 × 0,23 = 35,834
            "gross_total": 191.63,  # 155,80 + 35,834 = 191,634
        },
        # 1.01–28.02.2026 (59 dni): cennik 2026 bez ceny maksymalnej; opłaty: styczeń (31 dni) i luty (28 dni)
        # styczeń: strefa 1: 80 kWh, strefa 2: 40 kWh; luty: strefa 1: 60 kWh, strefa 2: 30 kWh
        {
            "cycle_start": "2026-01-01T00:00:00", "cycle_end": "2026-02-28T00:00:00",
            "days_billed": 59, "days_in_cycle": 59, "active_energy_kwh": 210.0,
            "active_energy_net": 105.00,  # 140 × 0,55 + 70 × 0,40 = 77,00 + 28,00
            "excise_net": 1.05,  # 210 × 0,005
            "variable_network_net": 53.20,  # 140 × 0,32 + 70 × 0,12 = 44,80 + 8,40
            "quality_net": 9.30,  # 120 × 0,04 + 90 × 0,05 = 4,80 + 4,50
            "renewable_net": 1.47,  # 210 × 0,007
            "cogeneration_net": 0.63,  # 210 × 0,003
            "fixed_network_net": 18.00,  # 9 × 2 × 31/59 + 9 × 2 × 28/59
            "subscription_net": 4.00,  # 2 × 2
            "capacity_net": 14.95,  # 7 × 2 × 31/59 + 8 × 2 × 28/59 = 882/59 = 14,9492
            "transition_net": 0.00,  # od 2026 r. bez opłaty przejściowej
            "trade_fee_net": 10.00,  # 5 × 2
            "net_total": 217.60,  # 202,65 + 14,9492 = 217,5992
            "vat": 50.05,  # 217,5992 × 0,23 = 50,0478
            "gross_total": 267.65,  # 217,5992 + 50,0478 = 267,6470
        },
        # 1.03–30.04.2026 (61 dni): cennik 2026, opłaty od lutego; strefa 1: 70 kWh, strefa 2: 40 kWh
        {
            "cycle_start": "2026-03-01T00:00:00", "cycle_end": "2026-04-30T00:00:00",
            "days_billed": 61, "days_in_cycle": 61, "active_energy_kwh": 110.0,
            "active_energy_net": 54.50,  # 70 × 0,55 + 40 × 0,40 = 38,50 + 16,00
            "excise_net": 0.55,  # 110 × 0,005
            "variable_network_net": 27.20,  # 70 × 0,32 + 40 × 0,12 = 22,40 + 4,80
            "quality_net": 5.50,  # 110 × 0,05
            "renewable_net": 0.77,  # 110 × 0,007
            "cogeneration_net": 0.33,  # 110 × 0,003
            "fixed_network_net": 18.00,  # 9 × 2
            "subscription_net": 4.00,  # 2 × 2
            "capacity_net": 16.00,  # 8 × 2
            "transition_net": 0.00,
            "trade_fee_net": 10.00,  # 5 × 2
            "net_total": 136.85,
            "vat": 31.48,  # 136,85 × 0,23 = 31,4755
            "gross_total": 168.33,  # 136,85 + 31,4755 = 168,3255
        },
        # 1.05–30.06.2026, plik do 31.05 (31 z 61 dni): opłaty miesięczne × 2 × 31/61; strefa 1: 50, strefa 2: 30 kWh
        {
            "cycle_start": "2026-05-01T00:00:00", "cycle_end": "2026-06-30T00:00:00",
            "days_billed": 31, "days_in_cycle": 61, "active_energy_kwh": 80.0,
            "active_energy_net": 39.50,  # 50 × 0,55 + 30 × 0,40 = 27,50 + 12,00
            "excise_net": 0.40,  # 80 × 0,005
            "variable_network_net": 19.60,  # 50 × 0,32 + 30 × 0,12 = 16,00 + 3,60
            "quality_net": 4.00,  # 80 × 0,05
            "renewable_net": 0.56,  # 80 × 0,007
            "cogeneration_net": 0.24,  # 80 × 0,003
            "fixed_network_net": 9.15,  # 9 × 2 × 31/61 = 9,1475
            "subscription_net": 2.03,  # 2 × 2 × 31/61 = 2,0328
            "capacity_net": 8.13,  # 8 × 2 × 31/61 = 8,1311
            "transition_net": 0.00,
            "trade_fee_net": 5.08,  # 5 × 2 × 31/61 = 5,0820
            "net_total": 88.69,  # 64,30 + 24 × 62/61 = 64,30 + 24,3934 = 88,6934
            "vat": 20.40,  # 88,6934 × 0,23 = 20,3995
            "gross_total": 109.09,  # 88,6934 + 20,3995 = 109,0929
        },
    ]
    assert bill["billing_cycle_months"] == 2
    assert bill["gross_total"] == 736.70  # 191,63 + 267,65 + 168,33 + 109,09
    assert bill["payable_gross"] == 736.70
    assert bill["trade_fee_net"] == 33.08  # 8,00 + 10,00 + 10,00 + 5,08
    # (energia + akcyza) × 1,23 = (73,25 + 60,60 + 45,45 + 55,05 + 39,90) × 1,23 = 274,25 × 1,23 = 337,3275
    assert bill["active_energy_gross"] == 337.33


def test_service_bills_dynamic_offer_with_each_allowed_distribution_group():
    # 10:00 to strefa dzienna G12, 23:00 nocna.
    readings = [(_at(FRIDAY, "10:00"), 2.0), (_at(FRIDAY, "23:00"), 2.0)]
    definitions = [
        _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"]),
        _definition(TariffTypeEnum.G12, ["0.60", "0.40"], ["0.40", "0.05"]),
        _definition(TariffTypeEnum.DYNAMIC, ["0.10"], ["0.30"], required_billing_cycle_months=1),
        _definition(TariffTypeEnum.DYNAMIC, ["0.10", "0.10"], ["0.40", "0.05"], hours=HOURS[TariffTypeEnum.G12],
                    distribution_group=TariffTypeEnum.G12, required_billing_cycle_months=1),
    ]
    service = _service(readings, definitions, [_period()], prices=_Prices("400"), tariff="G12", dynamic_price=True)

    result = service.perform_tariff_calculations(None, None)

    assert set(result.tariff_calculations) == {"G11", "G12"}
    assert set(result.dynamic_calculations) == {"G11", "G12"}
    network = {group: sum(cycle["variable_network_net"] for cycle in calc["cycles"])
               for group, calc in result.dynamic_calculations.items()}
    # Ta sama cena energii, dystrybucja według grupy: G11 4 × 0,30, G12 2 × 0,40 + 2 × 0,05.
    assert network == {"G11": pytest.approx(1.20), "G12": pytest.approx(0.90)}
    energy = {group: sum(cycle["active_energy_net"] for cycle in calc["cycles"])
              for group, calc in result.dynamic_calculations.items()}
    assert energy["G11"] == energy["G12"] == pytest.approx(2.00)  # 4 kWh × (0,40 + 0,10)
    # Profil: G12 z ceną dynamiczną.
    assert result.tariff_calculation == result.dynamic_calculations["G12"]


def test_selected_only_bills_profile_tariff_for_given_readings():
    definitions = [
        _definition(TariffTypeEnum.G11, ["0.50"], ["0.30"]),
        _definition(TariffTypeEnum.G12, ["0.60", "0.40"], ["0.40", "0.05"]),
    ]
    service = _service([(_at(FRIDAY, "10:00"), 9.0)], definitions, [_period()], tariff="G12")
    readings = [SimpleNamespace(measured_at=_at(FRIDAY, "23:00"), energy_kwh=Decimal("2"), exported_kwh=Decimal("0"))]

    result = service.perform_tariff_calculations(None, None, readings, selected_only=True)

    assert set(result.tariff_calculations) == {"G12"}
    # Podane odczyty zastępują plik: 2 kWh w nocy po 0,40 + 0,05.
    assert result.tariff_calculation["cycles"][0]["active_energy_kwh"] == 2.0
    assert result.tariff_calculation["cycles"][0]["variable_network_net"] == pytest.approx(0.10)

