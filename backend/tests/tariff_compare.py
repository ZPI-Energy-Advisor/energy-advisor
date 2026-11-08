"""Porównanie plików cennika z wierszami w bazie (po `load_data_set`): wszystkie wartości, nie tylko liczby wierszy."""

from sqlalchemy.orm import Session

from app.models.NewModels import RegulatoryPeriod, TariffDefinition, UnsupportedTariff
from app.tariff_data.build import build_definitions, build_regulatory, build_unsupported
from app.tariff_data.files import TariffDataSet


def _diff(errors: list[str], label: str, actual, expected) -> None:
    if actual != expected:
        errors.append(f"{label}: w bazie {actual!r}, w pliku {expected!r}")


def _hours(rows) -> list[tuple]:
    return [(h.zone_index, h.day_type, h.season_from, h.season_to, h.start_minute, h.end_minute) for h in rows]


def _definition_errors(row: TariffDefinition, spec) -> list[str]:
    errors: list[str] = []
    label = f"{spec.operator.value} {spec.tariff_code.value}/{spec.distribution_group.value} {spec.valid_from}"
    for field, actual, expected in (
        ("name", row.name, spec.name),
        ("number_of_zones", row.number_of_zones, len(spec.zones)),
        ("valid_to", row.valid_to, spec.valid_to),
        ("distribution_valid_from", row.distribution_valid_from, spec.distribution_valid_from),
        ("distribution_valid_to", row.distribution_valid_to, spec.distribution_valid_to),
        ("distribution_source", row.distribution_source, spec.distribution_source),
        ("energy_valid_from", row.energy_valid_from, spec.energy_valid_from),
        ("energy_valid_to", row.energy_valid_to, spec.energy_valid_to),
        ("energy_source", row.energy_source, spec.energy_source),
        ("energy_includes_excise", row.energy_includes_excise, spec.includes_excise),
        ("energy_price_cap_per_kwh", row.energy_price_cap_per_kwh, spec.price_cap),
        ("prosumer_margin_per_kwh", row.prosumer_margin_per_kwh, spec.prosumer_margin),
        ("market_price_floor_mwh", row.market_price_floor_mwh, spec.market_price_floor),
        ("market_price_cap_mwh", row.market_price_cap_mwh, spec.market_price_cap),
        ("required_billing_cycle_months", row.required_billing_cycle_months, spec.required_billing_cycle_months),
        ("fixed_1phase", row.fixed_network_fee_1phase_monthly, spec.fixed_1phase),
        ("fixed_3phase", row.fixed_network_fee_3phase_monthly, spec.fixed_3phase),
    ):
        _diff(errors, f"{label}: {field}", actual, expected)
    _diff(
        errors,
        f"{label}: stawki sieciowe i nazwy stref",
        {rate.zone_index: (rate.zone_name, rate.rate_per_kwh_net_pln) for rate in row.variable_network_rates},
        {zone.index: (zone.name, zone.network_rate) for zone in spec.zones},
    )
    _diff(
        errors,
        f"{label}: ceny energii",
        {rate.zone_index: rate.energy_price_per_kwh_net_pln for rate in row.supplier_ure_rates},
        {zone.index: zone.energy_price for zone in spec.zones},
    )
    _diff(errors, f"{label}: sprzedawca", {rate.supplier_name for rate in row.supplier_ure_rates}, {spec.seller})
    _diff(
        errors,
        f"{label}: abonament",
        {fee.billing_cycle_months: fee.monthly_fee_net_pln for fee in row.subscription_fees},
        dict(spec.subscription),
    )
    _diff(errors, f"{label}: opłata handlowa", row.trade_fee_monthly, spec.trade_fee)
    _diff(errors, f"{label}: opłata handlowa prosumenta", row.prosumer_trade_fee_monthly, spec.prosumer_trade_fee)
    actual_hours, expected_hours = _hours(row.zone_hours), _hours(spec.zone_hours)
    _diff(errors, f"{label}: godziny stref", set(actual_hours), set(expected_hours))
    _diff(errors, f"{label}: liczba przedziałów godzin (duplikaty)", len(actual_hours), len(expected_hours))
    return errors


def _bands(thresholds) -> list[tuple]:
    return sorted(
        ((t.min_kwh_annual, t.max_kwh_annual, t.monthly_fee_net_pln) for t in thresholds),
        key=lambda band: band[0],
    )


def _regulatory_errors(row: RegulatoryPeriod, spec) -> list[str]:
    errors: list[str] = []
    label = f"opłaty regulacyjne {spec.valid_from}"
    for field, actual, expected in (
        ("valid_to", row.valid_to, spec.valid_to),
        ("quality_fee_per_kwh", row.quality_fee_per_kwh, spec.values["quality_fee_per_kwh"]),
        ("renewable_energy_fee_per_kwh", row.renewable_energy_fee_per_kwh, spec.values["renewable_fee_per_kwh"]),
        ("cogeneration_fee_per_kwh", row.cogeneration_fee_per_kwh, spec.values["cogeneration_fee_per_kwh"]),
        ("excise_per_kwh", row.excise_per_kwh, spec.values["excise_per_kwh"]),
        ("vat_rate", row.vat_rate, spec.values["vat_rate"]),
        ("source", row.source, spec.source),
    ):
        _diff(errors, f"{label}: {field}", actual, expected)
    _diff(
        errors,
        f"{label}: progi opłaty mocowej",
        _bands(row.capacity_thresholds),
        [(band.min_kwh, band.max_kwh, band.fee) for band in spec.capacity_bands],
    )
    _diff(
        errors,
        f"{label}: progi opłaty przejściowej",
        _bands(row.transition_thresholds),
        [(band.min_kwh, band.max_kwh, band.fee) for band in spec.transition_bands],
    )
    return errors


def database_mismatches(session: Session, data_set: TariffDataSet) -> list[str]:
    """Różnice między plikami a bazą (pusta lista = baza w zakresach plików jest dokładną kopią plików)."""
    errors: list[str] = []
    for data in data_set.operator_files:
        rows = (
            session.query(TariffDefinition)
            .filter(
                TariffDefinition.osd_operator == data.operator,
                TariffDefinition.valid_from <= data.covers_to,
                TariffDefinition.valid_to >= data.covers_from,
            )
            .all()
        )
        by_key = {(row.tariff_code, row.distribution_group, row.valid_from): row for row in rows}
        specs = build_definitions(data)
        _diff(errors, f"{data.operator.value}: liczba definicji", len(rows), len(specs))
        for spec in specs:
            row = by_key.get((spec.tariff_code, spec.distribution_group, spec.valid_from))
            if row is None:
                errors.append(f"{spec.operator.value} {spec.tariff_code.value} {spec.valid_from}: brak w bazie")
            else:
                errors.extend(_definition_errors(row, spec))

        unsupported_rows = (
            session.query(UnsupportedTariff)
            .filter(
                UnsupportedTariff.osd_operator == data.operator,
                UnsupportedTariff.valid_from <= data.covers_to,
                UnsupportedTariff.valid_to >= data.covers_from,
            )
            .all()
        )
        unsupported_specs = build_unsupported(data)
        _diff(errors, f"{data.operator.value}: liczba taryf nieliczonych", len(unsupported_rows), len(unsupported_specs))
        unsupported_by_key = {(row.tariff_code, row.valid_from): row for row in unsupported_rows}
        for spec in unsupported_specs:
            row = unsupported_by_key.get((spec.code, spec.valid_from))
            label = f"{spec.operator.value} nieliczona {spec.code} {spec.valid_from}"
            if row is None:
                errors.append(f"{label}: brak w bazie")
                continue
            for field, actual, expected in (
                ("name", row.name, spec.name),
                ("reason", row.reason, spec.reason),
                ("valid_to", row.valid_to, spec.valid_to),
                ("source", row.source, spec.source),
            ):
                _diff(errors, f"{label}: {field}", actual, expected)

    for data in data_set.regulatory_files:
        rows = (
            session.query(RegulatoryPeriod)
            .filter(RegulatoryPeriod.valid_from <= data.covers_to, RegulatoryPeriod.valid_to >= data.covers_from)
            .all()
        )
        specs = build_regulatory(data)
        _diff(errors, f"{data.path.name} {data.year}: liczba okresów regulacyjnych", len(rows), len(specs))
        by_start = {row.valid_from: row for row in rows}
        for spec in specs:
            row = by_start.get(spec.valid_from)
            if row is None:
                errors.append(f"opłaty regulacyjne {spec.valid_from}: brak w bazie")
            else:
                errors.extend(_regulatory_errors(row, spec))
    return errors
