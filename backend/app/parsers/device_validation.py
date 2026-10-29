"""Reguły pliku urządzeń (JSON) z docs/devices-file-format.md.

Walidacja ma dwa kroki: najpierw schemat devices_file.schema.json sprawdza strukturę (pola, typy,
słowniki, formaty), potem kod poniżej sprawdza reguły łączące pola i obiekty, których schemat nie
wyrazi (suma profilu, nakładanie się akcji, istnienie urządzenia i programu, okno sesji EV, limit
przyłącza). Używają tego parser importu (app/parsers/devices.py) i skrypt CLI
backend/scripts/validate_devices_file.py.
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

SLOT = timedelta(minutes=15)
SLOT_HOURS = 0.25
DEFAULT_MAX_GRID_KW = 9.0
PRODUCER_CATEGORY = "OZE"
ENERGY_TOLERANCE_KWH = 0.005
POWER_TOLERANCE_KWH = 1e-9

SCHEMA = json.loads(Path(__file__).with_name("devices_file.schema.json").read_text(encoding="utf-8"))


def _inline_refs(node, definitions: dict):
    """Wkleja definicje z $defs w miejsca "$ref" (schemat nie ma odwołań cyklicznych ani pól obok "$ref").

    Walidator rozwiązuje "$ref" przy każdym obiekcie osobno; przy tysiącach akcji to prawie połowa czasu
    walidacji. Plik schematu zostaje czytelny, a walidator dostaje wersję bez odwołań.
    """
    if isinstance(node, dict):
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            return _inline_refs(definitions[reference.removeprefix("#/$defs/")], definitions)
        return {key: _inline_refs(value, definitions) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline_refs(item, definitions) for item in node]
    return node


SCHEMA_VALIDATOR = Draft202012Validator(_inline_refs(SCHEMA, SCHEMA["$defs"]))
# Słowniki są w schemacie; zgodność z tabelami w bazie pilnuje test w tests/test_device_repository.py.
DEVICE_TYPES = set(SCHEMA["$defs"]["device_type"]["enum"])
DEVICE_CATEGORIES = set(SCHEMA["$defs"]["device_category"]["enum"])

NOT_AN_OBJECT = "oczekiwano obiektu JSON z polami period, devices i energy_usage"
TYPE_NAMES = {"string": "tekst", "object": "obiekt", "array": "lista", "integer": "liczba całkowita", "number": "liczba"}
EXPECTED_TYPES = {
    "string": "tekstu", "object": "obiektu", "array": "listy", "integer": "liczby całkowitej", "number": "liczby",
}


@dataclass(frozen=True)
class Issue:
    """Błąd pliku: miejsce (urządzenie, program, akcja), treść i ID, po których UI pokaże nazwę urządzenia."""

    location: str
    message: str
    device_id: str | None = None
    action_id: str | None = None

    def __str__(self) -> str:
        return f"{self.location}: {self.message}" if self.location else self.message

    def with_message(self, message: str) -> "Issue":
        return replace(self, message=message)


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)
    devices_count: int = 0
    actions_count: int = 0
    categories: set[str] = field(default_factory=set)
    idle_devices: list[str] = field(default_factory=list)
    peak_kw: float | None = None
    peak_at: datetime | None = None
    daily_energy: dict[date, dict[str, float]] = field(default_factory=dict)

    @property
    def errors(self) -> list[str]:
        return [str(issue) for issue in self.issues]

    @property
    def is_valid(self) -> bool:
        return not self.issues


def schema_issues(document: dict) -> list[Issue]:
    """Błędy struktury pliku według schematu, jako polskie komunikaty wskazujące urządzenie albo akcję."""
    issues = []
    for error in SCHEMA_VALIDATOR.iter_errors(document):
        for issue in _describe(error, document):
            if issue not in issues:
                issues.append(issue)
    return issues


def _id_or(item, key: str, fallback):
    value = item.get(key) if isinstance(item, dict) else None
    return value if isinstance(value, str) else fallback


def _owner(path: list, document: dict) -> tuple[Issue, int]:
    """Obiekt, którego dotyczy błąd (urządzenie, program, akcja), jako Issue bez treści, i długość jego ścieżki."""
    if len(path) >= 2 and path[0] == "devices" and isinstance(path[1], int):
        device_id = _id_or(document["devices"][path[1]], "device_id", None)
        label = device_id or f"devices[{path[1]}]"
        if len(path) >= 4 and path[2] == "programs" and isinstance(path[3], int):
            return Issue(f"{label}.programs[{path[3]}]", "", device_id), 4
        return Issue(label, "", device_id), 2
    if len(path) >= 2 and path[0] == "energy_usage" and isinstance(path[1], int):
        action = document["energy_usage"][path[1]]
        action_id = _id_or(action, "action_id", None)
        return Issue(action_id or f"energy_usage[{path[1]}]", "", _id_or(action, "device_id", None), action_id), 2
    if path:
        return Issue(str(path[0]), ""), 1
    return Issue("plik", ""), 0


def _describe(error: ValidationError, document: dict) -> list[Issue]:
    path = list(error.absolute_path)
    owner, owner_length = _owner(path, document)
    field_name = next((part for part in reversed(path[owner_length:]) if isinstance(part, str)), None)

    template = error.schema.get("x-message") if isinstance(error.schema, dict) else None
    if template:
        messages = [template.format(field=field_name, value=error.instance)]
    elif error.validator == "required":
        messages = [f"brak pola {name}" for name in error.validator_value if name not in error.instance]
    elif error.validator == "type" and error.validator_value in TYPE_NAMES:
        if field_name is None:
            messages = [f"oczekiwano {EXPECTED_TYPES[error.validator_value]}"]
        else:
            messages = [f"pole {field_name} musi być typu {TYPE_NAMES[error.validator_value]}"]
    else:
        messages = [error.message]
    return [owner.with_message(message) for message in messages]


def parse_time(value: str, owner: Issue, field_name: str, issues: list[Issue]) -> datetime | None:
    """Schemat sprawdza zapis daty ze strefą; tu wychodzą daty nieistniejące w kalendarzu (np. 2026-02-30)."""
    location = f"{owner.location}.{field_name}"
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        issues.append(replace(owner, location=location, message=f"niepoprawna data {value!r}"))
        return None
    if parsed.utcoffset() is None:
        issues.append(replace(owner, location=location, message=f"brak strefy czasowej w {value!r}"))
        return None
    return parsed


def on_slot_boundary(moment: datetime) -> bool:
    return moment.minute % 15 == 0 and moment.second == 0 and moment.microsecond == 0


def validate_period(period: dict, issues: list[Issue]) -> tuple[datetime, datetime] | None:
    owner = Issue("period", "")
    start = parse_time(period["start"], owner, "start", issues)
    end = parse_time(period["end"], owner, "end", issues)
    if start is None or end is None:
        return None
    if start >= end:
        issues.append(Issue("period", "start musi być wcześniej niż end"))
        return None
    return start, end


def validate_devices(devices_list: list, issues: list[Issue]) -> dict:
    """Zwraca urządzenia według device_id, z programami według program_id."""
    devices = {}
    for device in devices_list:
        device_id = device["device_id"]
        if device_id in devices:
            issues.append(Issue(device_id, "zduplikowane device_id", device_id))
            continue
        programs = {}
        for program in device.get("programs", []):
            program_id = program["program_id"]
            if program_id in programs:
                issues.append(Issue(device_id, f"zduplikowany program_id {program_id!r}", device_id))
                continue
            if len(program["profile_kwh"]) * 15 != program["duration_min"]:
                issues.append(Issue(
                    f"{device_id}/{program_id}",
                    f"profil ma {len(program['profile_kwh'])} kwadransów, a program trwa {program['duration_min']} min",
                    device_id,
                ))
            programs[program_id] = program
        devices[device_id] = {**device, "programs": programs}
    return devices


def action_profile(action: dict, device: dict, slots: int) -> list[float]:
    if "profile_kwh" in action:
        return action["profile_kwh"]
    if action.get("program_id") in device["programs"]:
        return device["programs"][action["program_id"]]["profile_kwh"]
    return [action["energy_kwh"] / slots] * slots


def validate_ev_session(action: dict, owner: Issue, start: datetime, end: datetime, issues: list[Issue]) -> None:
    if "deadline" not in action:
        issues.append(owner.with_message("sesja EV wymaga deadline"))
        return
    plugged_in = parse_time(action.get("plugged_in", action["action_start"]), owner, "plugged_in", issues)
    deadline = parse_time(action["deadline"], owner, "deadline", issues)
    if plugged_in and deadline and not (plugged_in <= start < end <= deadline):
        issues.append(owner.with_message("wymagane plugged_in <= action_start < action_end <= deadline"))


def validate_actions(actions: list, devices: dict, period: tuple, result: ValidationResult) -> dict:
    issues = result.issues
    period_start, period_end = period
    seen_ids = set()
    ranges = defaultdict(list)
    grid_load = defaultdict(float)
    daily_energy = defaultdict(lambda: defaultdict(float))

    for action in actions:
        action_id = action["action_id"]
        owner = Issue(action_id, "", action["device_id"], action_id)

        if action_id in seen_ids:
            issues.append(owner.with_message("zduplikowane action_id"))
        seen_ids.add(action_id)

        device = devices.get(action["device_id"])
        if device is None:
            issues.append(owner.with_message(f"nieznane urządzenie {action['device_id']!r}"))
            continue

        start = parse_time(action["action_start"], owner, "action_start", issues)
        end = parse_time(action["action_end"], owner, "action_end", issues)
        if start is None or end is None:
            continue
        if not (period_start <= start < end <= period_end):
            issues.append(owner.with_message("akcja wykracza poza period albo kończy się przed startem"))
            continue
        if not (on_slot_boundary(start) and on_slot_boundary(end)):
            issues.append(owner.with_message("start i koniec muszą wypadać na pełnym kwadransie"))
            continue

        slots = int((end - start) / SLOT)
        energy = action["energy_kwh"]
        if (energy < 0) != (device["device_category"] == PRODUCER_CATEGORY):
            issues.append(owner.with_message(f"ujemna energia jest dozwolona tylko dla kategorii {PRODUCER_CATEGORY}"))

        if ("program_id" in action) != bool(device["programs"]):
            issues.append(owner.with_message("program_id jest wymagany dokładnie dla urządzeń z programami"))
            continue
        if device["programs"] and action["program_id"] not in device["programs"]:
            issues.append(owner.with_message(f"nieznany program {action['program_id']!r}"))
            continue

        profile = action_profile(action, device, slots)
        if len(profile) != slots:
            issues.append(owner.with_message(f"profil ma {len(profile)} kwadransów, a akcja trwa {slots}"))
            continue
        if abs(sum(profile) - energy) > ENERGY_TOLERANCE_KWH:
            issues.append(owner.with_message(f"suma profilu {sum(profile):.2f} kWh różni się od energy_kwh {energy:.2f}"))
        if "max_power_kw" in device:
            slot_limit = device["max_power_kw"] * SLOT_HOURS
            if max(abs(value) for value in profile) > slot_limit + POWER_TOLERANCE_KWH:
                issues.append(owner.with_message(f"przekroczona moc maksymalna {device['max_power_kw']} kW"))

        if device["device_type"] == "ev_charger":
            validate_ev_session(action, owner, start, end, issues)
        elif "plugged_in" in action or "deadline" in action:
            issues.append(owner.with_message("plugged_in i deadline są dozwolone tylko dla ładowarki EV"))

        ranges[action["device_id"]].append((start, end, action_id))
        for slot_index, value in enumerate(profile):
            slot = start + slot_index * SLOT
            grid_load[slot] += max(value, 0)
            daily_energy[slot.date()][device["device_category"]] += value

    for device_id, device_ranges in ranges.items():
        device_ranges.sort()
        for (_, previous_end, previous_id), (next_start, _, next_id) in zip(device_ranges, device_ranges[1:]):
            if next_start < previous_end:
                issues.append(Issue(device_id, f"akcje {previous_id} i {next_id} nakładają się", device_id))

    result.idle_devices = sorted(set(devices) - set(ranges))
    result.daily_energy = {day: dict(categories) for day, categories in sorted(daily_energy.items())}
    return grid_load


def validate_document(document, max_grid_kw: float | None = DEFAULT_MAX_GRID_KW) -> ValidationResult:
    """Sprawdza wczytany plik urządzeń. Nie rzuca wyjątków: każdy problem trafia do `errors`.

    Przy błędach struktury (schemat) reguły semantyczne nie są sprawdzane: zwracamy tylko błędy
    schematu, bo dalsze komunikaty wynikałyby z nich. `max_grid_kw=None` pomija regułę limitu
    przyłącza (szczyt poboru jest nadal liczony).
    """
    result = ValidationResult()
    issues = result.issues
    if not isinstance(document, dict):
        issues.append(Issue("plik", NOT_AN_OBJECT))
        return result
    issues.extend(schema_issues(document))
    if issues:
        return result
    period = validate_period(document["period"], issues)
    if period is None:
        return result

    devices = validate_devices(document["devices"], issues)
    grid_load = validate_actions(document["energy_usage"], devices, period, result)
    result.devices_count = len(devices)
    result.actions_count = len(document["energy_usage"])
    result.categories = {device["device_category"] for device in devices.values()}

    if grid_load:
        result.peak_at, peak_kwh = max(grid_load.items(), key=lambda item: item[1])
        result.peak_kw = peak_kwh / SLOT_HOURS
        if max_grid_kw is not None and peak_kwh > max_grid_kw * SLOT_HOURS + POWER_TOLERANCE_KWH:
            issues.append(Issue("", f"przekroczony limit przyłącza {max_grid_kw} kW o {result.peak_at:%d.%m %H:%M}"))
    return result
