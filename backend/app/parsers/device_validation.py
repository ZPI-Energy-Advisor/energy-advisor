"""Reguły pliku urządzeń (JSON) z docs/devices-file-format.md.

Używa ich parser importu (app/parsers/devices.py) i skrypt CLI backend/scripts/validate_devices_file.py.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

SLOT = timedelta(minutes=15)
SLOT_HOURS = 0.25
DEFAULT_MAX_GRID_KW = 9.0

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

# Wymagane i opcjonalne pola obiektów: nazwa -> typ. "number" to int albo float (bez bool).
DEVICE_FIELDS = {"device_id": str, "device_name": str, "device_type": str, "device_category": str, "flexibility": dict}
DEVICE_OPTIONAL = {"max_power_kw": "number", "programs": list}
PROGRAM_FIELDS = {"program_id": str, "program_name": str, "duration_min": int, "profile_kwh": "numbers"}
ACTION_FIELDS = {"action_id": str, "device_id": str, "action_start": str, "action_end": str, "energy_kwh": "number"}
ACTION_OPTIONAL = {"program_id": str, "profile_kwh": "numbers", "plugged_in": str, "deadline": str}


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    devices_count: int = 0
    actions_count: int = 0
    categories: set[str] = field(default_factory=set)
    idle_devices: list[str] = field(default_factory=list)
    peak_kw: float | None = None
    peak_at: datetime | None = None
    daily_energy: dict[date, dict[str, float]] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def has_type(value, expected) -> bool:
    if expected == "number":
        return is_number(value)
    if expected == "numbers":
        return isinstance(value, list) and bool(value) and all(is_number(item) for item in value)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


TYPE_NAMES = {str: "tekst", dict: "obiekt", list: "lista", int: "liczba całkowita", "number": "liczba",
              "numbers": "niepusta lista liczb"}


def check_fields(item, label: str, required: dict, optional: dict, errors: list[str]) -> bool:
    """Sprawdza obecność i typy pól. Zwraca False, gdy obiektu nie da się dalej walidować."""
    if not isinstance(item, dict):
        errors.append(f"{label}: oczekiwano obiektu")
        return False
    valid = True
    for name, expected in required.items():
        if name not in item:
            errors.append(f"{label}: brak pola {name}")
            valid = False
        elif not has_type(item[name], expected):
            errors.append(f"{label}: pole {name} musi być typu {TYPE_NAMES[expected]}")
            valid = False
    for name, expected in optional.items():
        if name in item and not has_type(item[name], expected):
            errors.append(f"{label}: pole {name} musi być typu {TYPE_NAMES[expected]}")
            valid = False
    return valid


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


def validate_period(document: dict, errors: list[str]) -> tuple[datetime, datetime] | None:
    period = document.get("period")
    if not check_fields(period, "period", {"start": str, "end": str}, {}, errors):
        return None
    start = parse_time(period["start"], "period.start", errors)
    end = parse_time(period["end"], "period.end", errors)
    if start is None or end is None:
        return None
    if start >= end:
        errors.append("period: start musi być wcześniej niż end")
        return None
    return start, end


def validate_devices(devices_list: list, errors: list[str]) -> tuple[dict, set[str]]:
    """Zwraca poprawne strukturalnie urządzenia i ID odrzuconych (ich akcje pomijamy bez kolejnych błędów)."""
    devices, rejected = {}, set()
    for index, device in enumerate(devices_list):
        label = device.get("device_id", f"devices[{index}]") if isinstance(device, dict) else f"devices[{index}]"
        if not check_fields(device, label, DEVICE_FIELDS, DEVICE_OPTIONAL, errors):
            if isinstance(device, dict) and isinstance(device.get("device_id"), str):
                rejected.add(device["device_id"])
            continue
        device_id = device["device_id"]
        if device_id in devices:
            errors.append(f"{device_id}: zduplikowane device_id")
            continue
        if device["device_type"] not in DEVICE_TYPES:
            errors.append(f"{device_id}: nieznany device_type {device['device_type']!r}")
        if device["device_category"] not in DEVICE_CATEGORIES:
            errors.append(f"{device_id}: nieznana device_category {device['device_category']!r}")
        if "max_power_kw" in device and device["max_power_kw"] <= 0:
            errors.append(f"{device_id}: max_power_kw musi być dodatnie")

        flexibility = device["flexibility"]
        mode = flexibility.get("mode")
        if mode not in FLEXIBILITY_FIELDS:
            errors.append(f"{device_id}: nieznany tryb flexibility {mode!r}")
        elif set(flexibility) - FLEXIBILITY_FIELDS[mode]:
            extra = ", ".join(sorted(set(flexibility) - FLEXIBILITY_FIELDS[mode]))
            errors.append(f"{device_id}: tryb {mode} nie obsługuje pól: {extra}")
        if "allowed_window" in flexibility:
            window = flexibility["allowed_window"]
            for bound in ("from", "to"):
                if not isinstance(window, dict) or not is_clock_time(window.get(bound)):
                    errors.append(f"{device_id}: allowed_window.{bound} musi mieć format HH:MM w pełnym kwadransie")
        if "max_shift_min" in flexibility and not (
            has_type(flexibility["max_shift_min"], int) and flexibility["max_shift_min"] > 0
        ):
            errors.append(f"{device_id}: max_shift_min musi być dodatnią liczbą całkowitą")

        programs = device.get("programs", [])
        if not programs and "max_power_kw" not in device:
            errors.append(f"{device_id}: urządzenie bez programów musi mieć max_power_kw")
        if mode == "fixed" and programs:
            errors.append(f"{device_id}: urządzenie fixed nie może mieć programów")
        valid_programs, rejected_programs = {}, set()
        for program_index, program in enumerate(programs):
            program_label = f"{device_id}.programs[{program_index}]"
            if not check_fields(program, program_label, PROGRAM_FIELDS, {}, errors):
                if isinstance(program, dict) and isinstance(program.get("program_id"), str):
                    rejected_programs.add(program["program_id"])
                continue
            program_id = program["program_id"]
            if program_id in valid_programs:
                errors.append(f"{device_id}: zduplikowany program_id {program_id!r}")
                continue
            if len(program["profile_kwh"]) * 15 != program["duration_min"]:
                errors.append(
                    f"{device_id}/{program_id}: profil ma {len(program['profile_kwh'])} kwadransów, "
                    f"a program trwa {program['duration_min']} min"
                )
            valid_programs[program_id] = program
        devices[device_id] = {**device, "programs": valid_programs, "rejected_programs": rejected_programs}
    return devices, rejected


def action_profile(action: dict, device: dict, slots: int) -> list[float]:
    if "profile_kwh" in action:
        return action["profile_kwh"]
    if action.get("program_id") in device["programs"]:
        return device["programs"][action["program_id"]]["profile_kwh"]
    return [action["energy_kwh"] / slots] * slots


def validate_ev_session(action: dict, start: datetime, end: datetime, errors: list[str]) -> None:
    action_id = action["action_id"]
    if "deadline" not in action:
        errors.append(f"{action_id}: sesja EV wymaga deadline")
        return
    plugged_in = parse_time(action.get("plugged_in", action["action_start"]), f"{action_id}.plugged_in", errors)
    deadline = parse_time(action["deadline"], f"{action_id}.deadline", errors)
    if plugged_in and deadline and not (plugged_in <= start < end <= deadline):
        errors.append(f"{action_id}: wymagane plugged_in <= action_start < action_end <= deadline")


def validate_actions(actions: list, devices: dict, rejected: set[str], period: tuple,
                     result: ValidationResult) -> dict:
    errors = result.errors
    period_start, period_end = period
    seen_ids = set()
    ranges = defaultdict(list)
    grid_load = defaultdict(float)
    daily_energy = defaultdict(lambda: defaultdict(float))

    for index, action in enumerate(actions):
        label = action.get("action_id", f"energy_usage[{index}]") if isinstance(action, dict) else f"energy_usage[{index}]"
        if not check_fields(action, label, ACTION_FIELDS, ACTION_OPTIONAL, errors):
            continue
        action_id = action["action_id"]
        if action_id in seen_ids:
            errors.append(f"{action_id}: zduplikowane action_id")
        seen_ids.add(action_id)

        device = devices.get(action["device_id"])
        if action["device_id"] in rejected:
            continue
        if device is None:
            errors.append(f"{action_id}: nieznane urządzenie {action['device_id']!r}")
            continue

        start = parse_time(action["action_start"], f"{action_id}.action_start", errors)
        end = parse_time(action["action_end"], f"{action_id}.action_end", errors)
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

        if action.get("program_id") in device["rejected_programs"]:
            continue
        if ("program_id" in action) != bool(device["programs"] or device["rejected_programs"]):
            errors.append(f"{action_id}: program_id jest wymagany dokładnie dla urządzeń z programami")
            continue
        if device["programs"] and action["program_id"] not in device["programs"]:
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
        for slot_index, value in enumerate(profile):
            slot = start + slot_index * SLOT
            grid_load[slot] += max(value, 0)
            daily_energy[slot.date()][device["device_category"]] += value

    for device_id, device_ranges in ranges.items():
        device_ranges.sort()
        for (_, previous_end, previous_id), (next_start, _, next_id) in zip(device_ranges, device_ranges[1:]):
            if next_start < previous_end:
                errors.append(f"{device_id}: akcje {previous_id} i {next_id} nakładają się")

    result.idle_devices = sorted(set(devices) - set(ranges))
    result.daily_energy = {day: dict(categories) for day, categories in sorted(daily_energy.items())}
    return grid_load


def validate_document(document, max_grid_kw: float | None = DEFAULT_MAX_GRID_KW) -> ValidationResult:
    """Sprawdza wczytany plik urządzeń. Nie rzuca wyjątków: każdy problem trafia do `errors`.

    `max_grid_kw=None` pomija regułę limitu przyłącza (szczyt poboru jest nadal liczony).
    """
    result = ValidationResult()
    errors = result.errors
    if not isinstance(document, dict):
        errors.append("plik: oczekiwano obiektu JSON z polami period, devices i energy_usage")
        return result
    for name in ("devices", "energy_usage"):
        if not isinstance(document.get(name), list):
            errors.append(f"{name}: oczekiwano listy")
    period = validate_period(document, errors)
    if period is None or errors:
        return result

    devices, rejected = validate_devices(document["devices"], errors)
    grid_load = validate_actions(document["energy_usage"], devices, rejected, period, result)
    result.devices_count = len(devices)
    result.actions_count = len(document["energy_usage"])
    result.categories = {device["device_category"] for device in devices.values()}

    if grid_load:
        result.peak_at, peak_kwh = max(grid_load.items(), key=lambda item: item[1])
        result.peak_kw = peak_kwh / SLOT_HOURS
        if max_grid_kw is not None and peak_kwh > max_grid_kw * SLOT_HOURS + POWER_TOLERANCE_KWH:
            errors.append(f"przekroczony limit przyłącza {max_grid_kw} kW o {result.peak_at:%d.%m %H:%M}")
    return result
