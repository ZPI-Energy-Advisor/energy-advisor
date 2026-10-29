import copy
import json
from datetime import date, time
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.parsers import FileImportError, ParsedEnergyFile, parse_energy_file
from app.parsers.device_validation import SLOT, validate_document
from app.services.calculation_service import CalculationService


SAMPLE_FILE = Path(__file__).resolve().parents[2] / "frontend" / "public" / "samples" / "devices-example.json"
DEMO_FILE = Path(__file__).parent / "fixtures" / "devices_demo_30d.json"
SAMPLE = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
WARSAW = ZoneInfo("Europe/Warsaw")


def parse(document: dict) -> ParsedEnergyFile:
    return parse_energy_file(BytesIO(json.dumps(document).encode("utf-8")))


def action(parsed: ParsedEnergyFile, action_id: str):
    return next(item for device in parsed.devices for item in device.actions if item.action_id == action_id)


def calculation_service() -> CalculationService:
    tariff = MagicMock()
    tariff.id, tariff.name, tariff.type = 1, "G11", "stala"
    rate = MagicMock(price_per_kwh=1.0, time_start=time(0, 0), time_end=time(23, 59, 59))
    repository = MagicMock()
    repository.get_all.return_value = [tariff]
    repository.get_rates_for_tariff.return_value = [rate]
    return CalculationService(repository)


@pytest.mark.parametrize("path", [SAMPLE_FILE, DEMO_FILE], ids=["plik-przykladowy", "plik-demo-30-dni"])
def test_devices_files_are_imported_and_priced(path):
    with path.open("rb") as handle:
        results = calculation_service().calculate_all_tariffs(handle)

    assert results["import_report"]["detected_format"] == "devices"
    assert results["import_report"]["unit"] == "action"
    assert results["tariffs"]["G11"]["total_usage_kwh"] == results["import_report"]["devices"]["consumption_kwh"]


def test_action_with_program_uses_program_profile():
    washing = action(parse(SAMPLE), "act_0016")

    assert washing.slots_kwh == [0.45, 0.45, 0.30, 0.10, 0.10, 0.15, 0.20, 0.20]


@pytest.mark.parametrize("action_id, slots, kwh", [
    ("act_0011", 1, 0.12),       # czajnik 06:45–07:00
    ("act_0028", 14, 0.45 / 14),  # telewizor 19:30–23:00
], ids=["czajnik", "telewizor"])
def test_action_without_profile_splits_energy_evenly(action_id, slots, kwh):
    record = action(parse(SAMPLE), action_id)

    assert record.slots_kwh == pytest.approx([kwh] * slots)


def test_action_with_own_profile_keeps_it():
    pv = next(item for item in SAMPLE["energy_usage"] if item["action_id"] == "act_0014")

    assert action(parse(SAMPLE), "act_0014").slots_kwh == pv["profile_kwh"]


def test_action_crossing_midnight_lands_on_two_days():
    dishwasher = action(parse(SAMPLE), "act_0031")  # zmywarka 22:30–01:30
    days = {(dishwasher.start + index * SLOT).astimezone(WARSAW).date() for index in range(len(dishwasher.slots_kwh))}

    assert days == {date(2026, 10, 19), date(2026, 10, 20)}


def test_dst_change_day_has_all_quarters_in_local_time():
    with DEMO_FILE.open("rb") as handle:
        parsed = parse_energy_file(handle)
    results = calculation_service().calculate_with_report(parsed)

    local_days = parsed.data["timestamp_start"].dt.date
    assert (local_days == date(2026, 10, 25)).sum() == 100
    assert None not in results["usage_15min"]["2026-10-25"]
    assert "2026-10-25" not in results["statistics"]["incomplete_days"]


def test_pv_production_does_not_reduce_consumption():
    parsed = parse(SAMPLE)
    slots = [kwh for device in parsed.devices for item in device.actions for kwh in item.slots_kwh]
    summary = parsed.report.devices

    assert parsed.data["kwh"].sum() == pytest.approx(sum(kwh for kwh in slots if kwh > 0))
    assert summary.consumption_kwh == pytest.approx(sum(kwh for kwh in slots if kwh > 0), abs=0.01)
    assert summary.pv_production_kwh == pytest.approx(-sum(kwh for kwh in slots if kwh < 0), abs=0.01)
    assert summary.pv_production_kwh > 0


def test_day_without_actions_counts_as_zero_usage_not_missing_data():
    document = copy.deepcopy(SAMPLE)
    document["period"]["end"] = "2026-10-22T00:00:00+02:00"

    parsed = parse(document)
    results = calculation_service().calculate_with_report(parsed)

    assert len(parsed.data) == 3 * 96
    assert results["usage_15min"]["2026-10-21"] == [0.0] * 96
    assert results["statistics"]["has_missing_data"] is False


def test_import_report_summarizes_devices():
    report = parse(SAMPLE).report.to_dict()

    assert report["rows_total"] == report["rows_imported"] == 62
    assert report["devices"]["devices_count"] == 24
    assert report["devices"]["actions_count"] == 62
    assert len(report["devices"]["categories"]) == 7


def test_records_keep_device_settings_programs_and_ev_session():
    devices = {device.device_id: device for device in parse(SAMPLE).devices}
    washer, charger = devices["dev_wm_01"], devices["dev_ev_01"]

    assert (washer.flexibility_mode, washer.allowed_window_from.isoformat()) == ("shiftable", "07:00:00")
    assert [program.program_id for program in washer.programs] == ["cotton_60", "quick_40"]
    session = next(item for item in charger.actions if item.deadline)
    assert session.plugged_in is not None and session.plugged_in <= session.start


def test_invalid_file_is_rejected_with_errors_pointing_to_actions():
    document = copy.deepcopy(SAMPLE)
    next(item for item in document["energy_usage"] if item["action_id"] == "act_0016")["energy_kwh"] = 1.5

    with pytest.raises(FileImportError) as exc_info:
        parse(document)

    error = exc_info.value
    assert error.status_code == 422
    assert error.detail == "Plik urządzeń zawiera błędy (1)."
    assert error.errors == [{
        "location": "act_0016",
        "message": "suma profilu 1.95 kWh różni się od energy_kwh 1.50",
        "device_id": "dev_wm_01",
        "device_name": "Pralka Bosch",
        "action_id": "act_0016",
    }]


def test_structure_error_names_the_device():
    document = copy.deepcopy(SAMPLE)
    next(item for item in document["devices"] if item["device_id"] == "dev_kt_01").pop("device_category")

    with pytest.raises(FileImportError) as exc_info:
        parse(document)

    assert exc_info.value.errors == [{
        "location": "dev_kt_01",
        "message": "brak pola device_category",
        "device_id": "dev_kt_01",
        "device_name": "Czajnik elektryczny",
        "action_id": None,
    }]


def test_long_error_list_is_limited_but_counted():
    document = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
    for item in document["energy_usage"]:
        item["device_id"] = "dev_nieznane"

    with pytest.raises(FileImportError) as exc_info:
        parse(document)

    error = exc_info.value
    actions_count = len(document["energy_usage"])
    assert error.detail == f"Plik urządzeń zawiera błędy ({actions_count})."
    assert error.errors_count == actions_count
    assert len(error.errors) == 100
    assert error.http_detail() == {"message": error.detail, "errors": error.errors, "errors_count": actions_count}


def test_grid_limit_is_not_checked_on_import():
    assert not validate_document(copy.deepcopy(SAMPLE), max_grid_kw=1).is_valid

    assert parse(SAMPLE).report.detected_format == "devices"
