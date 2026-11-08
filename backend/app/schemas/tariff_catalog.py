from datetime import date

from pydantic import BaseModel


class SubscriptionFeeOut(BaseModel):
    billing_cycle_months: int
    monthly_fee: float


class DistributionOut(BaseModel):
    valid_from: date
    valid_to: date
    source: str
    fixed_monthly_1phase: float
    fixed_monthly_3phase: float
    subscription: list[SubscriptionFeeOut]


class EnergyOut(BaseModel):
    valid_from: date
    valid_to: date
    source: str
    seller: str | None
    includes_excise: bool
    price_cap_per_kwh: float | None
    trade_fee_monthly: float | None
    prosumer_trade_fee_monthly: float | None


class ZoneHourOut(BaseModel):
    day_type: str
    season_from: str
    season_to: str
    start: str
    end: str


class ZoneOut(BaseModel):
    zone_index: int
    name: str | None
    energy_price_per_kwh: float | None
    network_rate_per_kwh: float | None
    hours: list[ZoneHourOut]


class DynamicOut(BaseModel):
    margin: float | None
    prosumer_margin: float | None
    market_price_floor_mwh: float | None
    market_price_cap_mwh: float | None
    billing_cycle_months: int | None


class ThresholdOut(BaseModel):
    min_kwh: float
    max_kwh: float | None
    fee: float


class RegulatoryOut(BaseModel):
    valid_from: date
    valid_to: date
    quality_fee_per_kwh: float
    renewable_fee_per_kwh: float
    cogeneration_fee_per_kwh: float
    excise_per_kwh: float
    vat_rate: float
    capacity_fee_monthly: list[ThresholdOut]
    transition_fee_monthly: list[ThresholdOut]
    source: str


class CatalogTariffOut(BaseModel):
    code: str
    # Grupa dystrybucyjna (dla oferty dynamicznej: grupa, z którą jest liczona).
    distribution_group: str
    name: str
    valid_from: date
    valid_to: date
    distribution: DistributionOut
    energy: EnergyOut
    zones: list[ZoneOut]
    dynamic: DynamicOut | None


class CatalogUnsupportedOut(BaseModel):
    code: str
    name: str
    reason: str
    valid_from: date
    valid_to: date
    source: str


class TariffCatalogResponse(BaseModel):
    operator: str
    date: date
    tariffs: list[CatalogTariffOut]
    regulatory: RegulatoryOut | None
    unsupported: list[CatalogUnsupportedOut]


class TariffOptionOut(BaseModel):
    code: str
    name: str
    billing_cycles: list[int]
    available_from: date
    available_to: date


class UnsupportedOptionOut(BaseModel):
    code: str
    name: str
    reason: str


class DynamicOfferOptionOut(BaseModel):
    name: str
    seller: str | None
    # Grupy, z którymi sprzedawca dopuszcza ofertę.
    distribution_groups: list[str]
    billing_cycle_months: int | None
    available_from: date
    available_to: date


class TariffOptionsResponse(BaseModel):
    has_rates: bool
    tariffs: list[TariffOptionOut]
    dynamic_offer: DynamicOfferOptionOut | None = None
    billing_cycles: list[int]
    unsupported: list[UnsupportedOptionOut]
