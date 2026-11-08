"""Budowa definicji taryf i okresów regulacyjnych z wczytanych plików (bez bazy).

Definicja = taryfa × część wspólna okresu wpisu OSD i wpisu sprzedawcy. Oferta dynamiczna ma osobną definicję dla
każdej grupy z `distribution_tariffs` (dystrybucja, strefy i abonament tej grupy). Zapamiętuje okresy i źródła
obu części osobno.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.schemas.other import DistributionOperatorEnum, TariffTypeEnum
from app.tariff_data.files import (
    DAY_TYPES,
    REGULATORY_VALUES,
    DistributionEntry,
    DistributionTariff,
    FeeBand,
    OperatorFile,
    RegulatoryFile,
    Source,
    TariffDataSet,
    days_between,
)


@dataclass(frozen=True)
class ZoneSpec:
    index: int
    name: str
    network_rate: Decimal
    energy_price: Decimal


@dataclass(frozen=True)
class ZoneHourSpec:
    zone_index: int
    day_type: str
    season_from: str
    season_to: str
    start_minute: int
    end_minute: int


@dataclass
class DefinitionSpec:
    operator: DistributionOperatorEnum
    tariff_code: TariffTypeEnum
    # Grupa, według której liczona jest dystrybucja (dla taryf strefowych = tariff_code).
    distribution_group: TariffTypeEnum
    name: str | None
    valid_from: date
    valid_to: date
    zones: list[ZoneSpec]
    fixed_1phase: Decimal
    fixed_3phase: Decimal
    subscription: dict[int, Decimal]
    trade_fee: Decimal | None
    prosumer_trade_fee: Decimal | None
    zone_hours: list[ZoneHourSpec]
    distribution_valid_from: date
    distribution_valid_to: date
    distribution_source: str
    energy_valid_from: date
    energy_valid_to: date
    energy_source: str
    seller: str
    includes_excise: bool
    price_cap: Decimal | None = None
    prosumer_margin: Decimal | None = None
    market_price_floor: Decimal | None = None
    market_price_cap: Decimal | None = None
    required_billing_cycle_months: int | None = None


@dataclass
class UnsupportedSpec:
    operator: DistributionOperatorEnum
    code: str
    name: str
    reason: str
    valid_from: date
    valid_to: date
    source: str


@dataclass
class RegulatorySpec:
    valid_from: date
    valid_to: date
    values: dict[str, Decimal]
    capacity_bands: list[FeeBand]
    transition_bands: list[FeeBand]
    source: str


@dataclass
class _Sources:
    """Opis źródeł części definicji."""

    documents: dict
    parts: list[str] = field(default_factory=list)

    def add(self, label: str, source: Source | None) -> None:
        if source is None:
            return
        self.parts.append(f"{label}: {source.describe(self.documents)}")

    def text(self) -> str:
        return "; ".join(self.parts)


def _money(value: Decimal) -> str:
    return f"{value:.4f}".replace(".", ",")


def _zone_hours(tariff: DistributionTariff) -> list[ZoneHourSpec]:
    return [
        ZoneHourSpec(
            zone_index=rule.zone,
            day_type=day_type,
            season_from=rule.season[0],
            season_to=rule.season[1],
            start_minute=start,
            end_minute=end,
        )
        for rule in tariff.hours
        for day_type in DAY_TYPES
        if day_type in rule.day_types
        for start, end in rule.intervals
    ]


def _distribution_sources(data: OperatorFile, entry: DistributionEntry, code: TariffTypeEnum) -> _Sources:
    tariff = entry.tariffs[code]
    _, subscription_source = entry.subscription_for(code)
    sources = _Sources(data.documents)
    sources.add(f"stawki sieciowe {code.value}", tariff.rates_source)
    sources.add(f"godziny stref {code.value}", tariff.hours_source)
    sources.add("opłata abonamentowa", subscription_source)
    return sources


def build_definitions(data: OperatorFile) -> list[DefinitionSpec]:
    specs: list[DefinitionSpec] = []
    codes = sorted({code for entry in data.distribution for code in entry.tariffs}, key=lambda code: code.value)
    for code in codes:
        for distribution in (entry for entry in data.distribution if code in entry.tariffs):
            tariff = distribution.tariffs[code]
            subscription, _ = distribution.subscription_for(code)
            for energy in (entry for entry in data.energy if code in entry.tariffs):
                start = max(distribution.valid_from, energy.valid_from)
                end = min(distribution.valid_to, energy.valid_to)
                if start > end:
                    continue
                prices = energy.tariffs[code]
                distribution_sources = _distribution_sources(data, distribution, code)
                energy_sources = _Sources(data.documents)
                energy_sources.add(f"ceny energii {code.value} ({energy.seller})", prices.source or energy.source)
                energy_sources.add("akcyza w cenach", energy.excise_source)
                if energy.price_cap is not None:
                    energy_sources.add(f"cena maksymalna {_money(energy.price_cap)} zł/kWh", energy.price_cap_source)
                if energy.trade_fee is not None:
                    energy_sources.add("opłata handlowa", energy.trade_fee_source)
                specs.append(
                    DefinitionSpec(
                        operator=data.operator,
                        tariff_code=code,
                        distribution_group=code,
                        name=None,
                        valid_from=start,
                        valid_to=end,
                        zones=[
                            ZoneSpec(
                                index=zone,
                                name=tariff.zone_names[zone],
                                network_rate=tariff.rates[zone],
                                energy_price=prices.prices[zone],
                            )
                            for zone in sorted(tariff.rates)
                        ],
                        fixed_1phase=tariff.fixed_1phase,
                        fixed_3phase=tariff.fixed_3phase,
                        subscription=dict(subscription),
                        trade_fee=energy.trade_fee,
                        prosumer_trade_fee=None,
                        zone_hours=_zone_hours(tariff),
                        distribution_valid_from=distribution.valid_from,
                        distribution_valid_to=distribution.valid_to,
                        distribution_source=distribution_sources.text(),
                        energy_valid_from=energy.valid_from,
                        energy_valid_to=energy.valid_to,
                        energy_source=energy_sources.text(),
                        seller=energy.seller,
                        includes_excise=energy.includes_excise,
                        price_cap=energy.price_cap,
                    )
                )

    for offer, code in ((offer, code) for offer in data.dynamic_offers for code in offer.distribution_tariffs):
        for distribution in (entry for entry in data.distribution if code in entry.tariffs):
            start = max(distribution.valid_from, offer.valid_from)
            end = min(distribution.valid_to, offer.valid_to)
            if start > end:
                continue
            tariff = distribution.tariffs[code]
            subscription, _ = distribution.subscription_for(code)
            distribution_sources = _distribution_sources(data, distribution, code)
            energy_sources = _Sources(data.documents)
            energy_sources.add(f"oferta „{offer.name}” ({offer.seller})", offer.source)
            for field_name, field_source in offer.field_sources.items():
                energy_sources.add(field_name, field_source)
            specs.append(
                DefinitionSpec(
                    operator=data.operator,
                    tariff_code=TariffTypeEnum.DYNAMIC,
                    distribution_group=code,
                    name=offer.name,
                    valid_from=start,
                    valid_to=end,
                    # Strefa 1 oferty: stawka sieciowa jak w taryfie dystrybucyjnej, „cena energii” = marża.
                    zones=[
                        ZoneSpec(
                            index=zone,
                            name=tariff.zone_names[zone],
                            network_rate=tariff.rates[zone],
                            energy_price=offer.margin,
                        )
                        for zone in sorted(tariff.rates)
                    ],
                    fixed_1phase=tariff.fixed_1phase,
                    fixed_3phase=tariff.fixed_3phase,
                    subscription=dict(subscription),
                    trade_fee=offer.trade_fee_monthly,
                    prosumer_trade_fee=offer.prosumer_trade_fee_monthly,
                    zone_hours=_zone_hours(tariff),
                    distribution_valid_from=distribution.valid_from,
                    distribution_valid_to=distribution.valid_to,
                    distribution_source=distribution_sources.text(),
                    energy_valid_from=offer.valid_from,
                    energy_valid_to=offer.valid_to,
                    energy_source=energy_sources.text(),
                    seller=offer.seller,
                    includes_excise=offer.includes_excise,
                    prosumer_margin=offer.prosumer_margin,
                    market_price_floor=offer.market_price_floor,
                    market_price_cap=offer.market_price_cap,
                    required_billing_cycle_months=offer.billing_cycle_months,
                )
            )
    return sorted(specs, key=lambda spec: (spec.tariff_code.value, spec.distribution_group.value, spec.valid_from))


def build_unsupported(data: OperatorFile) -> list[UnsupportedSpec]:
    return [
        UnsupportedSpec(
            operator=data.operator,
            code=entry.code,
            name=entry.name,
            reason=entry.reason,
            valid_from=entry.valid_from,
            valid_to=entry.valid_to,
            source=entry.source.describe(data.documents),
        )
        for entry in data.unsupported
    ]


def build_regulatory(data: RegulatoryFile) -> list[RegulatorySpec]:
    specs = []
    for period in data.periods:
        sources = _Sources(data.documents)
        for key, label in REGULATORY_VALUES.items():
            value, source = period.values[key]
            sources.add(f"{label} {value}", source)
        sources.add("opłata mocowa", period.capacity_source)
        if period.transition_bands:
            sources.add("opłata przejściowa", period.transition_source)
        specs.append(
            RegulatorySpec(
                valid_from=period.valid_from,
                valid_to=period.valid_to,
                values={key: value for key, (value, _) in period.values.items()},
                capacity_bands=period.capacity_bands,
                transition_bands=period.transition_bands,
                source=sources.text(),
            )
        )
    return specs


def coverage(data_set: TariffDataSet) -> dict[DistributionOperatorEnum, dict[TariffTypeEnum, list[date]]]:
    """Dni pokryte definicjami: operator → taryfa → posortowane dni."""
    result: dict[DistributionOperatorEnum, dict[TariffTypeEnum, set[date]]] = {}
    for data in data_set.operator_files:
        for spec in build_definitions(data):
            days = result.setdefault(data.operator, {}).setdefault(spec.tariff_code, set())
            days.update(days_between(spec.valid_from, spec.valid_to))
    return {
        operator: {code: sorted(days) for code, days in codes.items()} for operator, codes in result.items()
    }


def completeness_errors(data_set: TariffDataSet, first: date, last: date) -> list[str]:
    """Każda liczona taryfa każdego operatora ma stawki na każdy dzień od swojego pierwszego dnia (nie
    wcześniej niż `first`) do `last`, a opłaty regulacyjne obejmują każdy dzień od `first` do `last`."""
    from app.services.tariff_engine import format_day_ranges

    errors = []
    for operator, codes in coverage(data_set).items():
        for code, days in codes.items():
            start = max(first, days[0])
            covered = set(days)
            missing = [day for day in days_between(start, last) if day not in covered]
            if missing:
                errors.append(f"{operator.value} {code.value}: brak stawek dla dni {format_day_ranges(missing)}.")
    regulatory_days = {
        day
        for data in data_set.regulatory_files
        for period in data.periods
        for day in days_between(period.valid_from, period.valid_to)
    }
    missing = [day for day in days_between(first, last) if day not in regulatory_days]
    if missing:
        errors.append(f"Opłaty regulacyjne: brak dla dni {format_day_ranges(missing)}.")
    return errors
