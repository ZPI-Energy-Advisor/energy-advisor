import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.parsers.device_validation import validate_document


BACKEND_DIR = Path(__file__).resolve().parents[1]
VALIDATOR = BACKEND_DIR / "scripts" / "validate_devices_file.py"
SAMPLE_FILE = BACKEND_DIR.parent / "frontend" / "public" / "samples" / "devices-example.json"
SAMPLE = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))


def device(document, device_id):
    return next(item for item in document["devices"] if item["device_id"] == device_id)


def actions(document, device_id):
    return [item for item in document["energy_usage"] if item["device_id"] == device_id]


def swap_period(document):
    period = document["period"]
    period["start"], period["end"] = period["end"], period["start"]


def overlap_fridge_days(document):
    first, second = actions(document, "dev_fr_01")
    second["action_start"], second["action_end"] = first["action_start"], first["action_end"]


def duplicate_program(document):
    device(document, "dev_wm_01")["programs"][1]["program_id"] = "cotton_60"


INVALID_CASES = {
    "devices_not_list": (lambda d: d.update(devices={}), "devices: oczekiwano listy"),
    "period_reversed": (swap_period, "period: start musi być wcześniej niż end"),
    "period_without_timezone": (lambda d: d["period"].update(start="2026-10-19T00:00:00"), "brak strefy czasowej"),
    "missing_device_field": (lambda d: device(d, "dev_fr_01").pop("device_category"), "brak pola device_category"),
    "duplicate_device_id": (lambda d: device(d, "dev_td_01").update(device_id="dev_wm_01"), "zduplikowane device_id"),
    "unknown_device_type": (lambda d: device(d, "dev_kt_01").update(device_type="toaster"), "nieznany device_type"),
    "unknown_category": (lambda d: device(d, "dev_kt_01").update(device_category="Kuchnia"),
                         "nieznana device_category"),
    "unknown_mode": (lambda d: device(d, "dev_kt_01").update(flexibility={"mode": "smart"}), "nieznany tryb"),
    "field_not_allowed_in_mode": (lambda d: device(d, "dev_pv_01")["flexibility"].update(max_shift_min=30),
                                  "nie obsługuje pól: max_shift_min"),
    "window_off_slot": (lambda d: device(d, "dev_wm_01")["flexibility"]["allowed_window"].update({"from": "07:10"}),
                        "allowed_window.from"),
    "no_programs_and_no_power": (lambda d: device(d, "dev_ev_01").pop("max_power_kw"), "musi mieć max_power_kw"),
    "program_without_profile": (lambda d: device(d, "dev_wm_01")["programs"][0].pop("profile_kwh"),
                                "brak pola profile_kwh"),
    "program_duration_mismatch": (lambda d: device(d, "dev_wm_01")["programs"][0].update(duration_min=90),
                                  "a program trwa 90 min"),
    "duplicate_program_id": (duplicate_program, "zduplikowany program_id"),
    "duplicate_action_id": (lambda d: d["energy_usage"][1].update(action_id=d["energy_usage"][0]["action_id"]),
                            "zduplikowane action_id"),
    "energy_as_text": (lambda d: d["energy_usage"][0].update(energy_kwh="1.0"), "pole energy_kwh musi być typu liczba"),
    "unknown_device": (lambda d: d["energy_usage"][0].update(device_id="dev_xx_01"), "nieznane urządzenie"),
    "missing_program_id": (lambda d: actions(d, "dev_wm_01")[0].pop("program_id"), "program_id jest wymagany"),
    "unknown_program": (lambda d: actions(d, "dev_wm_01")[0].update(program_id="wool"), "nieznany program"),
    "action_outside_period": (lambda d: actions(d, "dev_kt_01")[0].update(action_start="2026-10-18T23:45:00+02:00"),
                              "wykracza poza period"),
    "action_off_slot": (lambda d: actions(d, "dev_kt_01")[0].update(action_start="2026-10-19T06:40:00+02:00"),
                        "pełnym kwadransie"),
    "profile_sum_mismatch": (lambda d: actions(d, "dev_wm_01")[0].update(energy_kwh=1.50), "suma profilu"),
    "max_power_exceeded": (lambda d: actions(d, "dev_kt_01")[0].update(energy_kwh=5.0), "przekroczona moc"),
    "negative_energy_outside_oze": (lambda d: actions(d, "dev_kt_01")[0].update(energy_kwh=-0.1), "ujemna energia"),
    "overlapping_actions": (overlap_fridge_days, "nakładają się"),
    "ev_without_deadline": (lambda d: actions(d, "dev_ev_01")[0].pop("deadline"), "sesja EV wymaga deadline"),
    "ev_plugged_in_after_start": (lambda d: actions(d, "dev_ev_01")[0].update(plugged_in="2026-10-19T18:30:00+02:00"),
                                  "plugged_in <= action_start"),
    "deadline_outside_ev": (lambda d: actions(d, "dev_kt_01")[0].update(deadline="2026-10-20T07:00:00+02:00"),
                            "dozwolone tylko dla ładowarki EV"),
}


def test_sample_file_is_valid():
    result = validate_document(copy.deepcopy(SAMPLE))

    assert result.is_valid, result.errors
    assert (result.devices_count, len(result.categories), result.actions_count) == (24, 7, 62)


@pytest.mark.parametrize("mutate, expected", INVALID_CASES.values(), ids=INVALID_CASES.keys())
def test_invalid_file_is_reported(mutate, expected):
    document = copy.deepcopy(SAMPLE)
    mutate(document)

    result = validate_document(document)

    assert any(expected in error for error in result.errors), result.errors


def test_document_must_be_object():
    assert validate_document([]).errors == ["plik: oczekiwano obiektu JSON z polami period, devices i energy_usage"]


def test_grid_limit_is_checked():
    result = validate_document(copy.deepcopy(SAMPLE), max_grid_kw=5)

    assert any("przekroczony limit przyłącza 5" in error for error in result.errors)


def test_actions_of_rejected_device_do_not_add_errors():
    document = copy.deepcopy(SAMPLE)
    device(document, "dev_fr_01").pop("device_category")

    assert validate_document(document).errors == ["dev_fr_01: brak pola device_category"]


def test_actions_of_rejected_program_do_not_add_errors():
    document = copy.deepcopy(SAMPLE)
    device(document, "dev_wm_01")["programs"][0].pop("profile_kwh")

    assert validate_document(document).errors == ["dev_wm_01.programs[0]: brak pola profile_kwh"]


@pytest.mark.parametrize("content, exit_code, expected", [
    (json.dumps(SAMPLE, ensure_ascii=False), 0, "OK: 24 urządzeń, 7 kategorii, 62 akcji"),
    ("{ to nie jest json", 1, "Nie udało się wczytać pliku"),
])
def test_command_line(tmp_path, content, exit_code, expected):
    path = tmp_path / "devices.json"
    path.write_text(content, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(path)],
        capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    assert result.returncode == exit_code
    assert expected in result.stdout
