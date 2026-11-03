from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable
from dateutil.relativedelta import relativedelta

from app.schemas.calculation import CalculationDetails
from app.schemas.other import PhaseTypeEnum


CENT = Decimal("0.01")
DEFAULT_VAT_RATE = Decimal("0.23")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TariffCycleResult:
    cycle_start: datetime
    cycle_end: datetime
    active_energy_kwh: Decimal
    active_energy_net: Decimal
    variable_network_net: Decimal
    fixed_network_net: Decimal
    subscription_net: Decimal
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
                    "active_energy_kwh": float(cycle.active_energy_kwh),
                    "active_energy_net": float(cycle.active_energy_net),
                    "variable_network_net": float(cycle.variable_network_net),
                    "fixed_network_net": float(cycle.fixed_network_net),
                    "subscription_net": float(cycle.subscription_net),
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


class ZonedTariffCalculationStrategy:
    """Calculates a tariff definition against balanced energy grouped by zones."""

    def __init__(self, vat_rate: Decimal = DEFAULT_VAT_RATE):
        if vat_rate < 0:
            raise ValueError("VAT rate cannot be negative.")
        self.vat_rate = vat_rate
        self.dynamic_price_resolver = None

    def set_dynamic_price_resolver(self, resolver):
        self.dynamic_price_resolver = resolver

    def calculate(
        self,
        calculation_details: CalculationDetails,
        tariff_definition: Any,
    ) -> TariffCalculationResult:
        cycles = []
        expected_zones = tariff_definition.number_of_zones
        energy_rates = self._rates_by_zone(tariff_definition.supplier_ure_rates, "energy_price_per_kwh_net_pln")
        network_rates = self._rates_by_zone(
            tariff_definition.variable_network_rates, "rate_per_kwh_net_pln"
        )
        is_dynamic = tariff_definition.tariff_code.value == "dynamic"
        if (not is_dynamic and len(energy_rates) != expected_zones) or len(network_rates) != expected_zones:
            raise ValueError("Brak kompletu stawek dla wszystkich stref taryfowych.")
        if is_dynamic and self.dynamic_price_resolver is None:
            raise ValueError("Brak resolvera cen RCE dla taryfy dynamicznej.")

        fixed_network = (
            tariff_definition.fixed_network_fee_1phase_monthly
            if calculation_details.tariff_data.phase_type == PhaseTypeEnum.SINGLE_PHASE
            else tariff_definition.fixed_network_fee_3phase_monthly
        )
        subscription = self._subscription_fee(
            tariff_definition.subscription_fees,
            calculation_details.tariff_data.billing_cycle.value,
        )

        for cycle_start, energy in self._cycles(calculation_details):
            zone_energy = self._zone_totals(energy, expected_zones)
            active_kwh = sum(zone_energy, Decimal("0"))
            if is_dynamic and isinstance(energy, dict):
                active_net = sum(
                    (
                        Decimal(str(value))
                        * Decimal(str(self.dynamic_price_resolver(timestamp)))
                        for timestamp, value in energy.items()
                    ),
                    Decimal("0"),
                )
            elif is_dynamic and isinstance(energy, list) and (
                not energy or isinstance(energy[0], tuple)
            ):
                active_net = sum(
                    (
                        Decimal(str(value))
                        * Decimal(str(self.dynamic_price_resolver(timestamp)))
                        for timestamp, value in energy
                    ),
                    Decimal("0"),
                )
            elif is_dynamic:
                raise ValueError(
                    "Taryfa dynamiczna wymaga zużycia z zachowanymi znacznikami czasu."
                )
            else:
                active_net = sum(
                    (zone_energy[index] * energy_rates[index + 1] for index in range(expected_zones)),
                    Decimal("0"),
                )
            network_net = sum(
                (zone_energy[index] * network_rates[index + 1] for index in range(expected_zones)),
                Decimal("0"),
            )
            fixed_net = Decimal(fixed_network) * calculation_details.tariff_data.billing_cycle.value
            subscription_net = Decimal(subscription) * calculation_details.tariff_data.billing_cycle.value
            net_total = active_net + network_net + fixed_net + subscription_net
            vat = net_total * self.vat_rate
            cycles.append(
                TariffCycleResult(
                    cycle_start=cycle_start,
                    cycle_end=cycle_start
                    + relativedelta(
                        months=calculation_details.tariff_data.billing_cycle.value
                    )
                    - relativedelta(days=1),
                    active_energy_kwh=active_kwh,
                    active_energy_net=money(active_net),
                    variable_network_net=money(network_net),
                    fixed_network_net=money(fixed_net),
                    subscription_net=money(subscription_net),
                    net_total=money(net_total),
                    vat=money(vat),
                    gross_total=money(net_total + vat),
                )
            )

        active_energy_gross = money(
            sum((cycle.active_energy_net for cycle in cycles), Decimal("0"))
            * (Decimal("1") + self.vat_rate)
        )
        gross_total = money(sum((cycle.gross_total for cycle in cycles), Decimal("0")))
        return TariffCalculationResult(
            cycles=tuple(cycles),
            active_energy_gross=active_energy_gross,
            gross_total=gross_total,
            payable_gross=gross_total,
        )

    @staticmethod
    def _rates_by_zone(rates: Iterable[Any], field: str) -> dict[int, Decimal]:
        return {
            int(rate.zone_index): Decimal(str(getattr(rate, field)))
            for rate in rates
        }

    @staticmethod
    def _cycles(calculation_details: CalculationDetails) -> Iterable[tuple[datetime, Any]]:
        energy_cycles = calculation_details.used_energy_cycles or []
        if energy_cycles and isinstance(energy_cycles[0], dict):
            start = calculation_details.tariff_data.billing_period_start_date
            for index, energy in enumerate(energy_cycles):
                cycle_start = start + relativedelta(
                    months=index * calculation_details.tariff_data.billing_cycle.value
                )
                yield datetime.combine(cycle_start, time.min), energy
            return
        yield from energy_cycles

    @staticmethod
    def _subscription_fee(fees: Iterable[Any], months: int) -> Decimal:
        for fee in fees:
            if fee.billing_cycle_months == months:
                return Decimal(str(fee.monthly_fee_net_pln))
        raise ValueError(f"Brak opłaty abonamentowej dla cyklu {months} miesięcy.")

    @staticmethod
    def _zone_totals(energy: Any, expected_zones: int) -> list[Decimal]:
        if isinstance(energy, dict):
            totals = [Decimal("0")] * expected_zones
            for timestamp, value in energy.items():
                if not isinstance(timestamp, datetime):
                    raise ValueError("Odczyt energii musi mieć znacznik datetime.")
                totals[ZonedTariffCalculationStrategy._zone_for(timestamp, expected_zones)] += Decimal(str(value))
            return totals
        values = list(energy)
        if values and isinstance(values[0], tuple):
            totals = [Decimal("0")] * expected_zones
            for timestamp, value in values:
                if not isinstance(timestamp, datetime):
                    raise ValueError("Odczyt energii musi mieć znacznik datetime.")
                totals[ZonedTariffCalculationStrategy._zone_for(timestamp, expected_zones)] += Decimal(str(value))
            return totals
        if len(values) != expected_zones:
            raise ValueError("Zbilansowana energia nie pasuje do liczby stref taryfowych.")
        return [Decimal(str(value)) for value in values]

    @staticmethod
    def _zone_for(timestamp: datetime, zones: int) -> int:
        """Fallback time mapping for raw 15-minute series; balanced zone totals remain authoritative."""
        hour = timestamp.hour
        if zones == 1:
            return 0
        if zones == 2:
            return 0 if 6 <= hour < 22 else 1
        if zones == 3:
            return min((hour // 8), 2)
        return min((hour // 6), 3)


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
