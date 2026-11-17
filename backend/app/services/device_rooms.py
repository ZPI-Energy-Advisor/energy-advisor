"""Pomieszczenie urządzenia dla widoku budynku: z pliku urządzeń (pole `room`) albo domyślne według typu.

W bazie (`device_instances.room`) jest tylko wartość z pliku. Domyślne liczymy przy odczycie (rejestr huba,
stan domu), więc urządzenia wgrane przed polem `room` też mają pomieszczenie, a zmiana reguł działa od razu.
"""

from app.parsers.device_validation import SCHEMA

# Słownik ze schematu pliku urządzeń, jedno źródło dla walidacji i reguł domyślnych.
ROOMS = tuple(SCHEMA["$defs"]["room"]["enum"])
OTHER = "other"
LIGHT_TYPE = "light"

DEFAULT_ROOMS = {
    "fridge": "kitchen",
    "freezer": "kitchen",
    "induction_hob": "kitchen",
    "oven": "kitchen",
    "microwave": "kitchen",
    "kettle": "kitchen",
    "coffee_machine": "kitchen",
    "dishwasher": "kitchen",
    "washing_machine": "bathroom",
    "tumble_dryer": "bathroom",
    "ev_charger": "garage",
    "pv_inverter": "roof",
    "heat_pump": "technical",
    "router": "technical",
    "ventilation": "technical",
    "water_heater": "bathroom",
    "hair_dryer": "bathroom",
    "tv": "living_room",
    "electric_heater": "living_room",
    "computer": "office",
    "vacuum_cleaner": OTHER,
    "other": OTHER,
}

# Oświetlenie według nazwy, np. „Oświetlenie kuchnia”: rdzenie słów, żeby pasowały też odmiany („w kuchni”).
LIGHT_NAME_ROOMS = (
    (("kuchni", "kitchen"), "kitchen"),
    (("salon", "living"), "living_room"),
    (("sypialn", "bedroom"), "bedroom"),
    (("łazien", "lazien", "bathroom"), "bathroom"),
    (("praln", "laundry"), "laundry"),
    (("gabinet", "biur", "office"), "office"),
    (("techniczn", "kotłown", "kotlown"), "technical"),
    (("garaż", "garaz", "garage"), "garage"),
)


def default_room(device_type: str, device_name: str) -> str:
    """Pomieszczenie urządzenia bez pola `room`: według typu, a oświetlenie według nazwy."""
    if device_type == LIGHT_TYPE:
        name = device_name.casefold()
        return next((room for words, room in LIGHT_NAME_ROOMS if any(word in name for word in words)), OTHER)
    return DEFAULT_ROOMS.get(device_type, OTHER)


def device_room(room: str | None, device_type: str, device_name: str) -> str:
    """Pomieszczenie z pliku, a bez niego domyślne."""
    return room or default_room(device_type, device_name)
