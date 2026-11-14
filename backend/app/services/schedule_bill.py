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
from app.services.scheduling import SLOT, SLOT_HOURS


def _local(moment: datetime) -> datetime:
    """Początek kwadransa jak `measured_at` odczytów: czas lokalny bez strefy."""
    return moment.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)


def grid_limit_note(readings: Iterable, max_grid_kw: float | None) -> str | None:
    """Ostrzeżenie, gdy już odczyty z pliku (pobór z sieci) przekraczają limit przyłącza z profilu.

    Optymalizacja tylko przesuwa urządzenia, więc przy limicie niższym niż faktyczny pobór domu zostawia
    wiele z nich na miejscu jako konflikt; wtedy najpewniej moc umowna w profilu jest za niska.
    """
    if not max_grid_kw:
        return None
    powers = [float(reading.energy_kwh) / SLOT_HOURS for reading in readings]
    over = [power for power in powers if power > max_grid_kw + 1e-9]
    if not over:
        return None
    limit, peak = (f"{value:.1f}".replace(".", ",") for value in (max_grid_kw, max(over)))
    return (
        f"W wybranym okresie dom pobierał z sieci więcej niż {limit} kW (moc umowna z profilu) w {len(over)} "
        f"kwadransach, najwięcej {peak} kW. Optymalizacja nie zmniejsza poboru, tylko przesuwa urządzenia, "
        "więc przy tym limicie wiele z nich zostaje na miejscu. Sprawdź moc umowną w profilu."
    )


def padded_readings(readings: list, actions: Iterable) -> list:
    """Odczyty uzupełnione zerowymi kwadransami, których dotyka akcja przed albo po przesunięciu.

    Rachunek bierze okres z dat odczytów: bez tego kwadrans po końcu pliku, na który trafiła akcja,
    dodałby rachunkowi „po” dobę opłat stałych, której „przed” nie ma.
    """
    known = {reading.measured_at for reading in readings}
    touched = set()
    for action in actions:
        touched.update(_local(action.original_start + index * SLOT) for index in range(len(action.original_profile_kwh)))
        touched.update(_local(action.start + index * SLOT) for index in range(len(action.profile_kwh)))
    return [
        *readings,
        *(SimpleNamespace(measured_at=moment, energy_kwh=Decimal("0"), exported_kwh=Decimal("0"))
          for moment in sorted(touched - known)),
    ]


def shifted_readings(readings: Iterable, actions: Iterable) -> list[SimpleNamespace]:
    net: dict[datetime, Decimal] = {}
    for reading in readings:
        net[reading.measured_at] = net.get(reading.measured_at, Decimal("0")) + (
            Decimal(str(reading.energy_kwh)) - Decimal(str(reading.exported_kwh or 0))
        )
    for action in actions:
        # Ładowanie EV zmienia też kształt profilu (przerwy), więc porównujemy oba profile, nie tylko start.
        original_profile = action.original_profile_kwh
        if action.start == action.original_start and action.profile_kwh == original_profile:
            continue
        for index, kwh in enumerate(original_profile):
            old = _local(action.original_start + index * SLOT)
            net[old] = net.get(old, Decimal("0")) - Decimal(str(kwh))
        for index, kwh in enumerate(action.profile_kwh):
            new = _local(action.start + index * SLOT)
            net[new] = net.get(new, Decimal("0")) + Decimal(str(kwh))
    return [
        SimpleNamespace(
            measured_at=moment,
            energy_kwh=max(balance, Decimal("0")),
            exported_kwh=max(-balance, Decimal("0")),
        )
        for moment, balance in sorted(net.items())
    ]
