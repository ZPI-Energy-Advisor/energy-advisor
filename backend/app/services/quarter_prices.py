from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Sequence

from app.parsers.devices import LOCAL_TIMEZONE
from app.schemas.other import PhaseTypeEnum, TariffTypeEnum
from app.services.tariff_zones import ZoneSchedule, covers

SLOT = timedelta(minutes=15)
MWH = Decimal("1000")
ZERO = Decimal("0")


def decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def included_excise(definition: Any, excise: Decimal) -> Decimal:
    """Akcyza zawarta w cenie (marży) sprzedawcy — odejmujemy ją, bo doliczamy ją osobną pozycją."""
    return excise if getattr(definition, "energy_includes_excise", False) else ZERO


def zone_energy_price(definition: Any, energy_rate: Decimal, excise: Decimal) -> Decimal:
    """Cena energii netto strefy bez akcyzy, ograniczona ceną maksymalną definicji (jeśli jest)."""
    price = energy_rate - included_excise(definition, excise)
    cap = getattr(definition, "energy_price_cap_per_kwh", None)
    return price if cap is None else min(price, decimal(cap))


def dynamic_energy_price(definition: Any, market_pln_kwh: Any, margin: Decimal, prosumer: bool, excise: Decimal) -> Decimal:
    """Cena energii netto kwadransa w ofercie dynamicznej bez akcyzy: cena rynkowa ograniczona do
    [market_price_floor, market_price_cap] + marża (prosumenta, jeśli oferta ją podaje)."""
    prosumer_margin = getattr(definition, "prosumer_margin_per_kwh", None)
    if prosumer and prosumer_margin is not None:
        margin = decimal(prosumer_margin)
    market = decimal(market_pln_kwh) * MWH
    floor = getattr(definition, "market_price_floor_mwh", None)
    cap = getattr(definition, "market_price_cap_mwh", None)
    if floor is not None:
        market = max(market, decimal(floor))
    if cap is not None:
        market = min(market, decimal(cap))
    return market / MWH + margin - included_excise(definition, excise)


def rates_by_zone(rates: Iterable[Any], attribute: str) -> dict[int, Decimal]:
    return {int(rate.zone_index): decimal(getattr(rate, attribute)) for rate in rates}


@dataclass(frozen=True)
class KwhPrice:
    """Cena 1 kWh netto w składnikach (zł/kWh) i stawka VAT."""

    zone: int
    energy: Decimal
    excise: Decimal
    network: Decimal
    quality: Decimal
    renewable: Decimal
    cogeneration: Decimal
    vat_rate: Decimal
    net: Decimal = field(init=False, repr=False, compare=False)
    gross: Decimal = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        net = self.energy + self.excise + self.network + self.quality + self.renewable + self.cogeneration
        object.__setattr__(self, "net", net)
        object.__setattr__(self, "gross", net * (Decimal(1) + self.vat_rate))

    def as_dict(self) -> dict[str, float | int]:
        return {
            "zone": self.zone,
            "energy": float(self.energy),
            "excise": float(self.excise),
            "network": float(self.network),
            "quality": float(self.quality),
            "renewable": float(self.renewable),
            "cogeneration": float(self.cogeneration),
            "net": float(self.net),
            "vat_rate": float(self.vat_rate),
            "gross": float(round(self.gross, 5)),
        }


class TariffRates:
    """Stawki za kWh jednej definicji taryfy w jednym okresie opłat regulacyjnych."""

    def __init__(self, definition: Any, period: Any):
        self.definition = definition
        self.dynamic = definition.tariff_code == TariffTypeEnum.DYNAMIC
        self.energy_rates = rates_by_zone(definition.supplier_ure_rates, "energy_price_per_kwh_net_pln")
        self.network_rates = rates_by_zone(definition.variable_network_rates, "rate_per_kwh_net_pln")
        self.excise = decimal(getattr(period, "excise_per_kwh", 0) or 0)
        self.quality = decimal(period.quality_fee_per_kwh)
        self.renewable = decimal(period.renewable_energy_fee_per_kwh)
        self.cogeneration = decimal(period.cogeneration_fee_per_kwh)
        self.vat_rate = decimal(period.vat_rate)
        self._fixed: dict[int, KwhPrice] = {}
        if self.dynamic:
            prosumer_margin = getattr(definition, "prosumer_margin_per_kwh", None)
            floor = getattr(definition, "market_price_floor_mwh", None)
            cap = getattr(definition, "market_price_cap_mwh", None)
            margin = self.energy_rates[1]
            self._margins = {False: margin, True: margin if prosumer_margin is None else decimal(prosumer_margin)}
            self._floor = None if floor is None else decimal(floor)
            self._cap = None if cap is None else decimal(cap)
            self._included_excise = included_excise(definition, self.excise)

    def energy(self, zone: int, market_pln_kwh: Any = None, prosumer: bool = False) -> Decimal:
        if self.dynamic:
            if market_pln_kwh is None:
                raise ValueError("Taryfa dynamiczna wymaga ceny rynkowej kwadransa.")
            market = decimal(market_pln_kwh) * MWH
            if self._floor is not None:
                market = max(market, self._floor)
            if self._cap is not None:
                market = min(market, self._cap)
            return market / MWH + self._margins[bool(prosumer)] - self._included_excise
        return zone_energy_price(self.definition, self.energy_rates[zone], self.excise)

    def price(self, zone: int, market_pln_kwh: Any = None, prosumer: bool = False) -> KwhPrice:
        if not self.dynamic and zone in self._fixed:
            return self._fixed[zone]
        price = KwhPrice(
            zone=zone,
            energy=self.energy(zone, market_pln_kwh, prosumer),
            excise=self.excise,
            network=self.network_rates[zone],
            quality=self.quality,
            renewable=self.renewable,
            cogeneration=self.cogeneration,
            vat_rate=self.vat_rate,
        )
        if not self.dynamic:
            self._fixed[zone] = price
        return price


def subscription_fee(fees: Iterable[Any], months: int) -> Decimal:
    for fee in fees:
        if fee.billing_cycle_months == months:
            return decimal(fee.monthly_fee_net_pln)
    raise ValueError(f"Brak opłaty abonamentowej dla cyklu {months} miesięcy.")


def trade_fee(definition: Any, prosumer: bool) -> Decimal:
    """Miesięczna opłata handlowa sprzedawcy (prosument może mieć własną); brak = brak opłaty."""
    fee = getattr(definition, "trade_fee_monthly", None)
    prosumer_fee = getattr(definition, "prosumer_trade_fee_monthly", None)
    if prosumer and prosumer_fee is not None:
        fee = prosumer_fee
    return ZERO if fee is None else decimal(fee)


def threshold_fee(thresholds: Iterable[Any], annual_kwh: Decimal, name: str) -> Decimal:
    """Miesięczna opłata z progu, do którego należy roczne zużycie (próg od min włącznie do max wyłącznie).

    Okres bez progów (np. opłata przejściowa od 2026 r.) oznacza brak opłaty."""
    thresholds = list(thresholds)
    if not thresholds:
        return ZERO
    for threshold in thresholds:
        minimum = decimal(threshold.min_kwh_annual)
        maximum = None if threshold.max_kwh_annual is None else decimal(threshold.max_kwh_annual)
        if minimum <= annual_kwh and (maximum is None or annual_kwh < maximum):
            return decimal(threshold.monthly_fee_net_pln)
    raise ValueError(f"Brak progu opłaty {name} dla rocznego zużycia {annual_kwh:.0f} kWh.")


@dataclass(frozen=True)
class FeeParameters:
    phase_type: PhaseTypeEnum
    billing_cycle_months: int
    annual_kwh: Decimal
    prosumer: bool = False


@dataclass(frozen=True)
class MonthlyFees:
    """Opłaty miesięczne netto (zł/miesiąc) i stawka VAT."""

    fixed_network: Decimal
    subscription: Decimal
    capacity: Decimal
    transition: Decimal
    trade: Decimal
    vat_rate: Decimal

    @property
    def net(self) -> Decimal:
        return self.fixed_network + self.subscription + self.capacity + self.transition + self.trade

    @property
    def gross(self) -> Decimal:
        return self.net * (Decimal(1) + self.vat_rate)

    def as_dict(self) -> dict[str, float]:
        return {
            "fixed_network": float(self.fixed_network),
            "subscription": float(self.subscription),
            "capacity": float(self.capacity),
            "transition": float(self.transition),
            "trade": float(self.trade),
            "net": float(self.net),
            "vat_rate": float(self.vat_rate),
            "gross": float(round(self.gross, 2)),
        }


def monthly_fees(definition: Any, period: Any, parameters: FeeParameters) -> MonthlyFees:
    fixed_network = (
        definition.fixed_network_fee_1phase_monthly
        if parameters.phase_type == PhaseTypeEnum.SINGLE_PHASE
        else definition.fixed_network_fee_3phase_monthly
    )
    return MonthlyFees(
        fixed_network=decimal(fixed_network),
        subscription=subscription_fee(definition.subscription_fees, parameters.billing_cycle_months),
        capacity=threshold_fee(period.capacity_thresholds, parameters.annual_kwh, "mocowej"),
        transition=threshold_fee(period.transition_thresholds, parameters.annual_kwh, "przejściowej"),
        trade=trade_fee(definition, parameters.prosumer),
        vat_rate=decimal(period.vat_rate),
    )


@dataclass(frozen=True)
class MonthlyFeesPeriod:
    valid_from: date
    valid_to: date
    fees: MonthlyFees


@dataclass(frozen=True)
class QuarterPrices:
    """Ceny kwadransów (początek w UTC) z rozbiciem na składniki i opłaty miesięczne osobno.

    `missing` to kwadranse bez ceny: bez definicji taryfy, okresu opłat regulacyjnych albo ceny RCE.
    `missing_rates` to ta ich część, której brakuje stawek (definicji taryfy albo okresu opłat), a nie ceny RCE."""

    prices: dict[datetime, KwhPrice]
    monthly_fees: tuple[MonthlyFeesPeriod, ...]
    missing: tuple[datetime, ...]
    name: str | None = None
    missing_rates: tuple[datetime, ...] = ()

    def gross(self, digits: int = 5) -> dict[datetime, float]:
        return {slot: float(round(price.gross, digits)) for slot, price in self.prices.items()}


def quarter_prices(
    definitions: Sequence[Any],
    periods: Sequence[Any],
    start_utc: datetime,
    end_utc: datetime,
    *,
    market_price=None,
    prosumer: bool = False,
    fee_parameters: FeeParameters | None = None,
    schedule: ZoneSchedule | None = None,
) -> QuarterPrices:
    """Cena każdego kwadransa [start_utc, end_utc) jednej taryfy; `market_price(kwadrans_utc)` zwraca cenę RCE
    w zł/kWh albo zgłasza ValueError, gdy jej brak (potrzebna tylko w ofercie dynamicznej)."""
    schedule = schedule or ZoneSchedule(definitions)
    dynamic = schedule.definitions[0].tariff_code == TariffTypeEnum.DYNAMIC
    if dynamic and market_price is None:
        raise ValueError("Brak cen RCE dla taryfy dynamicznej.")
    rates: dict[tuple[int, int], TariffRates] = {}
    prices: dict[datetime, KwhPrice] = {}
    missing: list[datetime] = []
    missing_rates: list[datetime] = []
    slot = start_utc
    current_day = definition = period = None
    while slot < end_utc:
        local = slot.astimezone(LOCAL_TIMEZONE)
        day = local.date()
        if day != current_day:
            current_day = day
            definition = schedule.definition_for(day)
            period = next((item for item in periods if covers(item, day)), None)
        if definition is None or period is None:
            missing.append(slot)
            missing_rates.append(slot)
            slot += SLOT
            continue
        key = (id(definition), id(period))
        if key not in rates:
            rates[key] = TariffRates(definition, period)
        zone = schedule.zone_index(local.replace(tzinfo=None))
        market = None
        if dynamic:
            try:
                market = market_price(slot.astimezone(timezone.utc))
            except ValueError:
                missing.append(slot)
                slot += SLOT
                continue
        prices[slot] = rates[key].price(zone, market, prosumer)
        slot += SLOT
    return QuarterPrices(
        prices=prices,
        monthly_fees=_monthly_fee_periods(schedule.definitions, periods, start_utc, end_utc, fee_parameters),
        missing=tuple(missing),
        name=next((definition.name for definition in schedule.definitions if getattr(definition, "name", None)), None),
        missing_rates=tuple(missing_rates),
    )


def _monthly_fee_periods(definitions, periods, start_utc, end_utc, parameters) -> tuple[MonthlyFeesPeriod, ...]:
    if parameters is None or end_utc <= start_utc:
        return ()
    first = start_utc.astimezone(LOCAL_TIMEZONE).date()
    last = (end_utc - SLOT).astimezone(LOCAL_TIMEZONE).date()
    result: list[MonthlyFeesPeriod] = []
    day = first
    while day <= last:
        definition = next((item for item in definitions if covers(item, day)), None)
        period = next((item for item in periods if covers(item, day)), None)
        if definition is None or period is None:
            day += timedelta(days=1)
            continue
        until = min(definition.valid_to, period.valid_to, last)
        result.append(MonthlyFeesPeriod(day, until, monthly_fees(definition, period, parameters)))
        day = until + timedelta(days=1)
    return tuple(result)


class MissingTariffRates(LookupError):
    pass


class QuarterPriceService:
    """Ceny kwadransów dowolnej taryfy operatora z nowego cennika (`tariff_definitions`)."""

    def __init__(self, tariff_repository, market_prices=None):
        self.tariff_repository = tariff_repository
        self.market_prices = market_prices

    def for_tariff(
        self,
        *,
        operator,
        tariff_code: TariffTypeEnum,
        distribution_group: TariffTypeEnum,
        start_utc: datetime,
        end_utc: datetime,
        prosumer: bool = False,
        fee_parameters: FeeParameters | None = None,
    ) -> QuarterPrices:
        first_day = start_utc.astimezone(LOCAL_TIMEZONE).date()
        last_day = (end_utc - SLOT).astimezone(LOCAL_TIMEZONE).date()
        definitions = [
            definition
            for definition in self.tariff_repository.list_for_period(operator=operator, date_from=first_day, date_to=last_day)
            if definition.tariff_code == tariff_code and definition.distribution_group == distribution_group
        ]
        if not definitions:
            raise MissingTariffRates(tariff_code, distribution_group)
        periods = self.tariff_repository.list_regulatory_periods(date_from=first_day, date_to=last_day)
        market_price = None
        if tariff_code == TariffTypeEnum.DYNAMIC and self.market_prices is not None:
            preload = getattr(self.market_prices, "preload_rce", None)
            if preload is not None:
                preload(start_utc, end_utc)
            market_price = self.market_prices.rce
        return quarter_prices(
            definitions, periods, start_utc, end_utc,
            market_price=market_price, prosumer=prosumer, fee_parameters=fee_parameters,
        )
