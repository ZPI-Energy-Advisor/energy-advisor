"""Pomieszczenia urządzeń (ZP-109): słownik ze schematu i pomieszczenie domyślne według typu albo nazwy."""

import pytest

from app.parsers.device_validation import DEVICE_TYPES
from app.services.device_rooms import DEFAULT_ROOMS, LIGHT_TYPE, ROOMS, default_room, device_room

# Oczekiwane pomieszczenie dla każdego typu ze słownika (oświetlenie osobno, według nazwy).
EXPECTED = {
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
    "vacuum_cleaner": "other",
    "other": "other",
}


def test_every_device_type_has_a_default_room():
    # Nowy typ w schemacie bez reguły trafiłby po cichu do „other”.
    assert set(DEFAULT_ROOMS) | {LIGHT_TYPE} == DEVICE_TYPES
    assert set(EXPECTED) | {LIGHT_TYPE} == DEVICE_TYPES
    assert set(DEFAULT_ROOMS.values()) <= set(ROOMS)


@pytest.mark.parametrize("device_type", sorted(EXPECTED))
def test_default_room_by_type(device_type):
    assert default_room(device_type, "Urządzenie w kuchni") == EXPECTED[device_type]


@pytest.mark.parametrize(
    ("name", "room"),
    [
        ("Oświetlenie kuchnia", "kitchen"),
        ("Lampa w kuchni", "kitchen"),
        ("Oświetlenie salon", "living_room"),
        ("Oświetlenie sypialnia", "bedroom"),
        ("Kinkiet w sypialni", "bedroom"),
        ("Oświetlenie łazienka", "bathroom"),
        ("Oswietlenie lazienka", "bathroom"),
        ("Oświetlenie pralnia", "laundry"),
        ("Lampka gabinet", "office"),
        ("Światło w biurze", "office"),
        ("Oświetlenie kotłownia", "technical"),
        ("Oświetlenie GARAŻ", "garage"),
        ("Garage light", "garage"),
        ("Oświetlenie przedpokój", "other"),
        ("Oświetlenie ogród", "other"),
        ("Lampa", "other"),
    ],
)
def test_light_room_by_name(name, room):
    assert default_room(LIGHT_TYPE, name) == room


def test_room_from_file_wins_over_default():
    assert device_room("garage", "fridge", "Lodówka") == "garage"
    assert device_room(None, "fridge", "Lodówka") == "kitchen"
