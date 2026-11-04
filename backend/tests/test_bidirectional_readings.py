from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.parsers import parse_energy_file
from app.schemas.other import TariffTypeEnum
from app.services.calculation_service import CalculationService
from app.services.new_calculations_service import CalculationsService
from calculations_seed import SCENARIOS


TEST_DATA = Path(__file__).resolve().parents[1] / "test_data"
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


def _seed_readings(scenario) -> list[tuple[datetime, float, float]]:
    """Odczyty tak, jak zapisuje je calculations_seed.py: wartość godzinowa po równo na kwadranse."""
    readings = []
    for timestamp_text, value in scenario["readings"]:
        end_time = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M")
        for minutes in (60, 45, 30, 15):
            readings.append((end_time - timedelta(minutes=minutes), max(value, 0) / 4, max(-value, 0) / 4))
    return sorted(readings)


def _uploaded_readings(file_name) -> list[tuple[datetime, float, float]]:
    with (TEST_DATA / file_name).open("rb") as handle:
        return CalculationService.quarter_hour_readings(parse_energy_file(handle))


def _g12_definition():
    rates = [(1, Decimal("0.86"), Decimal("0.34")), (2, Decimal("0.46"), Decimal("0.18"))]
    return SimpleNamespace(
        tariff_code=TariffTypeEnum.G12,
        number_of_zones=2,
        fixed_network_fee_1phase_monthly=Decimal("8.50"),
        fixed_network_fee_3phase_monthly=Decimal("16.50"),
        supplier_ure_rates=[SimpleNamespace(zone_index=zone, energy_price_per_kwh_net_pln=energy)
                            for zone, energy, _ in rates],
        variable_network_rates=[SimpleNamespace(zone_index=zone, rate_per_kwh_net_pln=network)
                                for zone, _, network in rates],
        subscription_fees=[SimpleNamespace(billing_cycle_months=1, monthly_fee_net_pln=Decimal("3.00"))],
    )


class _Repository:
    def __init__(self, **methods):
        for name, result in methods.items():
            setattr(self, name, lambda *args, _result=result, **kwargs: _result)


class _Prices:
    def get_prices_between(self, source, start_utc, end_utc):
        return {start_utc: Decimal("420")}

    def get_rcem_price(self, source, day):
        return Decimal("551.96")


def _calculate(scenario, readings):
    profile = SimpleNamespace(
        base_info=PROFILE,
        consumption_and_tariff={"tariff_type": "G12"},
        pv_config=scenario["pv_config"],
    )
    energy_file = SimpleNamespace(status="completed", STATUS_COMPLETED="completed")
    rows = [
        SimpleNamespace(measured_at=measured_at, energy_kwh=Decimal(str(used)), exported_kwh=Decimal(str(exported)))
        for measured_at, used, exported in readings
    ]
    service = CalculationsService(
        _Repository(get_profile=profile),
        _Repository(get_by_id_for_user=energy_file),
        _Repository(list_for_file=rows),
        _Repository(list_for_calculation=[_g12_definition()]),
        market_price_repository=_Prices(),
    )
    return service.perform_tariff_calculations(user_id=None, file_id=None)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[scenario["file_name"] for scenario in SCENARIOS])
def test_uploaded_scenario_file_has_the_same_readings_as_seed(scenario):
    uploaded, seeded = _uploaded_readings(scenario["file_name"]), _seed_readings(scenario)

    assert [time for time, _, _ in uploaded] == [time for time, _, _ in seeded]
    assert [value for _, *values in uploaded for value in values] == pytest.approx(
        [value for _, *values in seeded for value in values]
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[scenario["file_name"] for scenario in SCENARIOS])
def test_uploaded_scenario_file_gives_the_same_calculation_as_seed(scenario):
    uploaded = _calculate(scenario, _uploaded_readings(scenario["file_name"]))
    seeded = _calculate(scenario, _seed_readings(scenario))

    assert uploaded.tariff_calculation_errors is None
    assert uploaded.tariff_calculations == seeded.tariff_calculations


@pytest.mark.parametrize("file_name", ["scenario_net_metering.csv", "scenario_net_billing.csv"])
def test_uploaded_pv_file_has_production_for_calculation(file_name):
    readings = _uploaded_readings(file_name)

    _, produced = CalculationsService._cycles_from_readings(
        [SimpleNamespace(measured_at=time, energy_kwh=used, exported_kwh=exported) for time, used, exported in readings],
        SimpleNamespace(billing_period_start_date=datetime(2026, 1, 1).date(), billing_cycle=SimpleNamespace(value=1)),
    )

    assert sum(kwh for _, records in produced for _, kwh in records) > 0


def test_pv_reduces_bill_compared_to_the_same_consumption_without_export():
    scenario = next(item for item in SCENARIOS if item["pv_config"]["mode"] == "net_metering")
    readings = _uploaded_readings(scenario["file_name"])
    without_export = [(time, used, 0.0) for time, used, _ in readings]

    with_pv = _calculate(scenario, readings).tariff_calculation["gross_total"]
    without_pv = _calculate({**scenario, "pv_config": {"mode": "none"}}, without_export).tariff_calculation["gross_total"]

    assert with_pv < without_pv


def test_export_without_pv_in_profile_is_ignored_with_warning():
    scenario = next(item for item in SCENARIOS if item["pv_config"]["mode"] == "net_metering")
    readings = _uploaded_readings(scenario["file_name"])
    without_pv = {**scenario, "pv_config": {"mode": "none"}}

    result = _calculate(without_pv, readings)
    expected = _calculate(without_pv, [(time, used, 0.0) for time, used, _ in readings])

    assert result.pv_details is None
    assert result.tariff_calculations == expected.tariff_calculations
    assert result.warnings == [
        "Plik zawiera 5,60 kWh energii oddanej do sieci, ale profil nie ma instalacji PV. "
        "Kalkulacja pomija oddanie energii; uzupełnij instalację PV w profilu, żeby rozliczyć ją "
        "w net-meteringu albo net-billingu."
    ]
    assert expected.warnings is None
