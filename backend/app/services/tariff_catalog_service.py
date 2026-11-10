from datetime import date

from app.models.NewModels import TariffDefinition
from app.repositories.tariff_definition_repository import TariffDefinitionRepository
from app.schemas.other import DistributionOperatorEnum, TariffTypeEnum
from app.schemas.tariff_catalog import (
    CatalogTariffOut,
    CatalogUnsupportedOut,
    DynamicOfferOptionOut,
    DistributionOut,
    DynamicOut,
    EnergyOut,
    RegulatoryOut,
    SubscriptionFeeOut,
    TariffCatalogResponse,
    TariffOptionOut,
    TariffOptionsResponse,
    ThresholdOut,
    UnsupportedOptionOut,
    ZoneHourOut,
    ZoneOut,
)
from app.services.tariff_zone_text import describe_zones


def _float(value) -> float | None:
    return float(value) if value is not None else None


def _clock(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _thresholds(rows) -> list[ThresholdOut]:
    return [
        ThresholdOut(min_kwh=float(row.min_kwh_annual), max_kwh=_float(row.max_kwh_annual), fee=float(row.monthly_fee_net_pln))
        for row in sorted(rows, key=lambda row: row.min_kwh_annual)
    ]


class TariffCatalogService:
    """Odczyt cennika z bazy dla widoków: katalog stawek na dzień i opcje formularza profilu."""

    def __init__(self, repository: TariffDefinitionRepository):
        self.repository = repository

    def catalog(self, operator: DistributionOperatorEnum, on_date: date) -> TariffCatalogResponse:
        definitions = self.repository.list_for_period(operator=operator, date_from=on_date, date_to=on_date)
        periods = self.repository.list_regulatory_periods(date_from=on_date, date_to=on_date)
        unsupported = self.repository.list_unsupported(operator=operator, date_from=on_date, date_to=on_date)
        return TariffCatalogResponse(
            operator=operator.value,
            date=on_date,
            tariffs=[self._tariff(definition) for definition in definitions],
            regulatory=self._regulatory(periods[0]) if periods else None,
            unsupported=[
                CatalogUnsupportedOut(
                    code=row.tariff_code,
                    name=row.name,
                    reason=row.reason,
                    valid_from=row.valid_from,
                    valid_to=row.valid_to,
                    source=row.source,
                )
                for row in unsupported
            ],
        )

    @staticmethod
    def _tariff(definition: TariffDefinition) -> CatalogTariffOut:
        code = definition.tariff_code.value
        network = {rate.zone_index: rate for rate in definition.variable_network_rates}
        energy = {rate.zone_index: rate for rate in definition.supplier_ure_rates}
        seller = next(iter(energy.values())).supplier_name if energy else None
        zones = []
        for index in sorted(set(network) | set(energy)):
            zones.append(
                ZoneOut(
                    zone_index=index,
                    name=network[index].zone_name if index in network else None,
                    energy_price_per_kwh=_float(energy[index].energy_price_per_kwh_net_pln) if index in energy else None,
                    network_rate_per_kwh=_float(network[index].rate_per_kwh_net_pln) if index in network else None,
                    hours=[
                        ZoneHourOut(
                            day_type=hour.day_type,
                            season_from=hour.season_from,
                            season_to=hour.season_to,
                            start=_clock(hour.start_minute),
                            end=_clock(hour.end_minute),
                        )
                        for hour in sorted(
                            (h for h in definition.zone_hours if h.zone_index == index),
                            key=lambda h: (h.day_type, h.season_from, h.start_minute),
                        )
                    ],
                )
            )
        dynamic = None
        if definition.tariff_code == TariffTypeEnum.DYNAMIC:
            dynamic = DynamicOut(
                margin=_float(energy[1].energy_price_per_kwh_net_pln) if 1 in energy else None,
                prosumer_margin=_float(definition.prosumer_margin_per_kwh),
                market_price_floor_mwh=_float(definition.market_price_floor_mwh),
                market_price_cap_mwh=_float(definition.market_price_cap_mwh),
                billing_cycle_months=definition.required_billing_cycle_months,
            )
        return CatalogTariffOut(
            code=code,
            distribution_group=definition.distribution_group.value,
            name=definition.name or code,
            valid_from=definition.valid_from,
            valid_to=definition.valid_to,
            distribution=DistributionOut(
                valid_from=definition.distribution_valid_from,
                valid_to=definition.distribution_valid_to,
                source=definition.distribution_source,
                fixed_monthly_1phase=float(definition.fixed_network_fee_1phase_monthly),
                fixed_monthly_3phase=float(definition.fixed_network_fee_3phase_monthly),
                subscription=[
                    SubscriptionFeeOut(billing_cycle_months=fee.billing_cycle_months, monthly_fee=float(fee.monthly_fee_net_pln))
                    for fee in sorted(definition.subscription_fees, key=lambda fee: fee.billing_cycle_months)
                ],
            ),
            energy=EnergyOut(
                valid_from=definition.energy_valid_from,
                valid_to=definition.energy_valid_to,
                source=definition.energy_source,
                seller=seller,
                includes_excise=definition.energy_includes_excise,
                price_cap_per_kwh=_float(definition.energy_price_cap_per_kwh),
                trade_fee_monthly=_float(definition.trade_fee_monthly),
                prosumer_trade_fee_monthly=_float(definition.prosumer_trade_fee_monthly),
            ),
            zones=zones,
            dynamic=dynamic,
        )

    @staticmethod
    def _regulatory(period) -> RegulatoryOut:
        return RegulatoryOut(
            valid_from=period.valid_from,
            valid_to=period.valid_to,
            quality_fee_per_kwh=float(period.quality_fee_per_kwh),
            renewable_fee_per_kwh=float(period.renewable_energy_fee_per_kwh),
            cogeneration_fee_per_kwh=float(period.cogeneration_fee_per_kwh),
            excise_per_kwh=float(period.excise_per_kwh),
            vat_rate=float(period.vat_rate),
            capacity_fee_monthly=_thresholds(period.capacity_thresholds),
            transition_fee_monthly=_thresholds(period.transition_thresholds),
            source=period.source,
        )

    def options(self, operator: DistributionOperatorEnum) -> TariffOptionsResponse:
        definitions = self.repository.list_for_operator(operator=operator)
        by_code: dict[str, list[TariffDefinition]] = {}
        for definition in definitions:
            by_code.setdefault(definition.tariff_code.value, []).append(definition)

        tariffs = []
        dynamic_offer = None
        for code, rows in by_code.items():
            if code == TariffTypeEnum.DYNAMIC.value:
                latest = max(rows, key=lambda row: row.valid_from)
                dynamic_offer = DynamicOfferOptionOut(
                    name=latest.name or code,
                    seller=next((rate.supplier_name for rate in latest.supplier_ure_rates), None),
                    distribution_groups=sorted(
                        {row.distribution_group.value for row in rows},
                        key=lambda group: list(TariffTypeEnum).index(TariffTypeEnum(group)),
                    ),
                    billing_cycle_months=latest.required_billing_cycle_months,
                    available_from=min(row.valid_from for row in rows),
                    available_to=max(row.valid_to for row in rows),
                )
                continue
            cycles = {fee.billing_cycle_months for row in rows for fee in row.subscription_fees}
            tariffs.append(
                TariffOptionOut(
                    code=code,
                    name=next((row.name for row in reversed(rows) if row.name), code),
                    zones_description=describe_zones(max(rows, key=lambda row: row.valid_from)),
                    billing_cycles=sorted(cycles),
                    available_from=min(row.valid_from for row in rows),
                    available_to=max(row.valid_to for row in rows),
                )
            )
        tariffs.sort(key=lambda tariff: tariff.code)

        cycles = sorted(
            {
                fee.billing_cycle_months
                for definition in definitions
                if definition.tariff_code != TariffTypeEnum.DYNAMIC
                for fee in definition.subscription_fees
            }
        )
        unsupported: dict[str, UnsupportedOptionOut] = {}
        for row in self.repository.list_unsupported(operator=operator):
            unsupported[row.tariff_code] = UnsupportedOptionOut(code=row.tariff_code, name=row.name, reason=row.reason)
        return TariffOptionsResponse(
            has_rates=bool(definitions),
            tariffs=tariffs,
            dynamic_offer=dynamic_offer,
            billing_cycles=cycles,
            unsupported=[unsupported[code] for code in sorted(unsupported)],
        )
