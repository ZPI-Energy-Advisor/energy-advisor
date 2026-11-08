"""Odczyt i budowa definicji z plików cennika: zmyślony zestaw z 2030 roku i kompletność prawdziwych danych."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.schemas.other import DistributionOperatorEnum, TariffTypeEnum
from app.tariff_data.build import (
    build_definitions,
    build_regulatory,
    build_unsupported,
    completeness_errors,
    coverage,
)
from app.tariff_data.files import days_between, read_data_set

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tariffs" / "valid" / "2030"
DATA_DIR = BACKEND_DIR / "data" / "tariffs"

T = TariffTypeEnum
OPERATORS = DistributionOperatorEnum


@pytest.fixture(scope="module")
def fixture_set():
    return read_data_set([FIXTURE_DIR])


@pytest.fixture(scope="module")
def fixture_definitions(fixture_set):
    assert len(fixture_set.operator_files) == 1
    return build_definitions(fixture_set.operator_files[0])


def _by_code(definitions, code):
    return [spec for spec in definitions if spec.tariff_code == code]


# ---------------------------------------------------------------- zmyślony zestaw 2030


def test_fixture_parses_into_one_operator_and_one_regulatory_file(fixture_set):
    assert [data.operator for data in fixture_set.operator_files] == [OPERATORS.PGE]
    assert len(fixture_set.regulatory_files) == 1
    assert fixture_set.operator_files[0].covers_from == date(2030, 1, 1)
    assert fixture_set.operator_files[0].covers_to == date(2030, 12, 31)


def test_fixture_source_can_be_a_description(fixture_definitions):
    middle = _by_code(fixture_definitions, T.G11)[1]
    assert "abonament" in middle.distribution_source


@pytest.mark.parametrize("code", [T.G11, T.G12, T.G12W])
def test_fixture_splits_tariffs_at_distribution_and_energy_changes(fixture_definitions, code):
    periods = [(spec.valid_from, spec.valid_to) for spec in _by_code(fixture_definitions, code)]
    assert periods == [
        (date(2030, 1, 1), date(2030, 6, 30)),
        (date(2030, 7, 1), date(2030, 9, 30)),
        (date(2030, 10, 1), date(2030, 12, 31)),
    ]


def test_fixture_dynamic_offer_starts_in_march_and_splits_with_distribution(fixture_definitions):
    dynamic = [spec for spec in _by_code(fixture_definitions, T.DYNAMIC) if spec.distribution_group == T.G11]
    assert [(spec.valid_from, spec.valid_to) for spec in dynamic] == [
        (date(2030, 3, 1), date(2030, 6, 30)),
        (date(2030, 7, 1), date(2030, 12, 31)),
    ]
    first = dynamic[0]
    assert first.name == "Oferta dynamiczna testowa"
    assert first.seller == "Sprzedawca testowy S.A."
    assert first.required_billing_cycle_months == 1
    assert first.prosumer_margin == Decimal("0.1100")
    assert first.market_price_floor == Decimal("0")
    assert first.market_price_cap == Decimal("2000")
    assert (first.trade_fee, first.prosumer_trade_fee) == (Decimal("20.00"), Decimal("25.00"))
    # Strefa 1 oferty: stawka sieciowa taryfy G11, „cena energii” to marża.
    assert [(zone.network_rate, zone.energy_price) for zone in first.zones] == [(Decimal("0.3000"), Decimal("0.0800"))]
    assert dynamic[1].zones[0].network_rate == Decimal("0.3200")
    # Ta sama oferta z dystrybucją G12: strefy i stawki G12, marża w każdej strefie.
    g12 = [spec for spec in _by_code(fixture_definitions, T.DYNAMIC) if spec.distribution_group == T.G12]
    assert [(spec.valid_from, spec.valid_to) for spec in g12] == [(spec.valid_from, spec.valid_to) for spec in dynamic]
    assert len(g12[0].zones) == 2 and {zone.energy_price for zone in g12[0].zones} == {Decimal("0.0800")}


def test_fixture_definition_keeps_both_parts_with_own_periods_and_sources(fixture_definitions):
    middle = _by_code(fixture_definitions, T.G11)[1]
    assert (middle.distribution_valid_from, middle.distribution_valid_to) == (date(2030, 7, 1), date(2030, 12, 31))
    assert (middle.energy_valid_from, middle.energy_valid_to) == (date(2030, 1, 1), date(2030, 9, 30))
    assert "Zmyślona taryfa OSD 2030" in middle.distribution_source
    assert "Zmyślona taryfa sprzedawcy 2030" in middle.energy_source
    assert middle.price_cap == Decimal("0.5000")
    assert middle.includes_excise is False


def test_fixture_trade_fee_only_in_last_energy_entry(fixture_definitions):
    g11 = _by_code(fixture_definitions, T.G11)
    assert g11[0].trade_fee is None
    assert g11[2].trade_fee == Decimal("2.00")
    assert g11[2].price_cap is None


def test_fixture_g12_zone_values_and_hours(fixture_definitions):
    first = _by_code(fixture_definitions, T.G12)[0]
    assert [(zone.index, zone.name, zone.network_rate, zone.energy_price) for zone in first.zones] == [
        (1, "dzienna", Decimal("0.4000"), Decimal("0.7000")),
        (2, "nocna", Decimal("0.1000"), Decimal("0.4000")),
    ]
    assert first.fixed_1phase == Decimal("8.00")
    assert first.fixed_3phase == Decimal("14.00")
    assert first.subscription == {1: Decimal("4.00"), 2: Decimal("2.00"), 6: Decimal("1.00")}
    # G12: 2 sezony × 3 rodzaje dnia × (2 + 3 przedziały)
    assert len(first.zone_hours) == 2 * 3 * (2 + 3)
    summer_night = {
        (hour.start_minute, hour.end_minute)
        for hour in first.zone_hours
        if hour.zone_index == 2 and hour.day_type == "workday" and hour.season_from == "04-01"
    }
    assert summer_night == {(0, 360), (900, 1020), (1320, 1440)}


def test_fixture_g12w_weekend_is_one_zone_all_day(fixture_definitions):
    first = _by_code(fixture_definitions, T.G12W)[0]
    weekend = {
        (hour.zone_index, hour.day_type, hour.start_minute, hour.end_minute)
        for hour in first.zone_hours
        if hour.day_type != "workday"
    }
    assert weekend == {(2, "saturday", 0, 1440), (2, "sunday_holiday", 0, 1440)}


def test_fixture_unsupported_tariff(fixture_set):
    unsupported = build_unsupported(fixture_set.operator_files[0])
    assert [(spec.code, spec.name, spec.valid_from, spec.valid_to) for spec in unsupported] == [
        ("G12as", "Taryfa antysmogowa", date(2030, 1, 1), date(2030, 12, 31))
    ]
    assert "dane testowe" in unsupported[0].reason
    assert "Zmyślona taryfa OSD 2030" in unsupported[0].source


def test_fixture_regulatory_specs(fixture_set):
    specs = build_regulatory(fixture_set.regulatory_files[0])
    assert [(spec.valid_from, spec.valid_to) for spec in specs] == [
        (date(2030, 1, 1), date(2030, 6, 30)),
        (date(2030, 7, 1), date(2030, 12, 31)),
    ]
    first, second = specs
    assert first.values == {
        "quality_fee_per_kwh": Decimal("0.0300"),
        "renewable_fee_per_kwh": Decimal("0.0040"),
        "cogeneration_fee_per_kwh": Decimal("0.0030"),
        "excise_per_kwh": Decimal("0.0050"),
        "vat_rate": Decimal("0.23"),
    }
    assert second.values["quality_fee_per_kwh"] == Decimal("0.0310")
    assert [(band.min_kwh, band.max_kwh, band.fee) for band in first.transition_bands] == [
        (Decimal("0"), Decimal("500"), Decimal("0.02")),
        (Decimal("500"), Decimal("1200"), Decimal("0.10")),
        (Decimal("1200"), None, Decimal("0.33")),
    ]
    assert second.transition_bands == []
    assert [band.fee for band in second.capacity_bands] == [
        Decimal("3.00"), Decimal("7.00"), Decimal("12.00"), Decimal("17.00")
    ]
    assert "Zmyślone informacje URE 2030" in first.source


def test_fixture_coverage_has_every_day_of_year_per_computed_tariff(fixture_set):
    covered = coverage(fixture_set)[OPERATORS.PGE]
    year = days_between(date(2030, 1, 1), date(2030, 12, 31))
    assert covered[T.G11] == year
    assert covered[T.G12] == year
    assert covered[T.G12W] == year
    assert covered[T.DYNAMIC] == days_between(date(2030, 3, 1), date(2030, 12, 31))


def test_fixture_completeness_errors_name_missing_days(fixture_set):
    assert completeness_errors(fixture_set, date(2030, 1, 1), date(2030, 12, 31)) == []
    errors = completeness_errors(fixture_set, date(2029, 12, 1), date(2031, 1, 31))
    assert any("PGE G11" in error and "2031" in error for error in errors)
    assert any(error.startswith("Opłaty regulacyjne: brak") for error in errors)


# ---------------------------------------------------------------- prawdziwe dane


@pytest.fixture(scope="module")
def real_set():
    return read_data_set([DATA_DIR])


EXPECTED_TARIFFS = {
    OPERATORS.PGE: {T.G11, T.G12, T.G12W, T.G12N, T.DYNAMIC},
    OPERATORS.TAURON: {T.G11, T.G12, T.G12W, T.G13, T.DYNAMIC},
    OPERATORS.ENEA: {T.G11, T.G12, T.G12W, T.DYNAMIC},
    OPERATORS.ENERGA: {T.G11, T.G12, T.G12W, T.G12R, T.DYNAMIC},
    OPERATORS.STOEN: {T.G11, T.G12, T.G12W, T.DYNAMIC},
}


def test_real_data_is_complete_for_the_supported_period(real_set):
    assert completeness_errors(real_set, date(2024, 8, 24), date(2026, 12, 31)) == []


def test_real_data_computes_expected_tariffs_per_operator(real_set):
    covered = coverage(real_set)
    assert set(covered) == set(EXPECTED_TARIFFS)
    for operator, expected in EXPECTED_TARIFFS.items():
        assert set(covered[operator]) == expected, operator.value


def test_real_data_non_dynamic_tariffs_start_on_first_day_of_data(real_set):
    problems = []
    for operator, codes in coverage(real_set).items():
        for code, days in codes.items():
            if code != T.DYNAMIC and days[0] != date(2024, 8, 24):
                problems.append(f"{operator.value} {code.value} zaczyna się {days[0]}")
    assert problems == []


def test_real_data_definitions_have_sources(real_set):
    problems = []
    for data in real_set.operator_files:
        for spec in build_definitions(data):
            label = f"{spec.operator.value} {spec.tariff_code.value} {spec.valid_from}"
            if not spec.distribution_source.strip() or not spec.energy_source.strip():
                problems.append(f"{label}: puste źródło")
        for unsupported in build_unsupported(data):
            if not unsupported.source.strip() or not unsupported.reason.strip():
                problems.append(f"{data.operator.value} nieliczona {unsupported.code}: brak źródła albo powodu")
    for data in real_set.regulatory_files:
        for period in build_regulatory(data):
            if not period.source.strip():
                problems.append(f"opłaty regulacyjne {period.valid_from}: puste źródło")
    assert problems == []
