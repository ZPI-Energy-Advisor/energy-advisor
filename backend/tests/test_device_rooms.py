"""Pomieszczenia urządzeń (ZP-109): słownik ze schematu i pomieszczenie domyślne według typu albo nazwy."""

import pytest

from app.parsers.device_validation import DEVICE_TYPES, SCHEMA
from app.services.device_rooms import DEFAULT_ROOMS, LIGHT_TYPE, OTHER, default_room, device_room

ROOMS = set(SCHEMA["$defs"]["room"]["enum"])


def test_every_device_type_has_a_default_room_from_schema():
    # Nowy typ w schemacie bez reguły trafiłby po cichu do „other”, a literówka w pomieszczeniu – do huba.
    assert set(DEFAULT_ROOMS) | {LIGHT_TYPE} == DEVICE_TYPES
    assert set(DEFAULT_ROOMS.values()) <= ROOMS
    assert OTHER in ROOMS


@pytest.mark.parametrize(
    ("device_type", "room"),
    [
        ("fridge", "kitchen"),
        ("washing_machine", "bathroom"),
        ("heat_pump", "technical"),
        ("ev_charger", "garage"),
        ("pv_inverter", "roof"),
        ("tv", "living_room"),
        ("computer", "office"),
        ("other", "other"),
    ],
)
def test_default_room_by_type_ignores_name(device_type, room):
    # Nazwa decyduje tylko o oświetleniu: lodówka „w garażu” bez pola room zostaje w kuchni.
    assert default_room(device_type, "Urządzenie w garażu") == room


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
        ("Oświetlenie kuchenne", "kitchen"),
        ("Lampa łazienkowa", "bathroom"),
        ("Oświetlenie salonu", "living_room"),
        ("Living room light", "living_room"),
        ("Technical room light", "technical"),
        ("Oświetlenie pomieszczenia technicznego", "technical"),
        ("Oświetlenie GARAŻ", "garage"),
        ("Lampka na biurko w salonie", "living_room"),
        ("Lampka biurkowa", "other"),
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
