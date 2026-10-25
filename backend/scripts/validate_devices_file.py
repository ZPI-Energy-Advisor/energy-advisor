"""Sprawdza plik urządzeń (JSON) z regułami formatu i wypisuje podsumowanie.

Reguły opisuje docs/devices-file-format.md.

Użycie (z katalogu projektu):
    python backend/scripts/validate_devices_file.py frontend/public/samples/devices-example.json
    python backend/scripts/validate_devices_file.py plik.json --max-grid-kw 12

Zwraca kod 0, gdy plik jest poprawny, i 1, gdy znaleziono błędy.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta

SLOT = timedelta(minutes=15)
SLOT_HOURS = 0.25
# Pola dozwolone w obiekcie flexibility dla każdego trybu.
FLEXIBILITY_FIELDS = {
    "fixed": {"mode"},
    "shiftable": {"mode", "allowed_window", "max_shift_min"},
    "interruptible": {"mode", "allowed_window"},
}
DEVICE_CATEGORIES = {"AGD", "Ogrzewanie", "OZE", "Oświetlenie", "RTV/IT", "Pojazd elektryczny", "Inne"}
DEVICE_TYPES = {
    "washing_machine", "tumble_dryer", "dishwasher", "fridge", "freezer", "induction_hob", "oven",
    "microwave", "kettle", "coffee_machine", "heat_pump", "electric_heater", "water_heater", "ventilation",
    "pv_inverter", "light", "tv", "computer", "router", "ev_charger", "vacuum_cleaner", "hair_dryer", "other",
}
PRODUCER_CATEGORY = "OZE"
ENERGY_TOLERANCE_KWH = 0.005
POWER_TOLERANCE_KWH = 1e-9


def parse_time(value: str, label: str, errors: list[str]) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        errors.append(f"{label}: niepoprawna data {value!r}")
        return None
    if parsed.utcoffset() is None:
        errors.append(f"{label}: brak strefy czasowej w {value!r}")
        return None
    return parsed


def on_slot_boundary(moment: datetime) -> bool:
    return moment.minute % 15 == 0 and moment.second == 0 and moment.microsecond == 0


def is_clock_time(value) -> bool:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except (TypeError, ValueError):
        return False
    return parsed.minute % 15 == 0


def validate_devices(document: dict, errors: list[str]) -> dict:
    devices = {}
    for device in document.get("devices", []):
        device_id = device.get("device_id")
        if device_id in devices:
            errors.append(f"{device_id}: zduplikowane device_id")
            continue
        devices[device_id] = device

        if device.get("device_type") not in DEVICE_TYPES:
            errors.append(f"{device_id}: nieznany device_type {device.get('device_type')!r}")
        if device.get("device_category") not in DEVICE_CATEGORIES:
            errors.append(f"{device_id}: nieznana device_category {device.get('device_category')!r}")

        flexibility = device.get("flexibility", {})
        mode = flexibility.get("mode")
        if mode not in FLEXIBILITY_FIELDS:
            errors.append(f"{device_id}: nieznany tryb flexibility {mode!r}")
        elif set(flexibility) - FLEXIBILITY_FIELDS[mode]:
            extra = ", ".join(sorted(set(flexibility) - FLEXIBILITY_FIELDS[mode]))
            errors.append(f"{device_id}: tryb {mode} nie obsługuje pól: {extra}")
        for bound in ("from", "to"):
            value = flexibility.get("allowed_window", {}).get(bound)
            if "allowed_window" in flexibility and not is_clock_time(value):
                errors.append(f"{device_id}: allowed_window.{bound} musi mieć format HH:MM w pełnym kwadransie")

        programs = device.get("programs", [])
        if not programs and "max_power_kw" not in device:
            errors.append(f"{device_id}: urządzenie bez programów musi mieć max_power_kw")
        if mode == "fixed" and programs:
            errors.append(f"{device_id}: urządzenie fixed nie może mieć programów")
        for program in programs:
            if len(program["profile_kwh"]) * 15 != program["duration_min"]:
                errors.append(
                    f"{device_id}/{program['program_id']}: profil ma {len(program['profile_kwh'])} kwadransów, "
                    f"a program trwa {program['duration_min']} min"
                )
    return devices


def action_profile(action: dict, device: dict, slots: int) -> list[float]:
    if "profile_kwh" in action:
        return action["profile_kwh"]
    programs = {program["program_id"]: program for program in device.get("programs", [])}
    if action.get("program_id") in programs:
        return programs[action["program_id"]]["profile_kwh"]
    return [action["energy_kwh"] / slots] * slots


def validate_actions(document: dict, devices: dict, period: tuple, errors: list[str]) -> tuple:
    period_start, period_end = period
    seen_ids = set()
    ranges = defaultdict(list)
    grid_load = defaultdict(float)
    category_energy = defaultdict(lambda: defaultdict(float))

    for action in document.get("energy_usage", []):
        action_id = action.get("action_id")
        if action_id in seen_ids:
            errors.append(f"{action_id}: zduplikowane action_id")
        seen_ids.add(action_id)

        device = devices.get(action.get("device_id"))
        if device is None:
            errors.append(f"{action_id}: nieznane urządzenie {action.get('device_id')!r}")
            continue

        start = parse_time(action.get("action_start"), f"{action_id}.action_start", errors)
        end = parse_time(action.get("action_end"), f"{action_id}.action_end", errors)
        if start is None or end is None:
            continue
        if not (period_start <= start < end <= period_end):
            errors.append(f"{action_id}: akcja wykracza poza period albo kończy się przed startem")
            continue
        if not (on_slot_boundary(start) and on_slot_boundary(end)):
            errors.append(f"{action_id}: start i koniec muszą wypadać na pełnym kwadransie")
            continue

        slots = int((end - start) / SLOT)
        energy = action["energy_kwh"]
        if (energy < 0) != (device["device_category"] == PRODUCER_CATEGORY):
            errors.append(f"{action_id}: ujemna energia jest dozwolona tylko dla kategorii {PRODUCER_CATEGORY}")

        has_programs = bool(device.get("programs"))
        if ("program_id" in action) != has_programs:
            errors.append(f"{action_id}: program_id jest wymagany dokładnie dla urządzeń z programami")
            continue
        if has_programs and action["program_id"] not in {p["program_id"] for p in device["programs"]}:
            errors.append(f"{action_id}: nieznany program {action['program_id']!r}")
            continue

        profile = action_profile(action, device, slots)
        if len(profile) != slots:
            errors.append(f"{action_id}: profil ma {len(profile)} kwadransów, a akcja trwa {slots}")
            continue
        if abs(sum(profile) - energy) > ENERGY_TOLERANCE_KWH:
            errors.append(f"{action_id}: suma profilu {sum(profile):.2f} kWh różni się od energy_kwh {energy:.2f}")
        if "max_power_kw" in device:
            slot_limit = device["max_power_kw"] * SLOT_HOURS
            if max(abs(value) for value in profile) > slot_limit + POWER_TOLERANCE_KWH:
                errors.append(f"{action_id}: przekroczona moc maksymalna {device['max_power_kw']} kW")

        if device["device_type"] == "ev_charger":
            validate_ev_session(action, start, end, errors)
        elif "plugged_in" in action or "deadline" in action:
            errors.append(f"{action_id}: plugged_in i deadline są dozwolone tylko dla ładowarki EV")

        ranges[action["device_id"]].append((start, end, action_id))
        for index, value in enumerate(profile):
            slot = start + index * SLOT
            grid_load[slot] += max(value, 0)
            category_energy[slot.date()][device["device_category"]] += value

    for device_id, device_ranges in ranges.items():
        device_ranges.sort()
        for (_, previous_end, previous_id), (next_start, _, next_id) in zip(device_ranges, device_ranges[1:]):
            if next_start < previous_end:
                errors.append(f"{device_id}: akcje {previous_id} i {next_id} nakładają się")

    return ranges, grid_load, category_energy


def validate_ev_session(action: dict, start: datetime, end: datetime, errors: list[str]) -> None:
    action_id = action["action_id"]
    if "deadline" not in action:
        errors.append(f"{action_id}: sesja EV wymaga deadline")
        return
    plugged_in = parse_time(action.get("plugged_in", action["action_start"]), f"{action_id}.plugged_in", errors)
    deadline = parse_time(action["deadline"], f"{action_id}.deadline", errors)
    if plugged_in and deadline and not (plugged_in <= start < end <= deadline):
        errors.append(f"{action_id}: wymagane plugged_in <= action_start < action_end <= deadline")


def main() -> int:
    parser = argparse.ArgumentParser(description="Walidacja pliku urządzeń (JSON).")
    parser.add_argument("path", help="ścieżka do pliku urządzeń")
    parser.add_argument("--max-grid-kw", type=float, default=9.0, help="limit mocy przyłącza (domyślnie 9 kW)")
    args = parser.parse_args()

    try:
        with open(args.path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"Nie udało się wczytać pliku: {error}")
        return 1

    errors: list[str] = []
    period_start = parse_time(document.get("period", {}).get("start"), "period.start", errors)
    period_end = parse_time(document.get("period", {}).get("end"), "period.end", errors)
    if period_start is None or period_end is None:
        print("\n".join(errors))
        return 1

    devices = validate_devices(document, errors)
    ranges, grid_load, category_energy = validate_actions(document, devices, (period_start, period_end), errors)

    if grid_load:
        peak_slot, peak_kwh = max(grid_load.items(), key=lambda item: item[1])
        if peak_kwh > args.max_grid_kw * SLOT_HOURS + POWER_TOLERANCE_KWH:
            errors.append(f"przekroczony limit przyłącza {args.max_grid_kw} kW o {peak_slot:%d.%m %H:%M}")

    if errors:
        print(f"Znaleziono błędy ({len(errors)}):")
        print("\n".join(f"  - {error}" for error in errors))
        return 1

    actions_count = len(document.get("energy_usage", []))
    idle = sorted(set(devices) - set(ranges))
    print(f"OK: {len(devices)} urządzeń, {actions_count} akcji" + (f", bez akcji: {', '.join(idle)}" if idle else ""))
    if grid_load:
        print(f"Szczyt poboru: {peak_kwh / SLOT_HOURS:.2f} kW o {peak_slot:%d.%m %H:%M} (limit {args.max_grid_kw} kW)")
    for day, categories in sorted(category_energy.items()):
        consumption = sum(value for category, value in categories.items() if category != PRODUCER_CATEGORY)
        details = ", ".join(f"{category} {value:.2f}" for category, value in sorted(categories.items()))
        print(f"{day}: pobór {consumption:.2f} kWh | {details}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
