"""Zwykłe zużycie reszty domu o każdej porze dnia w rachunku z PV (ZP-121): ile prądu z paneli dom zużyje sam,
zanim cokolwiek zostanie dla urządzeń z planu.

- Z plików urządzeń: średnie zużycie urządzeń stałych (lodówka, światło, płyta…) z ostatnich dni.
- Z licznika: zużycie domu (pobór − oddanie + produkcja PV, jak na ekranie „Fotowoltaika”, `pv_insights.meter_day`)
  minus średnie zużycie urządzeń elastycznych z plików urządzeń (te układa plan albo liczy doba urządzeń spoza
  planu). Bez tego dom z plikiem urządzeń z samą pralką i autem miałby prawie całą produkcję jako nadwyżkę.

O każdej porze bierzemy większą z dwóch wartości: plik urządzeń z kompletem urządzeń daje to samo co licznik,
a niepełny plik uzupełnia licznik.
"""

from datetime import date, datetime, timedelta

from app.providers.prices.base import local_day_bounds_utc
from app.services.plan_history import average_by_clock
from app.services.pv_insights import meter_day

SLOT = timedelta(minutes=15)
DEVICES = "devices"
METER = "meter"


def _quarters(day: date) -> list[datetime]:
    start, end = local_day_bounds_utc(day)
    return [start + index * SLOT for index in range(int((end - start) / SLOT))]


def rest_of_home(
    fixed: list[tuple[datetime, float]],
    flexible: list[tuple[datetime, float]],
    readings: dict,
    files_with_export: set,
    production: dict[date, dict[datetime, float]],
    days: int,
) -> tuple[dict[int, float], str]:
    """Średnie zużycie reszty domu (minuta zegarowa -> kWh w kwadransie) i skąd głównie jest (`devices`/`meter`).

    `readings`: odczyty licznika (czas lokalny -> pobór, oddanie, plik), `production`: produkcja PV z modelu
    w dniach licznika (kWh na kwadrans UTC; bez niej licznik bez oddania liczy się jak dom bez paneli)."""
    devices_average, _ = average_by_clock(fixed, days)
    meter_days = sorted({moment.date() for moment in readings})[-days:]
    house = []
    for day in meter_days:
        data = meter_day(_quarters(day), readings, production.get(day, {}), files_with_export)
        if data is not None:
            house.extend(data.consumption.items())
    if not house:
        return devices_average, DEVICES
    house_average, _ = average_by_clock(house, days)
    flexible_average, _ = average_by_clock(flexible, days)
    meter_rest = {
        minute: max(kwh - flexible_average.get(minute, 0.0), 0.0) for minute, kwh in house_average.items()
    }
    minutes = set(devices_average) | set(meter_rest)
    combined = {minute: max(devices_average.get(minute, 0.0), meter_rest.get(minute, 0.0)) for minute in minutes}
    source = METER if sum(meter_rest.values()) > sum(devices_average.values()) + 1e-9 else DEVICES
    return combined, source
