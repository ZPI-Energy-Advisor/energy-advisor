from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from collections import deque
from typing import Callable

from app.schemas.other import BillingCycleEnum, PVTypeEnum, TariffTypeEnum, TypeOfMarketEnergyEnum
from app.parsers.devices import LOCAL_TIMEZONE
from app.providers.prices.pse_provider import PseRcePriceProvider



PV_ENERGY_VALIDITY_DAYS = 365
RCEM_SOURCE = "pse_rcem"

def get_deadline_date(start_date: datetime, billing_cycle: BillingCycleEnum, additional_days: int) -> datetime:
    next_cycle_start_date = start_date + relativedelta(months=billing_cycle.value)

    if additional_days in (365, 366):
        return next_cycle_start_date + relativedelta(years=1)
    
    return next_cycle_start_date + relativedelta(days=additional_days)


class DynamicMarketPriceResolver:
    """Reads RCE interval prices and RCEm monthly averages from stored observations."""

    def __init__(self, price_repository):
        self.price_repository = price_repository

    def __call__(
        self,
        timestamp: datetime,
        type_of_market_energy: TypeOfMarketEnergyEnum,
    ) -> float:
        day = timestamp.date()
        if type_of_market_energy == TypeOfMarketEnergyEnum.RCE:
            # Odczyty są zapisane w czasie lokalnym bez strefy, a ceny RCE w UTC.
            utc_timestamp = timestamp
            if utc_timestamp.tzinfo is None:
                utc_timestamp = utc_timestamp.replace(tzinfo=LOCAL_TIMEZONE)
            prices = self.price_repository.get_prices_between(
                PseRcePriceProvider.source,
                utc_timestamp,
                utc_timestamp + timedelta(minutes=15),
            )
            if not prices:
                raise ValueError(f"Brak ceny RCE dla interwału {timestamp.isoformat()}.")
            return float(next(iter(prices.values()))) / 1000.0

        price = self.price_repository.get_rcem_price(RCEM_SOURCE, day)
        if price is None:
            raise ValueError(f"Brak oficjalnej ceny RCEm dla miesiąca {day.replace(day=1).isoformat()}.")
        return float(price) / 1000.0


class PVBalancingEngine:
    def __init__(
        self,
        market_price_resolver: Callable[[datetime, TypeOfMarketEnergyEnum], float] | None = None,
    ):
        self.market_price_resolver = market_price_resolver

    @staticmethod
    def get_energy_price_zones(tariff_type: TariffTypeEnum) -> list[float]:
        """Relative prices used to prioritize PV energy in net-metering."""
        if tariff_type == TariffTypeEnum.G11:
            return [1.0]
        if tariff_type in (TariffTypeEnum.G12, TariffTypeEnum.G12W):
            return [1.0, 0.6]
        if tariff_type in (TariffTypeEnum.G13, TariffTypeEnum.G13S):
            return [1.0, 0.75, 0.5]
        if tariff_type == TariffTypeEnum.G14D:
            return [1.0, 0.8, 0.6, 0.4]
        if tariff_type == TariffTypeEnum.DYNAMIC:
            return [1.0]
        raise ValueError(f"Brak mapowania stref dla taryfy {tariff_type.value}.")

    @staticmethod
    def get_grouped_energy_by_zones(
        energy_records: list[tuple[datetime, float]],
        tariff_type: TariffTypeEnum,
    ) -> list[float]:
        """Aggregate hourly records into the tariff's deterministic time zones."""
        zone_count = len(PVBalancingEngine.get_energy_price_zones(tariff_type))
        grouped = [0.0] * zone_count
        for timestamp, energy_kwh in energy_records:
            grouped[PVBalancingEngine._zone_for(timestamp, tariff_type)] += energy_kwh
        return grouped

    @staticmethod
    def _zone_for(timestamp: datetime, tariff_type: TariffTypeEnum) -> int:
        weekday = timestamp.weekday()
        minutes = timestamp.hour * 60 + timestamp.minute
        if tariff_type == TariffTypeEnum.G11:
            return 0
        if tariff_type == TariffTypeEnum.DYNAMIC:
            return 0
        if tariff_type == TariffTypeEnum.G12W and weekday >= 5:
            return 1
        if tariff_type in (TariffTypeEnum.G12, TariffTypeEnum.G12W):
            return 0 if 6 * 60 <= minutes < 13 * 60 or 15 * 60 <= minutes < 22 * 60 else 1
        if tariff_type in (TariffTypeEnum.G13, TariffTypeEnum.G13S):
            if 7 * 60 <= minutes < 13 * 60 or 16 * 60 <= minutes < 21 * 60:
                return 0
            if 13 * 60 <= minutes < 16 * 60 or 21 * 60 <= minutes < 22 * 60:
                return 1
            return 2
        if tariff_type == TariffTypeEnum.G14D:
            if 7 * 60 <= minutes < 13 * 60:
                return 0
            if 13 * 60 <= minutes < 16 * 60:
                return 1
            if 16 * 60 <= minutes < 22 * 60:
                return 2
            return 3
        raise ValueError(f"Brak mapowania stref dla taryfy {tariff_type.value}.")

    def get_price_for_pv_energy(
        self,
        timestamp: datetime,
        type_of_market_energy: TypeOfMarketEnergyEnum,
    ) -> float:
        if self.market_price_resolver is None:
            raise ValueError(
                "Brak źródła cen rynkowych dla net-billingu. "
                "Skonfiguruj resolver RCE/RCEm."
            )
        price = self.market_price_resolver(timestamp, type_of_market_energy)
        if price < 0:
            raise ValueError("Cena rynkowa energii nie może być ujemna.")
        return price

    def _remove_expired_energy(self, past_accumulated_pv_energy: deque, current_cycle_date: datetime, billing_cycle: BillingCycleEnum, pv_validity_days: int) -> None:
            while past_accumulated_pv_energy:
                oldest_packet_date = past_accumulated_pv_energy[0][1]
                deadline = get_deadline_date(oldest_packet_date, billing_cycle, pv_validity_days)
                
                if deadline <= current_cycle_date:
                    past_accumulated_pv_energy.popleft()
                else:
                    break


    def _apply_net_metering(
        self,
        pv_energy_cycles: list[tuple[datetime, list[tuple[datetime, float]]]],
        used_energy_cycles: list[tuple[datetime, list[tuple[datetime, float]]]],
        tariff_type: TariffTypeEnum,
        k_var: float,
        pv_validity_days: int,
        billing_cycle: BillingCycleEnum
    ):

        if len(pv_energy_cycles) != len(used_energy_cycles):
            raise ValueError("Liczba cykli PV nie zgadza się z liczbą cykli zużycia energii.")

        
        past_accumulated_pv_energy = deque() 
        energy_price_zones = self.get_energy_price_zones(tariff_type)
        sorted_zones_by_price = sorted(range(len(energy_price_zones)), key=lambda i: energy_price_zones[i], reverse=True)

        used_energy_after_balancing_cycles = []
        for pv_energy_tuples, used_energy_tuples in zip(pv_energy_cycles, used_energy_cycles):

            _, pv_energy_records = pv_energy_tuples
            cycle_begining_date, used_energy_records = used_energy_tuples

            # Delete expired PV energy from the virtual storage based on the current cycle date, billing cycle, and PV validity days
            self._remove_expired_energy(past_accumulated_pv_energy, cycle_begining_date, billing_cycle, pv_validity_days)

            balanced_energy = {}
            for interval_start_datetime, pv_energy_kwh in pv_energy_records:
                hourly_interval_start = interval_start_datetime.replace(minute=0, second=0, microsecond=0)
                balanced_energy[hourly_interval_start] = balanced_energy.get(hourly_interval_start, 0.0) - pv_energy_kwh

            for interval_start_datetime, used_energy_kwh in used_energy_records:
                hourly_interval_start = interval_start_datetime.replace(minute=0, second=0, microsecond=0)
                balanced_energy[hourly_interval_start] = balanced_energy.get(hourly_interval_start, 0.0) + used_energy_kwh

            # Balansing PV energy with used energy in hours 
            accumulated_pv_energy = 0.0
            used_energy_after_balancing = []
            for hourly_interval_start, energy_balance_kwh in balanced_energy.items():
                if abs(energy_balance_kwh) < 1e-9:
                    continue
                elif energy_balance_kwh > 0:
                    used_energy_after_balancing.append((hourly_interval_start, energy_balance_kwh))
                else:
                    accumulated_pv_energy += abs(energy_balance_kwh) * k_var


            used_energy_after_balancing_zones = self.get_grouped_energy_by_zones(used_energy_after_balancing, tariff_type)


            # Balancing accumulated PV energy with used energy in zones (from highest to lowest price)
            for i in sorted_zones_by_price:
                if abs(accumulated_pv_energy) <= 1e-9:
                    break

                if abs(used_energy_after_balancing_zones[i]) > 1e-9:
                    if accumulated_pv_energy >= used_energy_after_balancing_zones[i]:
                        accumulated_pv_energy -= used_energy_after_balancing_zones[i]
                        used_energy_after_balancing_zones[i] = 0.0
                    else:
                        used_energy_after_balancing_zones[i] -= accumulated_pv_energy
                        accumulated_pv_energy = 0.0  


            if abs(accumulated_pv_energy) > 1e-9:
                past_accumulated_pv_energy.append((accumulated_pv_energy, cycle_begining_date))
            else: 
                energy_shortage = sum(used_energy_after_balancing_zones)

                if abs(energy_shortage) > 1e-9:

                    # If there is a shortage of energy, try to cover it with the accumulated PV energy
                    while past_accumulated_pv_energy:
                        first_accumulated_energy, first_cycle_date = past_accumulated_pv_energy.popleft()

                        for i in sorted_zones_by_price:
                            if abs(first_accumulated_energy) < 1e-9:
                                break

                            if used_energy_after_balancing_zones[i] > 0:
                                if first_accumulated_energy >= used_energy_after_balancing_zones[i]:
                                    first_accumulated_energy -= used_energy_after_balancing_zones[i]
                                    used_energy_after_balancing_zones[i] = 0.0
                                else:
                                    used_energy_after_balancing_zones[i] -= first_accumulated_energy
                                    first_accumulated_energy = 0.0



                        if abs(first_accumulated_energy) > 1e-9:
                            past_accumulated_pv_energy.appendleft((first_accumulated_energy, first_cycle_date))

                        energy_shortage = sum(used_energy_after_balancing_zones)
                        if abs(energy_shortage) < 1e-9:
                            break


            used_energy_after_balancing_cycles.append((cycle_begining_date, used_energy_after_balancing_zones))

        return used_energy_after_balancing_cycles

       
    def _apply_net_billing(
        self, 
        pv_energy_cycles: list[tuple[datetime, list[tuple[datetime, float]]]],
        used_energy_cycles: list[tuple[datetime, list[tuple[datetime, float]]]], 
        type_of_market_energy: TypeOfMarketEnergyEnum
    ) -> tuple[list[dict[datetime, float]], list[dict[str, float]]]:


        if len(pv_energy_cycles) != len(used_energy_cycles):
            raise ValueError("Liczba cykli PV nie zgadza się z liczbą cykli zużycia energii.")

        # PV energy
        energy_balance_cycles = []
        for _, pv_energy_15_min_intervals in pv_energy_cycles:
            energy_balance = {}
            for interval_start_datetime, pv_energy_kwh in pv_energy_15_min_intervals:
                energy_balance[interval_start_datetime] = energy_balance.get(interval_start_datetime, 0.0) - pv_energy_kwh

            energy_balance_cycles.append(energy_balance)


        # Used energy
        for cycle_index, (_, used_energy_15_min_intervals) in enumerate(used_energy_cycles):
            energy_balance = energy_balance_cycles[cycle_index]
            for interval_start_datetime, used_energy_kwh in used_energy_15_min_intervals:
                energy_balance[interval_start_datetime] = energy_balance.get(interval_start_datetime, 0.0) + used_energy_kwh


        # Summarizing overpayment and calculating energy usage after balancing
        energy_usage_after_balancing_cycles = []
        overpayment_cycles = []
        for energy_balance in energy_balance_cycles:
            energy_usage_after_balancing = {}
            overpayment = {}

            for interval_start_datetime, energy_balance_kwh in energy_balance.items():
                if abs(energy_balance_kwh) < 1e-9: 
                    energy_usage_after_balancing[interval_start_datetime] = 0.0
                elif energy_balance_kwh > 0:
                    energy_usage_after_balancing[interval_start_datetime] = energy_balance_kwh
                else:
                    price_per_kwh = self.get_price_for_pv_energy(interval_start_datetime, type_of_market_energy)
                    overpayment_amount = max(abs(energy_balance_kwh) * price_per_kwh, 0.0)

                    interval_month_and_year = interval_start_datetime.strftime('%Y-%m')
                    overpayment[interval_month_and_year] = overpayment.get(interval_month_and_year, 0.0) + overpayment_amount

            energy_usage_after_balancing_cycles.append(energy_usage_after_balancing)
            overpayment_cycles.append(overpayment)

        return energy_usage_after_balancing_cycles, overpayment_cycles

    @staticmethod
    def _group_balanced_billing_cycles(
        balanced_cycles: list[dict[datetime, float]],
        cycle_starts: list[datetime],
        tariff_type: TariffTypeEnum,
    ) -> list[tuple[datetime, list[float]]]:
        if len(balanced_cycles) != len(cycle_starts):
            raise ValueError("Liczba zbilansowanych cykli nie zgadza się z liczbą cykli zużycia.")
        return [
            (
                cycle_start,
                PVBalancingEngine.get_grouped_energy_by_zones(
                    [
                        (timestamp, energy_kwh)
                        for timestamp, energy_kwh in balanced_energy.items()
                        if abs(energy_kwh) >= 1e-9
                    ],
                    tariff_type,
                ),
            )
            for cycle_start, balanced_energy in zip(cycle_starts, balanced_cycles)
        ]


    def balance_pv(self, calculations_details):

        if calculations_details.pv_details is None:
            return calculations_details

        if calculations_details.pv_details.mode == PVTypeEnum.NET_METERING:
            used_energy_after_balancing_cycles = self._apply_net_metering(
                pv_energy_cycles=calculations_details.pv_details.pv_energy_cycles,
                used_energy_cycles=calculations_details.used_energy_cycles,
                tariff_type=calculations_details.tariff_data.tariff_type,
                k_var=calculations_details.pv_details.k_var,
                pv_validity_days=PV_ENERGY_VALIDITY_DAYS,
                billing_cycle=calculations_details.tariff_data.billing_cycle
            )
            calculations_details.used_energy_cycles = used_energy_after_balancing_cycles
            calculations_details.used_energy_after_balancing_cycles = (
                used_energy_after_balancing_cycles
            )

        elif calculations_details.pv_details.mode == PVTypeEnum.NET_BILLING:
            energy_usage_after_balancing_cycles, overpayment_cycles = self._apply_net_billing(
                pv_energy_cycles=calculations_details.pv_details.pv_energy_cycles,
                used_energy_cycles=calculations_details.used_energy_cycles,
                type_of_market_energy=calculations_details.pv_details.type_of_market_energy
            )
            cycle_starts = [cycle_start for cycle_start, _ in calculations_details.used_energy_cycles]
            if calculations_details.tariff_data.tariff_type == TariffTypeEnum.DYNAMIC:
                calculations_details.used_energy_after_balancing_cycles = [
                    (cycle_start, list(energy.items()))
                    for cycle_start, energy in zip(cycle_starts, energy_usage_after_balancing_cycles)
                ]
                calculations_details.used_energy_cycles = energy_usage_after_balancing_cycles
            else:
                grouped_cycles = self._group_balanced_billing_cycles(
                    energy_usage_after_balancing_cycles,
                    cycle_starts,
                    calculations_details.tariff_data.tariff_type,
                )
                calculations_details.used_energy_after_balancing_cycles = grouped_cycles
                calculations_details.used_energy_cycles = grouped_cycles
            calculations_details.overpayment_cycles = overpayment_cycles

        else:
            raise ValueError("Nieobsługiwany tryb PV.")

        return calculations_details
