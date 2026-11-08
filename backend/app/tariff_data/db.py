"""Ładowanie plików cennika do bazy.

Plik zastępuje dane w swoim zakresie dat (`covers`): usuwa definicje operatora, taryfy nieliczone albo okresy
regulacyjne leżące w całości w zakresie i wstawia nowe. Wpis leżący częściowo poza zakresem pliku oznacza, że
plik nie odpowiada za jego wszystkie dni — wtedy ładowanie jest przerywane, nic nie jest usuwane. Całość
wykonuje się w transakcji wywołującego (skrypt robi jeden commit na końcu).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.NewModels import (
    CapacityFeeThreshold,
    OsdSubscriptionFee,
    OsdVariableNetworkRate,
    RegulatoryPeriod,
    SupplierUreRate,
    TariffDefinition,
    TariffZoneHour,
    TransitionFeeThreshold,
    UnsupportedTariff,
)
from app.tariff_data.build import (
    DefinitionSpec,
    RegulatorySpec,
    UnsupportedSpec,
    build_definitions,
    build_regulatory,
    build_unsupported,
)
from app.tariff_data.files import TariffDataError, TariffDataSet


@dataclass
class LoadSummary:
    file: str
    removed: int
    inserted: int


def _outside(rows, first, last) -> list:
    return [row for row in rows if row.valid_from < first or row.valid_to > last]


def _describe(row) -> str:
    code = getattr(row, "tariff_code", None)
    code = getattr(code, "value", code)
    label = f"{code} " if code else ""
    return f"{label}{row.valid_from.isoformat()} – {row.valid_to.isoformat()}"


def _definition(spec: DefinitionSpec) -> TariffDefinition:
    return TariffDefinition(
        osd_operator=spec.operator,
        tariff_code=spec.tariff_code,
        distribution_group=spec.distribution_group,
        name=spec.name,
        number_of_zones=len(spec.zones),
        valid_from=spec.valid_from,
        valid_to=spec.valid_to,
        distribution_valid_from=spec.distribution_valid_from,
        distribution_valid_to=spec.distribution_valid_to,
        distribution_source=spec.distribution_source,
        energy_valid_from=spec.energy_valid_from,
        energy_valid_to=spec.energy_valid_to,
        energy_source=spec.energy_source,
        energy_includes_excise=spec.includes_excise,
        energy_price_cap_per_kwh=spec.price_cap,
        prosumer_margin_per_kwh=spec.prosumer_margin,
        market_price_floor_mwh=spec.market_price_floor,
        market_price_cap_mwh=spec.market_price_cap,
        required_billing_cycle_months=spec.required_billing_cycle_months,
        fixed_network_fee_1phase_monthly=spec.fixed_1phase,
        fixed_network_fee_3phase_monthly=spec.fixed_3phase,
        variable_network_rates=[
            OsdVariableNetworkRate(zone_index=zone.index, zone_name=zone.name, rate_per_kwh_net_pln=zone.network_rate)
            for zone in spec.zones
        ],
        supplier_ure_rates=[
            SupplierUreRate(
                supplier_name=spec.seller, zone_index=zone.index, energy_price_per_kwh_net_pln=zone.energy_price
            )
            for zone in spec.zones
        ],
        subscription_fees=[
            OsdSubscriptionFee(billing_cycle_months=months, monthly_fee_net_pln=fee)
            for months, fee in sorted(spec.subscription.items())
        ],
        trade_fee_monthly=spec.trade_fee,
        prosumer_trade_fee_monthly=spec.prosumer_trade_fee,
        zone_hours=[
            TariffZoneHour(
                zone_index=hour.zone_index,
                day_type=hour.day_type,
                season_from=hour.season_from,
                season_to=hour.season_to,
                start_minute=hour.start_minute,
                end_minute=hour.end_minute,
            )
            for hour in spec.zone_hours
        ],
    )


def _unsupported(spec: UnsupportedSpec) -> UnsupportedTariff:
    return UnsupportedTariff(
        osd_operator=spec.operator,
        tariff_code=spec.code,
        name=spec.name,
        reason=spec.reason,
        valid_from=spec.valid_from,
        valid_to=spec.valid_to,
        source=spec.source,
    )


def _regulatory(spec: RegulatorySpec) -> RegulatoryPeriod:
    return RegulatoryPeriod(
        valid_from=spec.valid_from,
        valid_to=spec.valid_to,
        quality_fee_per_kwh=spec.values["quality_fee_per_kwh"],
        renewable_energy_fee_per_kwh=spec.values["renewable_fee_per_kwh"],
        cogeneration_fee_per_kwh=spec.values["cogeneration_fee_per_kwh"],
        excise_per_kwh=spec.values["excise_per_kwh"],
        vat_rate=spec.values["vat_rate"],
        source=spec.source,
        capacity_thresholds=[
            CapacityFeeThreshold(min_kwh_annual=band.min_kwh, max_kwh_annual=band.max_kwh, monthly_fee_net_pln=band.fee)
            for band in spec.capacity_bands
        ],
        transition_thresholds=[
            TransitionFeeThreshold(
                min_kwh_annual=band.min_kwh, max_kwh_annual=band.max_kwh, monthly_fee_net_pln=band.fee
            )
            for band in spec.transition_bands
        ],
    )


def _existing(session: Session, model, first, last, **filters) -> list:
    query = session.query(model).filter(model.valid_from <= last, model.valid_to >= first)
    for name, value in filters.items():
        query = query.filter(getattr(model, name) == value)
    return query.all()


def load_data_set(session: Session, data_set: TariffDataSet) -> list[LoadSummary]:
    """Zastępuje dane z zakresów plików; rzuca TariffDataError (bez zmian w bazie po rollbacku wywołującego)."""
    errors: list[str] = []
    plans = []
    for data in data_set.regulatory_files:
        existing = _existing(session, RegulatoryPeriod, data.covers_from, data.covers_to)
        outside = _outside(existing, data.covers_from, data.covers_to)
        errors.extend(
            f"{data.path.name}: okres opłat regulacyjnych {_describe(row)} w bazie wychodzi poza zakres pliku "
            f"{data.covers_from.isoformat()} – {data.covers_to.isoformat()}; nie usuwam danych spoza zakresu pliku."
            for row in outside
        )
        plans.append((data, existing, [_regulatory(spec) for spec in build_regulatory(data)]))
    for data in data_set.operator_files:
        existing = _existing(session, TariffDefinition, data.covers_from, data.covers_to, osd_operator=data.operator)
        existing += _existing(session, UnsupportedTariff, data.covers_from, data.covers_to, osd_operator=data.operator)
        outside = _outside(existing, data.covers_from, data.covers_to)
        errors.extend(
            f"{data.path.parent.name}/{data.path.name}: wpis {data.operator.value} {_describe(row)} w bazie wychodzi "
            f"poza zakres pliku {data.covers_from.isoformat()} – {data.covers_to.isoformat()}; "
            "nie usuwam danych spoza zakresu pliku."
            for row in outside
        )
        new_rows = [_definition(spec) for spec in build_definitions(data)]
        new_rows += [_unsupported(spec) for spec in build_unsupported(data)]
        plans.append((data, existing, new_rows))
    if errors:
        raise TariffDataError(errors)

    summaries = []
    for data, existing, new_rows in plans:
        for row in existing:
            session.delete(row)
        session.flush()
        session.add_all(new_rows)
        session.flush()
        summaries.append(
            LoadSummary(file=f"{data.path.parent.name}/{data.path.name}", removed=len(existing), inserted=len(new_rows))
        )
    return summaries
