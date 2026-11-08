from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Sequence
from dateutil.relativedelta import relativedelta

from app.schemas.calculation import CalculationDetails
from app.schemas.other import PhaseTypeEnum, TariffTypeEnum
from app.services.tariff_zones import ZoneSchedule


CENT = Decimal("0.01")
DAYS_IN_YEAR = 365
MWH = Decimal("1000")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def covers(item: Any, day: date) -> bool:
    return item.valid_from <= day <= item.valid_to


def days_between(first: date, last: date) -> list[date]:
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def format_day_ranges(days: Iterable[date]) -> str:
    """Dni jako zakresy, np. „2027-01-01 – 2027-01-31, 2027-03-05”."""
    ranges: list[list[date]] = []
    for day in sorted(days):
        if ranges and day - ranges[-1][1] == timedelta(days=1):
            ranges[-1][1] = day
        else:
            ranges.append([day, day])
    return ", ".join(
        first.isoformat() if first == last else f"{first.isoformat()} – {last.isoformat()}"
        for first, last in ranges
    )


def decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def included_excise(definition: Any, excise: Decimal) -> Decimal:
    """Akcyza zawarta w cenie (marży) sprzedawcy — odejmujemy ją, bo doliczamy ją osobną pozycją."""
    return excise if getattr(definition, "energy_includes_excise", False) else Decimal("0")


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


@dataclass(frozen=True)
class BillingContext:
    """Dane wspólne dla wszystkich taryf jednego pliku.

    Opłaty miesięczne są liczone tylko za dni od `first_day` do `last_day` (okres pliku), żeby
    dotyczyły tego samego czasu co energia. `raw_cycles` to zużycie przed bilansowaniem PV; służy do
    podziału energii zbilansowanej w strefach na odcinki z różnymi stawkami. `prosumer` wybiera marżę i
    opłatę handlową prosumenta w ofercie z ceną dynamiczną.
    """

    regulatory_periods: Sequence[Any]
    annual_kwh: Decimal
    first_day: date
    last_day: date
    raw_cycles: Sequence[tuple[datetime, Any]] = field(default_factory=tuple)
    prosumer: bool = False


@dataclass(frozen=True)
class TariffCycleResult:
    cycle_start: datetime
    cycle_end: datetime
    days_billed: int
    days_in_cycle: int
    active_energy_kwh: Decimal
    active_energy_net: Decimal
    excise_net: Decimal
    variable_network_net: Decimal
    quality_net: Decimal
    renewable_net: Decimal
    cogeneration_net: Decimal
    fixed_network_net: Decimal
    subscription_net: Decimal
    capacity_net: Decimal
    transition_net: Decimal
    trade_fee_net: Decimal
    net_total: Decimal
    vat: Decimal
    gross_total: Decimal


@dataclass(frozen=True)
class TariffCalculationResult:
    cycles: tuple[TariffCycleResult, ...]
    active_energy_gross: Decimal
    gross_total: Decimal
    deposit_amount: Decimal = Decimal("0")
    deposit_applied: Decimal = Decimal("0")
    payable_gross: Decimal = Decimal("0")
    name: str | None = None
    billing_cycle_months: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "billing_cycle_months": self.billing_cycle_months,
            "cycles": [
                {
                    "cycle_start": cycle.cycle_start.isoformat(),
                    "cycle_end": cycle.cycle_end.isoformat(),
                    "days_billed": cycle.days_billed,
                    "days_in_cycle": cycle.days_in_cycle,
                    "active_energy_kwh": float(cycle.active_energy_kwh),
                    **{name: float(getattr(cycle, name)) for name in COMPONENTS},
                    "net_total": float(cycle.net_total),
                    "vat": float(cycle.vat),
                    "gross_total": float(cycle.gross_total),
                }
                for cycle in self.cycles
            ],
            "trade_fee_net": float(sum((cycle.trade_fee_net for cycle in self.cycles), Decimal("0"))),
            "active_energy_gross": float(self.active_energy_gross),
            "gross_total": float(self.gross_total),
            "deposit_amount": float(self.deposit_amount),
            "deposit_applied": float(self.deposit_applied),
            "payable_gross": float(self.payable_gross),
        }


@dataclass
class _Segment:
    """Kolejne dni cyklu z tą samą definicją taryfy i tym samym okresem opłat regulacyjnych."""

    definition: Any
    period: Any
    days: list[date]
    zone_energy: list[Decimal] = field(default_factory=list)
    records: list[tuple[datetime, float]] | None = None


# Składniki rachunku netto w kolejności pól TariffCycleResult.
COMPONENTS = (
    "active_energy_net", "excise_net", "variable_network_net", "quality_net", "renewable_net",
    "cogeneration_net", "fixed_network_net", "subscription_net", "capacity_net", "transition_net",
    "trade_fee_net",
)


def billing_cycle_months(definitions: Sequence[Any], profile_months: int) -> int:
    """Okres rozliczeniowy taryfy: wymagany przez ofertę (np. 1 miesiąc w ofercie dynamicznej) albo z profilu."""
    required = {definition.required_billing_cycle_months for definition in definitions} - {None}
    if len(required) > 1:
        raise ValueError("Definicje oferty w okresie pliku wymagają różnych okresów rozliczeniowych.")
    return int(required.pop()) if required else profile_months


class ZonedTariffCalculationStrategy:
    """Rachunek za taryfę: energia i dystrybucja w strefach, akcyza, opłaty regulacyjne, opłaty miesięczne i VAT.

    Cena energii strefy to cena sprzedawcy bez akcyzy ograniczona ceną maksymalną definicji (jeśli jest);
    akcyza jest osobną pozycją ze stawki okresu regulacyjnego. W ofercie dynamicznej cena kwadransa to cena
    RCE ograniczona do [market_price_floor, market_price_cap] + marża (strefa 1 supplier_ure_rates; dla
    prosumenta prosumer_margin_per_kwh).

    Cykl przecinający zmianę cennika jest dzielony na odcinki dni: każdy dzień liczy się według
    definicji taryfy i okresu opłat regulacyjnych ważnych w tym dniu. Opłaty miesięczne odcinka to
    stawka miesięczna × liczba miesięcy cyklu × dni odcinka / dni cyklu.
    """

    def __init__(self):
        self.dynamic_price_resolver = None

    def set_dynamic_price_resolver(self, resolver):
        self.dynamic_price_resolver = resolver

    def calculate(
        self,
        calculation_details: CalculationDetails,
        definitions: Sequence[Any],
        context: BillingContext,
        schedule: ZoneSchedule | None = None,
    ) -> TariffCalculationResult:
        if not definitions:
            raise ValueError("Brak definicji taryfy.")
        definitions = sorted(definitions, key=lambda definition: definition.valid_from)
        tariff_type = definitions[0].tariff_code
        schedule = schedule or ZoneSchedule(definitions)
        for definition in definitions:
            self._check_definition(definition, schedule.zone_count)
        if tariff_type == TariffTypeEnum.DYNAMIC and self.dynamic_price_resolver is None:
            raise ValueError("Brak resolvera cen RCE dla taryfy dynamicznej.")

        months = calculation_details.tariff_data.billing_cycle.value
        raw_cycles = dict(context.raw_cycles)
        cycles = []
        active_energy_gross = Decimal("0")
        for cycle_start, energy in self._cycles(calculation_details):
            cycle_end = cycle_start + relativedelta(months=months) - relativedelta(days=1)
            first = max(cycle_start.date(), context.first_day)
            last = min(cycle_end.date(), context.last_day)
            if first > last:
                continue
            days_in_cycle = (cycle_end.date() - cycle_start.date()).days + 1
            segments = self._segments(days_between(first, last), definitions, context.regulatory_periods, tariff_type)
            self._split_energy(energy, segments, schedule, raw_cycles.get(cycle_start))

            totals = dict.fromkeys(COMPONENTS, Decimal("0"))
            vat = Decimal("0")
            for segment in segments:
                parts = self._segment_parts(segment, calculation_details, context, months, days_in_cycle, tariff_type)
                vat_rate = decimal(segment.period.vat_rate)
                vat += sum(parts.values(), Decimal("0")) * vat_rate
                active_energy_gross += (parts["active_energy_net"] + parts["excise_net"]) * (1 + vat_rate)
                for name, value in parts.items():
                    totals[name] += value

            net_total = sum(totals.values(), Decimal("0"))
            cycles.append(
                TariffCycleResult(
                    cycle_start=cycle_start,
                    cycle_end=cycle_end,
                    days_billed=(last - first).days + 1,
                    days_in_cycle=days_in_cycle,
                    active_energy_kwh=sum(
                        (sum(segment.zone_energy, Decimal("0")) for segment in segments), Decimal("0")
                    ),
                    **{name: money(value) for name, value in totals.items()},
                    net_total=money(net_total),
                    vat=money(vat),
                    gross_total=money(net_total + vat),
                )
            )

        gross_total = money(sum((cycle.gross_total for cycle in cycles), Decimal("0")))
        return TariffCalculationResult(
            cycles=tuple(cycles),
            active_energy_gross=money(active_energy_gross),
            gross_total=gross_total,
            payable_gross=gross_total,
            name=next((definition.name for definition in definitions if getattr(definition, "name", None)), None),
            billing_cycle_months=months,
        )

    def _segment_parts(
        self,
        segment: _Segment,
        calculation_details: CalculationDetails,
        context: BillingContext,
        months: int,
        days_in_cycle: int,
        tariff_type: TariffTypeEnum,
    ) -> dict[str, Decimal]:
        definition, period = segment.definition, segment.period
        energy_rates = self._rates_by_zone(definition.supplier_ure_rates, "energy_price_per_kwh_net_pln")
        network_rates = self._rates_by_zone(definition.variable_network_rates, "rate_per_kwh_net_pln")
        zone_energy = segment.zone_energy
        kwh = sum(zone_energy, Decimal("0"))
        excise = decimal(getattr(period, "excise_per_kwh", 0) or 0)

        if tariff_type == TariffTypeEnum.DYNAMIC:
            if segment.records is None:
                raise ValueError("Taryfa dynamiczna wymaga zużycia z zachowanymi znacznikami czasu.")
            active = sum(
                (
                    decimal(value) * dynamic_energy_price(
                        definition, self.dynamic_price_resolver(timestamp), energy_rates[1], context.prosumer, excise
                    )
                    for timestamp, value in segment.records
                ),
                Decimal("0"),
            )
        else:
            active = sum(
                (energy * zone_energy_price(definition, energy_rates[zone], excise)
                 for zone, energy in enumerate(zone_energy, start=1)),
                Decimal("0"),
            )

        fixed_network = (
            definition.fixed_network_fee_1phase_monthly
            if calculation_details.tariff_data.phase_type == PhaseTypeEnum.SINGLE_PHASE
            else definition.fixed_network_fee_3phase_monthly
        )
        # Część opłat miesięcznych przypadająca na dni odcinka.
        share = Decimal(months) * Decimal(len(segment.days)) / Decimal(days_in_cycle)
        return {
            "active_energy_net": active,
            "excise_net": kwh * excise,
            "variable_network_net": sum(
                (energy * network_rates[zone] for zone, energy in enumerate(zone_energy, start=1)), Decimal("0")
            ),
            "quality_net": kwh * decimal(period.quality_fee_per_kwh),
            "renewable_net": kwh * decimal(period.renewable_energy_fee_per_kwh),
            "cogeneration_net": kwh * decimal(period.cogeneration_fee_per_kwh),
            "fixed_network_net": decimal(fixed_network) * share,
            "subscription_net": self._subscription_fee(definition.subscription_fees, months) * share,
            "capacity_net": self._threshold_fee(period.capacity_thresholds, context.annual_kwh, "mocowej") * share,
            "transition_net": self._threshold_fee(period.transition_thresholds, context.annual_kwh, "przejściowej")
            * share,
            "trade_fee_net": self._trade_fee(definition, context.prosumer) * share,
        }

    @staticmethod
    def _check_definition(definition: Any, zones: int) -> None:
        energy_rates = ZonedTariffCalculationStrategy._rates_by_zone(
            definition.supplier_ure_rates, "energy_price_per_kwh_net_pln"
        )
        network_rates = ZonedTariffCalculationStrategy._rates_by_zone(
            definition.variable_network_rates, "rate_per_kwh_net_pln"
        )
        expected = set(range(1, zones + 1))
        if set(energy_rates) != expected or set(network_rates) != expected:
            raise ValueError("Brak kompletu stawek dla wszystkich stref taryfowych.")

    @staticmethod
    def _segments(
        days: list[date],
        definitions: Sequence[Any],
        periods: Sequence[Any],
        tariff_type: TariffTypeEnum,
    ) -> list[_Segment]:
        segments: list[_Segment] = []
        without_definition, without_period = [], []
        for day in days:
            definition = next((item for item in definitions if covers(item, day)), None)
            period = next((item for item in periods if covers(item, day)), None)
            if definition is None:
                without_definition.append(day)
            if period is None:
                without_period.append(day)
            if definition is None or period is None:
                continue
            last = segments[-1] if segments else None
            if last and last.definition is definition and last.period is period and last.days[-1] == day - timedelta(days=1):
                last.days.append(day)
            else:
                segments.append(_Segment(definition=definition, period=period, days=[day]))
        if without_definition:
            raise ValueError(f"Brak stawek taryfy {tariff_type.value} dla dni: {format_day_ranges(without_definition)}.")
        if without_period:
            raise ValueError(f"Brak opłat regulacyjnych dla dni: {format_day_ranges(without_period)}.")
        return segments

    @staticmethod
    def _split_energy(
        energy: Any,
        segments: list[_Segment],
        schedule: ZoneSchedule,
        raw_records: Any,
    ) -> None:
        """Przypisuje energię cyklu do odcinków: odczyty po dniu, a energię już zbilansowaną w strefach
        proporcjonalnie do zużycia w strefie przed bilansowaniem PV."""
        values = list(energy.items()) if isinstance(energy, dict) else list(energy)
        # Cykl bez poboru liczymy jak odczyty bez energii (taryfa dynamiczna wymaga list odczytów w odcinkach).
        if not values or isinstance(values[0], tuple):
            by_day = {day: segment for segment in segments for day in segment.days}
            for segment in segments:
                segment.records = []
            for timestamp, value in values:
                if not isinstance(timestamp, datetime):
                    raise ValueError("Odczyt energii musi mieć znacznik datetime.")
                segment = by_day.get(timestamp.date())
                if segment is None:
                    # Odczyty spoza dni rozliczanych (np. przed początkiem danych cennika) pomijamy.
                    continue
                segment.records.append((timestamp, value))
            for segment in segments:
                segment.zone_energy = zone_totals(segment.records, schedule)
            return

        totals = zone_totals(values, schedule)
        if len(segments) == 1:
            segments[0].zone_energy = totals
            return
        raw = {id(segment): [Decimal("0")] * len(totals) for segment in segments}
        by_day = {day: segment for segment in segments for day in segment.days}
        for timestamp, value in raw_records or []:
            segment = by_day.get(timestamp.date())
            if segment is not None:
                raw[id(segment)][schedule.zone_index(timestamp) - 1] += decimal(value)
        total_days = Decimal(sum(len(segment.days) for segment in segments))
        for segment in segments:
            segment.zone_energy = []
            for zone, total in enumerate(totals):
                raw_total = sum((raw[id(item)][zone] for item in segments), Decimal("0"))
                share = (
                    raw[id(segment)][zone] / raw_total if raw_total > 0 else Decimal(len(segment.days)) / total_days
                )
                segment.zone_energy.append(total * share)

    @staticmethod
    def _rates_by_zone(rates: Iterable[Any], field: str) -> dict[int, Decimal]:
        return {int(rate.zone_index): decimal(getattr(rate, field)) for rate in rates}

    @staticmethod
    def _cycles(calculation_details: CalculationDetails) -> Iterable[tuple[datetime, Any]]:
        yield from calculation_details.used_energy_cycles or []

    @staticmethod
    def _subscription_fee(fees: Iterable[Any], months: int) -> Decimal:
        for fee in fees:
            if fee.billing_cycle_months == months:
                return decimal(fee.monthly_fee_net_pln)
        raise ValueError(f"Brak opłaty abonamentowej dla cyklu {months} miesięcy.")

    @staticmethod
    def _trade_fee(definition: Any, prosumer: bool) -> Decimal:
        """Miesięczna opłata handlowa sprzedawcy (prosument może mieć własną); brak = brak opłaty."""
        fee = getattr(definition, "trade_fee_monthly", None)
        prosumer_fee = getattr(definition, "prosumer_trade_fee_monthly", None)
        if prosumer and prosumer_fee is not None:
            fee = prosumer_fee
        return Decimal("0") if fee is None else decimal(fee)

    @staticmethod
    def _threshold_fee(thresholds: Iterable[Any], annual_kwh: Decimal, name: str) -> Decimal:
        """Miesięczna opłata z progu, do którego należy roczne zużycie (próg od min włącznie do max wyłącznie).

        Okres bez progów (np. opłata przejściowa od 2026 r.) oznacza brak opłaty."""
        thresholds = list(thresholds)
        if not thresholds:
            return Decimal("0")
        for threshold in thresholds:
            minimum = decimal(threshold.min_kwh_annual)
            maximum = None if threshold.max_kwh_annual is None else decimal(threshold.max_kwh_annual)
            if minimum <= annual_kwh and (maximum is None or annual_kwh < maximum):
                return decimal(threshold.monthly_fee_net_pln)
        raise ValueError(f"Brak progu opłaty {name} dla rocznego zużycia {annual_kwh:.0f} kWh.")


def zone_totals(energy: Any, schedule: ZoneSchedule) -> list[Decimal]:
    """Energia w strefach (lista od strefy 1): z odczytów ze znacznikiem czasu albo już zbilansowana przez PV."""
    values = list(energy.items()) if isinstance(energy, dict) else list(energy)
    if values and isinstance(values[0], tuple):
        totals = [Decimal("0")] * schedule.zone_count
        for timestamp, value in values:
            if not isinstance(timestamp, datetime):
                raise ValueError("Odczyt energii musi mieć znacznik datetime.")
            totals[schedule.zone_index(timestamp) - 1] += decimal(value)
        return totals
    if not values:
        return [Decimal("0")] * schedule.zone_count
    if len(values) != schedule.zone_count:
        raise ValueError("Zbilansowana energia nie pasuje do liczby stref taryfowych.")
    return [decimal(value) for value in values]


class FinancialSettlement:
    def settle(
        self,
        result: TariffCalculationResult,
        overpayment_cycles: list[dict[str, float]] | None,
    ) -> TariffCalculationResult:
        deposit = money(
            sum(
                (Decimal(str(amount)) for cycle in (overpayment_cycles or []) for amount in cycle.values()),
                Decimal("0"),
            )
        )
        applied = min(deposit, result.active_energy_gross)
        return TariffCalculationResult(
            cycles=result.cycles,
            active_energy_gross=result.active_energy_gross,
            gross_total=result.gross_total,
            deposit_amount=deposit,
            deposit_applied=money(applied),
            payable_gross=money(result.gross_total - applied),
            name=result.name,
            billing_cycle_months=result.billing_cycle_months,
        )
