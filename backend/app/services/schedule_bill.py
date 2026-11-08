"""Zużycie z pliku po przesunięciu akcji urządzeń — do policzenia pełnego rachunku „po” optymalizacji.

Odczyt kwadransu to saldo z siecią: pobór − oddanie = zużycie − produkcja PV. Przesunięcie akcji zmienia zużycie
w dwóch kwadransach (ubywa w pierwotnym, przybywa w nowym), więc zmienia saldo; pobór i oddanie wyznaczamy z nowego
salda. Dzięki temu akcja przeniesiona na godziny nadwyżki z PV najpierw zmniejsza oddanie, a dopiero potem zwiększa
pobór, a silnik taryf liczy z tego rachunek (z bilansowaniem PV i depozytem) tak samo jak w Wynikach kalkulacji.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterable

from app.parsers.devices import LOCAL_TIMEZONE
from app.services.scheduling import SLOT


def _local(moment: datetime) -> datetime:
    """Początek kwadransa jak `measured_at` odczytów: czas lokalny bez strefy."""
    return moment.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)


def shifted_readings(readings: Iterable, actions: Iterable) -> list[SimpleNamespace]:
    net: dict[datetime, Decimal] = {}
    for reading in readings:
        net[reading.measured_at] = net.get(reading.measured_at, Decimal("0")) + (
            Decimal(str(reading.energy_kwh)) - Decimal(str(reading.exported_kwh or 0))
        )
    for action in actions:
        if action.start == action.original_start:
            continue
        for index, kwh in enumerate(action.profile_kwh):
            energy = Decimal(str(kwh))
            old = _local(action.original_start + index * SLOT)
            new = _local(action.start + index * SLOT)
            net[old] = net.get(old, Decimal("0")) - energy
            net[new] = net.get(new, Decimal("0")) + energy
    return [
        SimpleNamespace(
            measured_at=moment,
            energy_kwh=max(balance, Decimal("0")),
            exported_kwh=max(-balance, Decimal("0")),
        )
        for moment, balance in sorted(net.items())
    ]
