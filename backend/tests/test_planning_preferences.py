# ruff: noqa: F811 (fikstury db i home z test_home są parametrami testów)
"""ZP-111: wymagania na jutro – ustawienia użytkownika dla urządzeń z jego plików (ZP-112: pompa ciepła i bojler)."""

from app.services.planning_service import CHARGING_EFFICIENCY
from test_energy_files import _headers, client
from test_home import HEAT_PUMP, LAMP, WASHER, _devices_file, _upload, db, home  # noqa: F401 (fixtures)


DISHWASHER = {
    "device": {
        "device_id": "dev_dw_01",
        "device_name": "Zmywarka",
        "device_type": "dishwasher",
        "device_category": "AGD",
        "flexibility": {"mode": "shiftable", "allowed_window": {"from": "19:00", "to": "07:00"}},
        "programs": [{"program_id": "eco", "program_name": "Eco", "duration_min": 45, "profile_kwh": [0.3, 0.2, 0.1]}],
    },
    "actions": [{
        "action_id": "act_dw_1", "device_id": "dev_dw_01", "program_id": "eco",
        "action_start": "2026-10-05T20:00:00+02:00", "action_end": "2026-10-05T20:45:00+02:00", "energy_kwh": 0.6,
    }],
}
WATER_HEATER = {
    "device": {
        "device_id": "dev_wh_01",
        "device_name": "Bojler",
        "device_type": "water_heater",
        "device_category": "Ogrzewanie",
        "max_power_kw": 2.0,
        "flexibility": {"mode": "shiftable", "max_shift_min": 120},
    },
    "actions": [
        {"action_id": "act_wh_1", "device_id": "dev_wh_01",
         "action_start": "2026-10-05T06:00:00+02:00", "action_end": "2026-10-05T07:00:00+02:00", "energy_kwh": 2.0},
        {"action_id": "act_wh_2", "device_id": "dev_wh_01",
         "action_start": "2026-10-05T19:00:00+02:00", "action_end": "2026-10-05T20:00:00+02:00", "energy_kwh": 1.6},
    ],
}
EV = {
    "device": {
        "device_id": "dev_ev_01",
        "device_name": "Ładowarka EV",
        "device_type": "ev_charger",
        "device_category": "Pojazd elektryczny",
        "max_power_kw": 3.7,
        "flexibility": {"mode": "interruptible", "allowed_window": {"from": "18:00", "to": "07:00"}},
    },
    "actions": [{
        "action_id": "act_ev_1", "device_id": "dev_ev_01",
        "plugged_in": "2026-10-05T18:00:00+02:00", "deadline": "2026-10-05T23:00:00+02:00",
        "action_start": "2026-10-05T18:00:00+02:00", "action_end": "2026-10-05T19:00:00+02:00", "energy_kwh": 3.6,
    }],
}


def _get(user):
    return client.get("/api/v1/planning/preferences", headers=_headers(user))


def _put(user, body):
    return client.put("/api/v1/planning/preferences", json=body, headers=_headers(user))


def _windows(*pairs):
    return [{"start": start, "end": end} for start, end in pairs]


def _owner_with_devices(home):
    assert _upload(home.owner, _devices_file(WASHER, LAMP, HEAT_PUMP, DISHWASHER, WATER_HEATER, EV)).status_code == 200
    return home.owner


def _errors(response):
    assert response.status_code == 422
    return {(item["loc"][2], item["loc"][3]): item["msg"] for item in response.json()["detail"]}


def test_every_user_plans_own_devices_without_smart_home(home):
    _owner_with_devices(home)
    assert _upload(home.other, _devices_file(DISHWASHER)).status_code == 200

    other = _get(home.other)
    saved = _put(home.other, {"devices": [
        {"device_id": "dev_dw_01", "enabled": True, "program_id": "eco", "windows": _windows(("10:00", "14:00"))},
    ]})

    assert other.status_code == 200
    assert [device["device_id"] for device in other.json()["devices"]] == ["dev_dw_01"]
    assert saved.status_code == 200
    # Ustawienia innego konta nie zmieniają ustawień właściciela.
    owner_devices = {device["device_id"]: device for device in _get(home.owner).json()["devices"]}
    assert owner_devices["dev_dw_01"]["preference"]["enabled"] is False


def test_saving_again_overwrites_previous_settings(home):
    owner = _owner_with_devices(home)
    first = {"devices": [{"device_id": "dev_dw_01", "enabled": True, "program_id": "eco", "windows": _windows(("10:00", "14:00"))}]}
    second = {"devices": [{"device_id": "dev_dw_01", "enabled": False, "program_id": "eco", "windows": _windows(("20:00", "22:00"))}]}

    assert _put(owner, first).status_code == 200
    assert _put(owner, second).status_code == 200

    dishwasher = next(device for device in _get(owner).json()["devices"] if device["device_id"] == "dev_dw_01")
    assert dishwasher["preference"]["enabled"] is False
    assert dishwasher["preference"]["windows"] == _windows(("20:00", "22:00"))


def test_saving_the_same_settings_again_updates_saved_at(home):
    owner = _owner_with_devices(home)
    body = {"devices": [{"device_id": "dev_dw_01", "enabled": True, "program_id": "eco", "windows": _windows(("10:00", "14:00"))}]}

    first = _put(owner, body).json()["saved_at"]
    second = _put(owner, body).json()["saved_at"]

    assert second > first


def test_defaults_list_flexible_devices_with_windows_from_file(home):
    owner = _owner_with_devices(home)

    body = _get(owner).json()

    assert body["saved_at"] is None
    assert body["after_max_gap_min"] == 60
    devices = {device["device_id"]: device for device in body["devices"]}
    # Lampa jest fixed; pompa ciepła i bojler bez programów, ale z energią z historii (ZP-112).
    assert set(devices) == {"dev_wm_01", "dev_dw_01", "dev_ev_01", "dev_hp_01", "dev_wh_01"}
    washer = devices["dev_wm_01"]
    assert washer["default_windows"] == _windows(("07:00", "22:00"))
    assert washer["preference"]["windows"] == _windows(("07:00", "22:00"))
    assert washer["preference"]["enabled"] is False
    assert [program["program_id"] for program in washer["programs"]] == ["cotton_60", "quick_30"]
    assert devices["dev_ev_01"]["is_ev"] is True
    assert devices["dev_ev_01"]["default_windows"] == _windows(("18:00", "07:00"))
    # Pompa ciepła i bojler i tak pracują codziennie: od razu zaznaczone, z historią zużycia.
    heat_pump, water_heater = devices["dev_hp_01"], devices["dev_wh_01"]
    assert heat_pump["kind"] == "heat_pump"
    assert heat_pump["preference"]["enabled"] is True
    assert heat_pump["preference"]["shift_hours"] == 1  # max_shift_min z pliku
    assert (heat_pump["history_kwh"], heat_pump["history_day"]) == (1.5, "2026-10-05")
    assert water_heater["kind"] == "water_heater"
    assert water_heater["preference"]["ready_times"] == ["06:00", "18:00"]
    # Bojler ma historię (3,6 kWh 05.10): ciepła woda to zużycie z termostatem minus jego straty
    # (80 l trzymane na 55°C traci ok. 1,1 kWh na dobę). Zbiornik bez pliku i profilu: 80 l dla 2 osób.
    assert water_heater["preference"]["tank_liters"] == 80
    assert (water_heater["history_kwh"], water_heater["hot_water_source"]) == (3.6, "history")
    assert water_heater["hot_water_kwh"] == 2.48


def test_saved_settings_keep_several_windows_and_battery_capacity(home):
    owner = _owner_with_devices(home)
    body = {
        "devices": [
            {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60",
             "windows": _windows(("08:00", "13:00"), ("17:00", "00:00"))},
            {"device_id": "dev_ev_01", "enabled": True, "windows": _windows(("19:00", "06:00")),
             "energy_input": "percent", "battery_kwh": 60, "current_percent": 40, "target_percent": 70},
        ],
    }

    saved = _put(owner, body)

    assert saved.status_code == 200
    again = _get(owner).json()
    assert again["saved_at"] is not None
    devices = {device["device_id"]: device for device in again["devices"]}
    assert devices["dev_wm_01"]["preference"]["windows"] == _windows(("08:00", "13:00"), ("17:00", "00:00"))
    assert devices["dev_ev_01"]["preference"]["battery_kwh"] == 60
    # 30% z 60 kWh = 18 kWh w baterii, z sieci więcej o straty ładowania.
    assert devices["dev_ev_01"]["energy_needed_kwh"] == round(18 / CHARGING_EFFICIENCY, 2)
    assert devices["dev_dw_01"]["preference"]["enabled"] is False  # bez zapisu: domyślne
    assert devices["dev_dw_01"]["preference"]["windows"] == _windows(("19:00", "07:00"))


def test_window_shorter_than_program_is_rejected_with_message(home):
    owner = _owner_with_devices(home)

    response = _put(owner, {"devices": [
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60",
         "windows": _windows(("08:00", "08:30"), ("12:00", "12:30"))},
    ]})

    assert _errors(response)[(0, "windows")] == "Najdłuższy przedział (30 min) jest krótszy niż program Bawełna 60°C (45 min)."
    assert _get(owner).json()["saved_at"] is None


def test_overlapping_windows_and_missing_program_are_rejected(home):
    owner = _owner_with_devices(home)

    errors = _errors(_put(owner, {"devices": [
        {"device_id": "dev_wm_01", "enabled": True, "windows": _windows(("08:00", "12:00"), ("11:00", "14:00"))},
        {"device_id": "dev_dw_01", "enabled": True, "program_id": "eco", "windows": []},
    ]}))

    assert errors[(0, "windows")] == "Przedziały godzin nachodzą na siebie."
    assert errors[(1, "windows")] == "Dodaj co najmniej jeden przedział godzin."


def test_ev_energy_must_fit_into_windows_at_charger_power(home):
    owner = _owner_with_devices(home)

    errors = _errors(_put(owner, {"devices": [
        {"device_id": "dev_ev_01", "enabled": True, "windows": _windows(("22:00", "00:00")), "energy_kwh": 10},
    ]}))

    assert errors[(0, "windows")] == (
        "W przedziałach zmieści się najwyżej 7,4 kWh (3,7 kW × 2 h), a auto potrzebuje 10,0 kWh."
    )


def test_ev_needs_energy_and_target_above_current_level(home):
    owner = _owner_with_devices(home)

    missing = _errors(_put(owner, {"devices": [
        {"device_id": "dev_ev_01", "enabled": True, "windows": _windows(("18:00", "07:00"))},
    ]}))
    reversed_levels = _errors(_put(owner, {"devices": [
        {"device_id": "dev_ev_01", "enabled": True, "windows": _windows(("18:00", "07:00")),
         "energy_input": "percent", "battery_kwh": 60, "current_percent": 80, "target_percent": 50},
    ]}))

    assert missing == {(0, "energy_kwh"): "Podaj, ile energii potrzebuje auto."}
    assert reversed_levels == {(0, "target_percent"): "Docelowy poziom baterii musi być wyższy niż obecny."}


def test_disabled_device_keeps_settings_without_checking_them(home):
    owner = _owner_with_devices(home)

    response = _put(owner, {"devices": [
        {"device_id": "dev_wm_01", "enabled": False, "program_id": "cotton_60", "windows": _windows(("08:00", "08:15"))},
    ]})

    assert response.status_code == 200
    washer = next(device for device in response.json()["devices"] if device["device_id"] == "dev_wm_01")
    assert washer["preference"]["windows"] == _windows(("08:00", "08:15"))


def test_disabled_ev_with_target_below_current_level_is_saved(home):
    owner = _owner_with_devices(home)

    response = _put(owner, {"devices": [
        {"device_id": "dev_ev_01", "enabled": False, "windows": _windows(("18:00", "07:00")),
         "energy_input": "percent", "battery_kwh": 60, "current_percent": 80, "target_percent": 50},
    ]})

    assert response.status_code == 200


def test_unknown_or_fixed_device_and_off_quarter_times_are_rejected(home):
    owner = _owner_with_devices(home)

    unknown = _errors(_put(owner, {"devices": [
        {"device_id": "dev_lamp_01", "enabled": True, "windows": []},
        {"device_id": "dev_missing", "enabled": True, "windows": []},
    ]}))
    off_quarter = _put(owner, {"devices": [
        {"device_id": "dev_dw_01", "enabled": True, "program_id": "eco", "windows": _windows(("08:10", "09:00"))},
    ]})

    assert unknown[(0, "device_id")] == "Tego urządzenia nie ma w Twoich plikach albo nie da się go planować."
    assert unknown[(1, "device_id")] == unknown[(0, "device_id")]
    assert off_quarter.status_code == 422


def _washer_then_dishwasher(washer_windows, finish_by=None, washer_enabled=True):
    return {"devices": [
        {"device_id": "dev_wm_01", "enabled": washer_enabled, "program_id": "cotton_60", "windows": _windows(*washer_windows)},
        # Przedziały zmywarki są ignorowane: start wyznacza pralka.
        {"device_id": "dev_dw_01", "enabled": True, "program_id": "eco", "windows": [],
         "after_device_id": "dev_wm_01", "finish_by": finish_by},
    ]}


def test_device_after_another_needs_only_finish_time_and_keeps_it_saved(home):
    owner = _owner_with_devices(home)

    # Pranie (45 min) w 08:00–10:00 kończy się najwcześniej o 08:45, zmywarka (45 min) zdąży przed 11:00.
    response = _put(owner, _washer_then_dishwasher([("08:00", "10:00")], finish_by="11:00"))
    # Bez godziny końca nic poza pralką jej nie ogranicza.
    without_finish = _put(owner, _washer_then_dishwasher([("08:00", "10:00")]))
    # 01:00 jest przed początkiem przedziału pralki (19:00), więc to rano następnego dnia.
    overnight = _put(owner, _washer_then_dishwasher([("19:00", "23:00")], finish_by="01:00"))

    assert response.status_code == 200
    assert without_finish.status_code == 200
    assert overnight.status_code == 200
    dishwasher = next(device for device in _get(owner).json()["devices"] if device["device_id"] == "dev_dw_01")
    assert dishwasher["preference"]["after_device_id"] == "dev_wm_01"
    # Zapisane przedziały były puste, więc wracają domyślne z pliku na wypadek usunięcia „Wykonaj po”.
    assert dishwasher["preference"]["windows"] == _windows(("19:00", "07:00"))


def test_run_after_needs_enabled_predecessor_time_and_no_loop(home):
    owner = _owner_with_devices(home)

    disabled = _errors(_put(owner, _washer_then_dishwasher([("08:00", "10:00")], washer_enabled=False)))
    too_early = _errors(_put(owner, _washer_then_dishwasher([("08:00", "10:00")], finish_by="09:15")))
    body = _washer_then_dishwasher([("08:00", "10:00")])
    body["devices"][0]["after_device_id"] = "dev_dw_01"
    loop = _errors(_put(owner, body))
    ev = _errors(_put(owner, {"devices": [
        {"device_id": "dev_ev_01", "enabled": True, "windows": _windows(("18:00", "07:00")), "energy_kwh": 5,
         "after_device_id": "dev_wm_01"},
    ]}))

    assert disabled == {(1, "after_device_id"): "Pralka Bosch nie pracuje jutro. Zaznacz je albo usuń „Wykonaj po”."}
    assert too_early == {
        (1, "finish_by"): "Pralka Bosch skończy się najwcześniej o 08:45, a Eco trwa 45 min – nie zdąży przed 09:15.",
    }
    assert loop[(0, "after_device_id")] == "Urządzenia nie mogą czekać na siebie nawzajem."
    assert ev == {(0, "after_device_id"): "Tylko urządzenie z programem może czekać na inne."}


def test_heat_pump_and_water_heater_need_only_shift_or_ready_times(home):
    owner = _owner_with_devices(home)

    saved = _put(owner, {"devices": [
        {"device_id": "dev_hp_01", "enabled": True, "shift_hours": 3},
        {"device_id": "dev_wh_01", "enabled": True, "ready_times": ["07:00", "19:30"], "tank_liters": 150},
    ]})
    errors = _errors(_put(owner, {"devices": [
        {"device_id": "dev_hp_01", "enabled": True},
        {"device_id": "dev_wh_01", "enabled": True, "ready_times": ["07:00", "07:00"]},
    ]}))
    off_quarter = _put(owner, {"devices": [{"device_id": "dev_wh_01", "enabled": True, "ready_times": ["07:10"]}]})

    assert saved.status_code == 200
    devices = {device["device_id"]: device for device in saved.json()["devices"]}
    assert devices["dev_hp_01"]["preference"]["shift_hours"] == 3
    assert devices["dev_wh_01"]["preference"]["ready_times"] == ["07:00", "19:30"]
    assert devices["dev_wh_01"]["preference"]["tank_liters"] == 150
    assert errors == {
        (0, "shift_hours"): "Wybierz, o ile można przesunąć grzanie.",
        (1, "ready_times"): "Godziny się powtarzają.",
    }
    assert off_quarter.status_code == 422


def test_water_heater_follows_number_of_residents_from_profile(home, db):
    from app.models.UserProfile import UserProfile

    # Bojler bez historii w pliku: ciepła woda z liczby osób z profilu.
    without_history = {**WATER_HEATER, "actions": []}
    owner = home.owner
    assert _upload(owner, _devices_file(without_history)).status_code == 200
    db.add(UserProfile(user_id=owner.id, base_info={"number_of_residents": 5}, consumption_and_tariff={}, pv_config={}))
    db.commit()

    water_heater = _get(owner).json()["devices"][0]

    # 5 osób to więcej ciepłej wody niż 2 i większy zbiornik domyślnie.
    assert (water_heater["residents"], water_heater["hot_water_kwh"]) == (5, 8.0)
    assert water_heater["hot_water_source"] == "residents"
    assert water_heater["preference"]["tank_liters"] == 150


def test_tank_capacity_from_devices_file_wins_over_setting(home):
    heater = {**WATER_HEATER, "device": {**WATER_HEATER["device"], "tank_liters": 150}}
    assert _upload(home.owner, _devices_file(heater)).status_code == 200
    assert _put(home.owner, {"devices": [
        {"device_id": "dev_wh_01", "enabled": True, "ready_times": ["06:00"], "tank_liters": 80},
    ]}).status_code == 200

    water_heater = _get(home.owner).json()["devices"][0]

    assert water_heater["tank_liters_from_file"] == 150
    assert water_heater["preference"]["tank_liters"] == 150


def test_tank_capacity_is_allowed_only_for_water_heater(home):
    lamp = {**LAMP, "device": {**LAMP["device"], "tank_liters": 80}}

    assert _upload(home.owner, _devices_file(lamp)).status_code != 200


def test_flat_tariff_is_reported_for_g11_without_dynamic_price(home, db):
    from app.models.UserProfile import UserProfile

    owner = _owner_with_devices(home)
    assert _get(owner).json()["flat_tariff"] is False  # bez profilu nie wiemy
    profile = UserProfile(user_id=owner.id, base_info={}, consumption_and_tariff={"tariff_type": "G11"}, pv_config={})
    db.add(profile)
    db.commit()
    assert _get(owner).json()["flat_tariff"] is True

    profile.consumption_and_tariff = {"tariff_type": "G11", "dynamic_price": True}
    db.commit()
    assert _get(owner).json()["flat_tariff"] is False
