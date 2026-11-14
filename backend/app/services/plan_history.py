"""Historia zużycia z plików urządzeń jako podstawa planu na jutro (ZP-112).

Pompa ciepła: ostatni dzień z historią. Ogrzewanie zależy od pogody, a nie od dnia tygodnia, a pogoda
wczoraj jest zwykle bliższa jutrzejszej niż tydzień temu. Bez prognozy pogody to przybliżenie:
zakładamy, że jutro dom zużyje tyle co wtedy.

Reszta domu (urządzenia stałe): największy pobór o każdej porze dnia z ostatnich dni, jako rezerwa
w limicie przyłącza.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from app.parsers.devices import LOCAL_TIMEZONE


def local_day(moment: datetime) -> date:
    return moment.astimezone(LOCAL_TIMEZONE).date()


def reference_day(actions: list, plan_date: date) -> date | None:
    """Dzień z historii, który przenosimy na dzień planu: ostatni przed dniem planu (dla planu demo
    w przeszłości), a bez takiego ostatni w ogóle; None bez historii."""
    days = {local_day(action.action_start) for action in actions}
    if not days:
        return None
    earlier = [day for day in days if day < plan_date]
    return max(earlier or days)


def day_actions(actions: list, day: date) -> list:
    """Akcje, które zaczęły się danego dnia (czas lokalny)."""
    return [action for action in actions if local_day(action.action_start) == day]


def daily_energy(actions: list, day: date) -> float:
    return round(sum(action.energy_kwh for action in day_actions(actions, day)), 2)


def moved_to(moment: datetime, source_day: date, target_day: date) -> datetime:
    """Ta sama godzina zegarowa w innym dniu (czas lokalny), także przy zmianie czasu."""
    local = moment.astimezone(LOCAL_TIMEZONE)
    shifted = local.replace(tzinfo=None) + timedelta(days=(target_day - source_day).days)
    return shifted.replace(tzinfo=LOCAL_TIMEZONE)


def clock_minute(moment: datetime) -> int:
    local = moment.astimezone(LOCAL_TIMEZONE)
    return local.hour * 60 + local.minute


def peak_by_clock(slots: list[tuple[datetime, float]], days: int) -> tuple[dict[int, float], list[date]]:
    """Największy pobór (kWh w kwadransie) o każdej porze dnia z ostatnich `days` dni z danymi.

    Bierzemy maksimum, a nie średnią: rezerwa w limicie przyłącza ma wystarczyć także w gorszy dzień.
    Zwraca (minuta zegarowa -> kWh, dni, z których liczyliśmy).
    """
    per_day: dict[tuple[date, int], float] = defaultdict(float)
    for start, kwh in slots:
        per_day[(local_day(start), clock_minute(start))] += kwh
    used = sorted({day for day, _ in per_day})[-days:]
    peaks: dict[int, float] = defaultdict(float)
    for (day, minute), kwh in per_day.items():
        if day in used:
            peaks[minute] = max(peaks[minute], kwh)
    return dict(peaks), used


def average_daily_energy(actions: list, days: int) -> tuple[float | None, list[date]]:
    """Średnia energia na dobę z ostatnich `days` dni z akcjami urządzenia (np. bojlera); None bez historii."""
    per_day: dict[date, float] = defaultdict(float)
    for action in actions:
        per_day[local_day(action.action_start)] += action.energy_kwh
    used = sorted(per_day)[-days:]
    if not used:
        return None, []
    return round(sum(per_day[day] for day in used) / len(used), 2), used
