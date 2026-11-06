from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Sequence
from dateutil.relativedelta import relativedelta

from app.schemas.calculation import CalculationDetails
from app.schemas.other import PhaseTypeEnum, TariffTypeEnum
from app.services.tariff_zones import zone_count, zone_for


CENT = Decimal("0.01")
DAYS_IN_YEAR = 365


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


@dataclass(frozen=True)
class BillingContext:
    """Dane wspólne dla wszystkich taryf jednego pliku.

    Opłaty miesięczne są liczone tylko za dni od `first_day` do `last_day` (okres pliku), żeby
    dotyczyły tego samego czasu co energia. `raw_cycles` to zużycie przed bilansowaniem PV; służy do
    podziału energii zbilansowanej w strefach na odcinki z różnymi stawkami.
    """

    regulatory_periods: Sequence[Any]
    annual_kwh: Decimal
    first_day: date
    last_day: date
    raw_cycles: Sequence[tuple[datetime, Any]] = field(default_factory=tuple)


@dataclass(frozen=True)
class TariffCycleResult:
    cycle_start: datetime
    cycle_end: datetime
    days_billed: int
    days_in_cycle: int
    active_energy_kwh: Decimal
    active_energy_net: Decimal
    variable_network_net: Decimal
    quality_net: Decimal
    renewable_net: Decimal
    cogeneration_net: Decimal
    fixed_network_net: Decimal
    subscription_net: Decimal
    capacity_net: Decimal
    transition_net: Decimal
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycles": [
                {
                    "cycle_start": cycle.cycle_start.isoformat(),
                    "cycle_end": cycle.cycle_end.isoformat(),
                    "days_billed": cycle.days_billed,
                    "days_in_cycle": cycle.days_in_cycle,
                    "active_energy_kwh": float(cycle.active_energy_kwh),
                    "active_energy_net": float(cycle.active_energy_net),
                    "variable_network_net": float(cycle.variable_network_net),
                    "quality_net": float(cycle.quality_net),
                    "renewable_net": float(cycle.renewable_net),
                    "cogeneration_net": float(cycle.cogeneration_net),
                    "fixed_network_net": float(cycle.fixed_network_net),
                    "subscription_net": float(cycle.subscription_net),
                    "capacity_net": float(cycle.capacity_net),
                    "transition_net": float(cycle.transition_net),
                    "net_total": float(cycle.net_total),
                    "vat": float(cycle.vat),
                    "gross_total": float(cycle.gross_total),
                }
                for cycle in self.cycles
            ],
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
    "active_energy_net", "variable_network_net", "quality_net", "renewable_net", "cogeneration_net",
    "fixed_network_net", "subscription_net", "capacity_net", "transition_net",
)


class ZonedTariffCalculationStrategy:
    """Rachunek za taryfę: energia i dystrybucja w strefach, opłaty regulacyjne, opłaty miesięczne i VAT.

    Dla taryfy dynamicznej stawka energii z supplier_ure_rates (strefa 1) jest marżą sprzedawcy
    doliczaną do ceny RCE: energia netto = Σ kWh × (RCE / 1000 + marża).

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
    ) -> TariffCalculationResult:
        if not definitions:
            raise ValueError("Brak definicji taryfy.")
        definitions = sorted(definitions, key=lambda definition: definition.valid_from)
        tariff_type = definitions[0].tariff_code
        for definition in definitions:
            self._check_definition(definition, tariff_type)
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
            self._split_energy(energy, segments, tariff_type, raw_cycles.get(cycle_start))

            totals = dict.fromkeys(COMPONENTS, Decimal("0"))
            vat = Decimal("0")
            for segment in segments:
                parts = self._segment_parts(
                    segment, calculation_details, context.annual_kwh, months, days_in_cycle, tariff_type
                )
                vat_rate = Decimal(str(segment.period.vat_rate))
                vat += sum(parts.values(), Decimal("0")) * vat_rate
                active_energy_gross += parts["active_energy_net"] * (1 + vat_rate)
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
        )

    def _segment_parts(
        self,
        segment: _Segment,
        calculation_details: CalculationDetails,
        annual_kwh: Decimal,
        months: int,
        days_in_cycle: int,
        tariff_type: TariffTypeEnum,
    ) -> dict[str, Decimal]:
        definition, period = segment.definition, segment.period
        energy_rates = self._rates_by_zone(definition.supplier_ure_rates, "energy_price_per_kwh_net_pln")
        network_rates = self._rates_by_zone(definition.variable_network_rates, "rate_per_kwh_net_pln")
        zone_energy = segment.zone_energy
        kwh = sum(zone_energy, Decimal("0"))

        if tariff_type == TariffTypeEnum.DYNAMIC:
            if segment.records is None:
                raise ValueError("Taryfa dynamiczna wymaga zużycia z zachowanymi znacznikami czasu.")
            margin = energy_rates[1]
            active = sum(
                (
                    Decimal(str(value)) * (Decimal(str(self.dynamic_price_resolver(timestamp))) + margin)
                    for timestamp, value in segment.records
                ),
                Decimal("0"),
            )
        else:
            active = sum((energy * energy_rates[zone + 1] for zone, energy in enumerate(zone_energy)), Decimal("0"))

        fixed_network = (
            definition.fixed_network_fee_1phase_monthly
            if calculation_details.tariff_data.phase_type == PhaseTypeEnum.SINGLE_PHASE
            else definition.fixed_network_fee_3phase_monthly
        )
        # Część opłat miesięcznych przypadająca na dni odcinka.
        share = Decimal(months) * Decimal(len(segment.days)) / Decimal(days_in_cycle)
        return {
            "active_energy_net": active,
            "variable_network_net": sum(
                (energy * network_rates[zone + 1] for zone, energy in enumerate(zone_energy)), Decimal("0")
            ),
            "quality_net": kwh * Decimal(str(period.quality_fee_per_kwh)),
            "renewable_net": kwh * Decimal(str(period.renewable_energy_fee_per_kwh)),
            "cogeneration_net": kwh * Decimal(str(period.cogeneration_fee_per_kwh)),
            "fixed_network_net": Decimal(str(fixed_network)) * share,
            "subscription_net": self._subscription_fee(definition.subscription_fees, months) * share,
            "capacity_net": self._threshold_fee(period.capacity_thresholds, annual_kwh, "mocowej") * share,
            "transition_net": self._threshold_fee(period.transition_thresholds, annual_kwh, "przejściowej") * share,
        }

    @staticmethod
    def _check_definition(definition: Any, tariff_type: TariffTypeEnum) -> None:
        expected_zones = definition.number_of_zones
        if expected_zones != zone_count(tariff_type):
            raise ValueError(
                f"Definicja taryfy {tariff_type.value} ma {expected_zones} stref, "
                f"a godziny stref tej taryfy przewidują {zone_count(tariff_type)}."
            )
        energy_rates = ZonedTariffCalculationStrategy._rates_by_zone(
            definition.supplier_ure_rates, "energy_price_per_kwh_net_pln"
        )
        network_rates = ZonedTariffCalculationStrategy._rates_by_zone(
            definition.variable_network_rates, "rate_per_kwh_net_pln"
        )
        if len(energy_rates) != expected_zones or len(network_rates) != expected_zones:
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
        tariff_type: TariffTypeEnum,
        raw_records: Any,
    ) -> None:
        """Przypisuje energię cyklu do odcinków: odczyty po dniu, a energię już zbilansowaną w strefach
        proporcjonalnie do zużycia w strefie przed bilansowaniem PV."""
        values = list(energy.items()) if isinstance(energy, dict) else list(energy)
        if values and isinstance(values[0], tuple):
            by_day = {day: segment for segment in segments for day in segment.days}
            for segment in segments:
                segment.records = []
            for timestamp, value in values:
                if not isinstance(timestamp, datetime):
                    raise ValueError("Odczyt energii musi mieć znacznik datetime.")
                segment = by_day.get(timestamp.date())
                if segment is None:
                    raise ValueError(f"Odczyt {timestamp.isoformat()} jest poza okresem pliku.")
                segment.records.append((timestamp, value))
            for segment in segments:
                segment.zone_energy = ZonedTariffCalculationStrategy._zone_totals(segment.records, tariff_type)
            return

        zone_totals = ZonedTariffCalculationStrategy._zone_totals(values, tariff_type)
        if len(segments) == 1:
            segments[0].zone_energy = zone_totals
            return
        raw = {id(segment): [Decimal("0")] * len(zone_totals) for segment in segments}
        by_day = {day: segment for segment in segments for day in segment.days}
        for timestamp, value in raw_records or []:
            segment = by_day.get(timestamp.date())
            if segment is not None:
                raw[id(segment)][zone_for(timestamp, tariff_type)] += Decimal(str(value))
        total_days = Decimal(sum(len(segment.days) for segment in segments))
        for segment in segments:
            segment.zone_energy = []
            for zone, total in enumerate(zone_totals):
                raw_total = sum((raw[id(item)][zone] for item in segments), Decimal("0"))
                share = (
                    raw[id(segment)][zone] / raw_total if raw_total > 0 else Decimal(len(segment.days)) / total_days
                )
                segment.zone_energy.append(total * share)

    @staticmethod
    def _rates_by_zone(rates: Iterable[Any], field: str) -> dict[int, Decimal]:
        return {
            int(rate.zone_index): Decimal(str(getattr(rate, field)))
            for rate in rates
        }

    @staticmethod
    def _cycles(calculation_details: CalculationDetails) -> Iterable[tuple[datetime, Any]]:
        yield from calculation_details.used_energy_cycles or []

    @staticmethod
    def _subscription_fee(fees: Iterable[Any], months: int) -> Decimal:
        for fee in fees:
            if fee.billing_cycle_months == months:
                return Decimal(str(fee.monthly_fee_net_pln))
        raise ValueError(f"Brak opłaty abonamentowej dla cyklu {months} miesięcy.")

    @staticmethod
    def _threshold_fee(thresholds: Iterable[Any], annual_kwh: Decimal, name: str) -> Decimal:
        """Miesięczna opłata z progu, do którego należy roczne zużycie (próg od min włącznie do max wyłącznie)."""
        for threshold in thresholds:
            minimum = Decimal(str(threshold.min_kwh_annual))
            maximum = None if threshold.max_kwh_annual is None else Decimal(str(threshold.max_kwh_annual))
            if minimum <= annual_kwh and (maximum is None or annual_kwh < maximum):
                return Decimal(str(threshold.monthly_fee_net_pln))
        raise ValueError(f"Brak progu opłaty {name} dla rocznego zużycia {annual_kwh:.0f} kWh.")

    @staticmethod
    def _zone_totals(energy: Any, tariff_type: TariffTypeEnum) -> list[Decimal]:
        """Energia cyklu w strefach: z odczytów ze znacznikiem czasu albo już zbilansowana przez PV."""
        values = list(energy.items()) if isinstance(energy, dict) else list(energy)
        if values and isinstance(values[0], tuple):
            totals = [Decimal("0")] * zone_count(tariff_type)
            for timestamp, value in values:
                if not isinstance(timestamp, datetime):
                    raise ValueError("Odczyt energii musi mieć znacznik datetime.")
                totals[zone_for(timestamp, tariff_type)] += Decimal(str(value))
            return totals
        if not values:
            return [Decimal("0")] * zone_count(tariff_type)
        if len(values) != zone_count(tariff_type):
            raise ValueError("Zbilansowana energia nie pasuje do liczby stref taryfowych.")
        return [Decimal(str(value)) for value in values]


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
        )
