"""Strefy czasowe taryf z godzin zapisanych w bazie (`tariff_zone_hours`).

Strefę kwadransa wyznacza definicja taryfy ważna w dniu odczytu: rodzaj dnia (dzień roboczy, sobota, niedziela
albo dzień ustawowo wolny od pracy), sezon (`MM-DD`–`MM-DD`) i minuta doby. Z tego samego harmonogramu korzysta
silnik taryf i bilansowanie PV, więc energia zawsze trafia do tych samych stref.

Godziny stosujemy do czasu lokalnego odczytów (pliki z liczników zdalnego odczytu mają czas CET/CEST). W dobie
zmiany czasu na zimowy oba wystąpienia godziny 02:00–03:00 są już zsumowane w jednym lokalnym kwadransie, a w
dobie zmiany na letni tej godziny nie ma — strefa zależy wyłącznie od lokalnej godziny zegarowej.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

from app.services.polish_holidays import day_type
from app.tariff_data.files import season_contains


def covers(item: Any, day: date) -> bool:
    return item.valid_from <= day <= item.valid_to


class ZoneSchedule:
    """Harmonogram stref jednej taryfy z jej definicji (każda definicja ma własne godziny i stawki)."""

    def __init__(self, definitions: Sequence[Any]):
        if not definitions:
            raise ValueError("Brak definicji taryfy.")
        self.definitions = sorted(definitions, key=lambda definition: definition.valid_from)
        counts = {int(definition.number_of_zones) for definition in self.definitions}
        if len(counts) != 1:
            raise ValueError("Definicje taryfy w okresie pliku mają różną liczbę stref.")
        self.zone_count = counts.pop()
        self.tariff_code = getattr(self.definitions[0].tariff_code, "value", self.definitions[0].tariff_code)
        self._intervals: dict[date, tuple[tuple[int, int, int], ...]] = {}

    def definition_for(self, day: date) -> Any | None:
        return next((definition for definition in self.definitions if covers(definition, day)), None)

    def intervals(self, day: date) -> tuple[tuple[int, int, int], ...]:
        """Przedziały (od minuty, do minuty, strefa od 1) obowiązujące w danym dniu."""
        if day not in self._intervals:
            definition = self.definition_for(day)
            if definition is None:
                raise ValueError(f"Brak stawek taryfy {self.tariff_code} dla dnia {day.isoformat()}.")
            kind = day_type(day)
            month_day = day.strftime("%m-%d")
            rows = tuple(
                sorted(
                    (int(hour.start_minute), int(hour.end_minute), int(hour.zone_index))
                    for hour in definition.zone_hours
                    if hour.day_type == kind and season_contains((hour.season_from, hour.season_to), month_day)
                )
            )
            if not rows:
                raise ValueError(f"Taryfa {self.tariff_code} nie ma godzin stref dla dnia {day.isoformat()}.")
            wrong = sorted({zone for _, _, zone in rows if not 1 <= zone <= self.zone_count})
            if wrong:
                # Bez tego energia trafiłaby poza listę stref (IndexError) albo do strefy bez stawek.
                raise ValueError(
                    f"Godziny stref taryfy {self.tariff_code} dla dnia {day.isoformat()} wskazują strefę "
                    f"{', '.join(str(zone) for zone in wrong)} spoza liczby stref definicji ({self.zone_count})."
                )
            self._intervals[day] = rows
        return self._intervals[day]

    def zone_index(self, timestamp: datetime) -> int:
        """Strefa (numerowana od 1, jak zone_index stawek) kwadransa zaczynającego się o `timestamp`."""
        minute = timestamp.hour * 60 + timestamp.minute
        for start, end, zone in self.intervals(timestamp.date()):
            if start <= minute < end:
                return zone
        raise ValueError(
            f"Godzina {timestamp:%H:%M} dnia {timestamp.date().isoformat()} nie należy do żadnej strefy "
            f"taryfy {self.tariff_code}."
        )

    def zone_prices(self, day: date) -> list[Decimal]:
        """Cena strefy dla odbiorcy (cena energii z definicji ograniczona ceną maksymalną + dystrybucja zmienna)
        z definicji ważnej w dniu `day`; lista od strefy 1. Służy tylko do kolejności stref przy net-meteringu:
        akcyza i opłaty za kWh są jednakowe we wszystkich strefach, więc ich pomijamy."""
        definition = self.definition_for(day)
        if definition is None:
            raise ValueError(f"Brak stawek taryfy {self.tariff_code} dla dnia {day.isoformat()}.")
        energy = {int(rate.zone_index): Decimal(str(rate.energy_price_per_kwh_net_pln)) for rate in definition.supplier_ure_rates}
        network = {int(rate.zone_index): Decimal(str(rate.rate_per_kwh_net_pln)) for rate in definition.variable_network_rates}
        cap = getattr(definition, "energy_price_cap_per_kwh", None)
        prices = []
        for zone in range(1, self.zone_count + 1):
            price = energy.get(zone, Decimal("0"))
            if cap is not None:
                price = min(price, Decimal(str(cap)))
            prices.append(price + network.get(zone, Decimal("0")))
        return prices

    def first_day(self) -> date:
        return self.definitions[0].valid_from
