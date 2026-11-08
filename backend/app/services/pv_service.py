from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from collections import deque
from typing import Callable

from app.schemas.other import BillingCycleEnum, PVTypeEnum, TariffTypeEnum, TypeOfMarketEnergyEnum
from app.parsers.devices import LOCAL_TIMEZONE
from app.providers.prices.pse_provider import PseRcePriceProvider
from app.services.tariff_zones import ZoneSchedule



PV_ENERGY_VALIDITY_DAYS = 365

def get_deadline_date(start_date: datetime, billing_cycle: BillingCycleEnum, additional_days: int) -> datetime:
    next_cycle_start_date = start_date + relativedelta(months=billing_cycle.value)

    if additional_days in (365, 366):
        return next_cycle_start_date + relativedelta(years=1)
    
    return next_cycle_start_date + relativedelta(days=additional_days)


class DynamicMarketPriceResolver:
    """Ceny RCE (kwadrans) z zapisanych obserwacji.

    Net-billing od 1.07.2024 rozlicza energię oddaną według RCE z okresu rozliczeniowego (art. 4b ust. 2
    ustawy o OZE), a cennik zaczyna się 24.08.2024, więc miesięcznej ceny RCEm nie używamy.

    Ceny RCE wczytujemy z bazy całymi miesiącami (doba lokalna, zapis w UTC), a nie zapytaniem na każdy kwadrans —
    roczny plik to 35 tys. kwadransów. Odczyty są w czasie lokalnym bez strefy; powtórzoną godzinę doby zmiany
    czasu (zsumowaną w jednym lokalnym kwadransie) wyceniamy ceną jej pierwszego wystąpienia.
    """

    def __init__(self, price_repository):
        self.price_repository = price_repository
        self._rce_months: dict[tuple[int, int], dict[datetime, float]] = {}

    def __call__(
        self,
        timestamp: datetime,
        type_of_market_energy: TypeOfMarketEnergyEnum,
    ) -> float:
        return self.rce(timestamp)

    def rce(self, timestamp: datetime) -> float:
        local = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=LOCAL_TIMEZONE)
        local = local.astimezone(LOCAL_TIMEZONE)
        key = (local.year, local.month)
        if key not in self._rce_months:
            month_start = datetime(local.year, local.month, 1, tzinfo=LOCAL_TIMEZONE)
            month_end = month_start + relativedelta(months=1)
            prices = self.price_repository.get_prices_between(
                PseRcePriceProvider.source,
                month_start.astimezone(timezone.utc),
                month_end.astimezone(timezone.utc),
            )
            self._rce_months[key] = {
                moment.astimezone(timezone.utc): float(price) / 1000.0 for moment, price in prices.items()
            }
        price = self._rce_months[key].get(local.astimezone(timezone.utc))
        if price is None:
            raise ValueError(f"Brak ceny RCE dla interwału {timestamp.isoformat()}.")
        return price



class PVBalancingEngine:
    def __init__(
        self,
        market_price_resolver: Callable[[datetime, TypeOfMarketEnergyEnum], float] | None = None,
    ):
        self.market_price_resolver = market_price_resolver

    @staticmethod
    def zone_priority(schedule: ZoneSchedule, cycle_start: datetime) -> list[int]:
        """Strefy (indeksy od 0) od najdroższej: cena energii po cenie maksymalnej + dystrybucja zmienna z definicji
        ważnej na początku okresu (albo w pierwszym dniu, od którego mamy stawki). Energia z PV pokrywa najpierw
        zużycie w najdroższej strefie."""
        day = max(cycle_start.date(), schedule.first_day())
        prices = schedule.zone_prices(day)
        return sorted(range(len(prices)), key=lambda zone: prices[zone], reverse=True)

    @staticmethod
    def get_grouped_energy_by_zones(
        energy_records: list[tuple[datetime, float]],
        schedule: ZoneSchedule,
    ) -> list[float]:
        """Energia w strefach taryfy (lista od strefy 1) według godzin stref ważnych w dniu odczytu."""
        grouped = [0.0] * schedule.zone_count
        for timestamp, energy_kwh in energy_records:
            grouped[schedule.zone_index(timestamp) - 1] += energy_kwh
        return grouped

    def get_price_for_pv_energy(
        self,
        timestamp: datetime,
        type_of_market_energy: TypeOfMarketEnergyEnum,
    ) -> float:
        if self.market_price_resolver is None:
            raise ValueError(
                "Brak źródła cen rynkowych dla net-billingu. "
                "Skonfiguruj resolver cen RCE."
            )
        price = self.market_price_resolver(timestamp, type_of_market_energy)
        # Przy ujemnej cenie rynkowej energię wprowadzoną do sieci w tym okresie wycenia się na zero
        # (zasady net-billingu sprzedawców na podstawie art. 4b ustawy o OZE).
        return max(price, 0.0)

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
        schedule: ZoneSchedule,
        k_var: float,
        pv_validity_days: int,
        billing_cycle: BillingCycleEnum
    ):

        if len(pv_energy_cycles) != len(used_energy_cycles):
            raise ValueError("Liczba cykli PV nie zgadza się z liczbą cykli zużycia energii.")

        
        past_accumulated_pv_energy = deque() 

        used_energy_after_balancing_cycles = []
        for pv_energy_tuples, used_energy_tuples in zip(pv_energy_cycles, used_energy_cycles):

            _, pv_energy_records = pv_energy_tuples
            cycle_begining_date, used_energy_records = used_energy_tuples

            # Delete expired PV energy from the virtual storage based on the current cycle date, billing cycle, and PV validity days
            self._remove_expired_energy(past_accumulated_pv_energy, cycle_begining_date, billing_cycle, pv_validity_days)
            sorted_zones_by_price = self.zone_priority(schedule, cycle_begining_date)

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


            used_energy_after_balancing_zones = self.get_grouped_energy_by_zones(used_energy_after_balancing, schedule)


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
        schedule: ZoneSchedule,
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
                    schedule,
                ),
            )
            for cycle_start, balanced_energy in zip(cycle_starts, balanced_cycles)
        ]


    def balance_pv(self, calculations_details, schedule: ZoneSchedule):
        """Bilansuje PV w cyklach z `calculations_details`; strefy i ich kolejność bierze z `schedule` taryfy."""

        if calculations_details.pv_details is None:
            return calculations_details

        if calculations_details.pv_details.mode == PVTypeEnum.NET_METERING:
            used_energy_after_balancing_cycles = self._apply_net_metering(
                pv_energy_cycles=calculations_details.pv_details.pv_energy_cycles,
                used_energy_cycles=calculations_details.used_energy_cycles,
                schedule=schedule,
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
            else:
                calculations_details.used_energy_after_balancing_cycles = self._group_balanced_billing_cycles(
                    energy_usage_after_balancing_cycles,
                    cycle_starts,
                    schedule,
                )
            # Silnik dostaje energię ze znacznikami czasu, żeby sam podzielił ją na strefy i dni ze stawkami.
            calculations_details.used_energy_cycles = list(zip(cycle_starts, energy_usage_after_balancing_cycles))
            calculations_details.overpayment_cycles = overpayment_cycles

        else:
            raise ValueError("Nieobsługiwany tryb PV.")

        return calculations_details
