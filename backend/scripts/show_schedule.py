"""Pokazuje wynik harmonogramowania dla pliku urządzeń: co się przesunęło i ile to daje.

Ceny to plik JSON {"start": "...", "prices_pln_kwh": [...]} z ceną dla kolejnych kwadransów.

Użycie (z katalogu projektu):
    python backend/scripts/show_schedule.py backend/tests/fixtures/scheduling_demo.json \
        backend/tests/fixtures/scheduling_demo_prices.json
    python backend/scripts/show_schedule.py plik.json ceny.json --max-grid-kw 9 --out wynik.json
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.parsers import parse_energy_file  # noqa: E402
from app.services.scheduling import SLOT, actions_from_devices, schedule  # noqa: E402

LOCAL = ZoneInfo("Europe/Warsaw")
HOURS = range(24)
# Poziomy ceny na osi czasu: od najtańszej do najdroższej.
PRICE_LEVELS = " .:-=+*#"


def load_prices(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    start = datetime.fromisoformat(data["start"])
    return {start + index * SLOT: price for index, price in enumerate(data["prices_pln_kwh"])}


def clock(moment: datetime) -> str:
    return moment.astimezone(LOCAL).strftime("%d.%m %H:%M")


def hours_of(start: datetime, end: datetime, day: date) -> set[int]:
    hours, slot = set(), start
    while slot < end:
        local = slot.astimezone(LOCAL)
        if local.date() == day:
            hours.add(local.hour)
        slot += SLOT
    return hours


def timeline(items, names: dict, prices: dict, day: date) -> list[str]:
    """Oś 24 godzin: wiersz cen, a pod nim dla każdego urządzenia układ przed i po."""
    hourly = {}
    for slot, price in prices.items():
        local = slot.astimezone(LOCAL)
        if local.date() == day:
            hourly.setdefault(local.hour, []).append(price)
    averages = {hour: sum(values) / len(values) for hour, values in hourly.items()}
    low, high = min(averages.values()), max(averages.values())
    level = lambda price: PRICE_LEVELS[int((price - low) / (high - low or 1) * (len(PRICE_LEVELS) - 1))]  # noqa: E731

    lines = [f"{day:%d.%m}".ljust(25) + "".join(f"{hour:<3d}" for hour in HOURS)]
    lines.append("cena (spacja = tanio)".ljust(25) + "".join(level(averages[h]) * 3 if h in averages else "   " for h in HOURS))
    for device_id, name in names.items():
        device_items = [item for item in items if item.device_id == device_id]
        before = set().union(*[hours_of(i.original_start, i.original_start + (i.end - i.start), day) for i in device_items], set())
        after = set().union(*[hours_of(i.start, i.end, day) for i in device_items], set())
        if not before and not after:
            continue
        lines.append(f"{name} przed".ljust(25) + "".join("###" if h in before else " . " for h in HOURS))
        lines.append(f"{name} po".ljust(25) + "".join("###" if h in after else " . " for h in HOURS))
    return lines


def result_document(result) -> dict:
    """Wynik jako JSON: dla ekranu optymalizacji i planu dla huba."""
    return {
        "cost_before": round(result.cost_before, 4),
        "cost_after": round(result.cost_after, 4),
        "actions": [
            {
                "action_id": item.action_id,
                "device_id": item.device_id,
                "program_id": item.program_id,
                "original_start": item.original_start.astimezone(LOCAL).isoformat(),
                "start": item.start.astimezone(LOCAL).isoformat(),
                "end": item.end.astimezone(LOCAL).isoformat(),
                "profile_kwh": item.profile_kwh,
                "cost_before": None if item.cost_before is None else round(item.cost_before, 4),
                "cost_after": None if item.cost_after is None else round(item.cost_after, 4),
                "status": item.status,
                "reason": item.reason,
            }
            for item in result.actions
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Wynik harmonogramowania dla pliku urządzeń.")
    parser.add_argument("devices", help="plik urządzeń (JSON)")
    parser.add_argument("prices", help="ceny kwadransów (JSON)")
    parser.add_argument("--max-grid-kw", type=float, default=None, help="limit mocy przyłącza")
    parser.add_argument("--out", help="zapisuje wynik do pliku JSON")
    args = parser.parse_args()

    with open(args.devices, "rb") as handle:
        devices = parse_energy_file(handle).devices
    names = {device.device_id: device.name for device in devices}
    prices = load_prices(args.prices)
    result = schedule(actions_from_devices(devices), prices, args.max_grid_kw)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(result_document(result), handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    print(f"{'urządzenie':<14}{'akcja':<10}{'przed':<14}{'po':<14}{'koszt przed':>12}{'koszt po':>10}  status")
    for item in result.actions:
        after = f"{item.cost_after:.2f} zł" if item.cost_after is not None else "-"
        before = f"{item.cost_before:.2f} zł" if item.cost_before is not None else "-"
        status = f"{item.status} ({item.reason})" if item.reason else item.status
        print(f"{names[item.device_id]:<14}{item.action_id:<10}{clock(item.original_start):<14}"
              f"{clock(item.start):<14}{before:>12}{after:>10}  {status}")

    saved = result.cost_before - result.cost_after
    percent = saved / result.cost_before * 100 if result.cost_before else 0
    print(f"\nKoszt przed: {result.cost_before:.2f} zł, po: {result.cost_after:.2f} zł, "
          f"oszczędność: {saved:.2f} zł ({percent:.0f}%)\n")

    days = sorted({item.original_start.astimezone(LOCAL).date() for item in result.actions})
    for day in days:
        print("\n".join(timeline(result.actions, names, prices, day)))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
