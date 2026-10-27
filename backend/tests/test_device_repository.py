import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.models.DeviceAction import DeviceAction
from app.models.DeviceCategory import DeviceCategory
from app.models.DeviceInstance import DeviceInstance
from app.models.DeviceProgram import DeviceProgram
from app.models.DeviceSlotUsage import DeviceSlotUsage
from app.models.DeviceType import DeviceType
from app.models.EnergyDataFile import EnergyDataFile
from app.parsers.device_records import ActionRecord, DeviceRecord, ProgramRecord
from app.repositories.device_repository import DeviceRepository
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from scripts.validate_devices_file import DEVICE_CATEGORIES, DEVICE_TYPES, SLOT, action_profile, validate_devices


DEMO_FILE = Path(__file__).parent / "fixtures" / "devices_demo_30d.json"
DEMO = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
SAVE_LIMIT_SECONDS = 3


def clock(value: str | None):
    return datetime.strptime(value, "%H:%M").time() if value else None


def records_from_document(document: dict) -> list[DeviceRecord]:
    """Zamiana poprawnego pliku urządzeń na rekordy repozytorium (to samo zrobi parser z ZP-70)."""
    devices, _ = validate_devices(document["devices"], [])
    records = {}
    for device_id, device in devices.items():
        flexibility = device["flexibility"]
        window = flexibility.get("allowed_window", {})
        records[device_id] = DeviceRecord(
            device_id=device_id,
            name=device["device_name"],
            device_type=device["device_type"],
            device_category=device["device_category"],
            flexibility_mode=flexibility["mode"],
            max_power_kw=device.get("max_power_kw"),
            allowed_window_from=clock(window.get("from")),
            allowed_window_to=clock(window.get("to")),
            max_shift_min=flexibility.get("max_shift_min"),
            programs=[
                ProgramRecord(program_id, program["program_name"], program["duration_min"], program["profile_kwh"])
                for program_id, program in device["programs"].items()
            ],
        )
    for action in document["energy_usage"]:
        start = datetime.fromisoformat(action["action_start"])
        end = datetime.fromisoformat(action["action_end"])
        slots = int((end - start) / SLOT)
        records[action["device_id"]].actions.append(ActionRecord(
            action_id=action["action_id"],
            start=start,
            end=end,
            energy_kwh=action["energy_kwh"],
            slots_kwh=action_profile(action, devices[action["device_id"]], slots),
            program_id=action.get("program_id"),
            plugged_in=datetime.fromisoformat(action["plugged_in"]) if "plugged_in" in action else None,
            deadline=datetime.fromisoformat(action["deadline"]) if "deadline" in action else None,
        ))
    return list(records.values())


DEMO_RECORDS = records_from_document(DEMO)


@pytest.fixture
def energy_file(db, user_a) -> EnergyDataFile:
    return EnergyDataFileRepository(db).create(user_id=user_a.id, file_name="devices_demo_30d.json")


@pytest.fixture
def saved_demo(db, user_a, energy_file) -> EnergyDataFile:
    DeviceRepository(db).save_for_file(user_id=user_a.id, energy_data_file_id=energy_file.id, devices=DEMO_RECORDS)
    db.commit()
    return energy_file


def count(db, model, file_id) -> int:
    query = db.query(func.count()).select_from(model)
    if model is DeviceSlotUsage:
        return query.filter(DeviceSlotUsage.energy_data_file_id == file_id).scalar()
    if model is not DeviceInstance:
        query = query.join(DeviceInstance, model.device_instance_id == DeviceInstance.id)
    return query.filter(DeviceInstance.energy_data_file_id == file_id).scalar()


def action_by_id(db, energy_file, action_id: str) -> DeviceAction:
    return (
        db.query(DeviceAction)
        .join(DeviceInstance, DeviceAction.device_instance_id == DeviceInstance.id)
        .filter(DeviceInstance.energy_data_file_id == energy_file.id, DeviceAction.source_action_id == action_id)
        .one()
    )


def test_dictionaries_match_validator(db):
    assert {row.code for row in db.query(DeviceCategory)} == DEVICE_CATEGORIES
    assert {row.code for row in db.query(DeviceType)} == DEVICE_TYPES
    assert db.get(DeviceType, "ventilation").label == "Rekuperator / wentylacja"


def test_saves_whole_demo_file(db, saved_demo):
    expected_slots = sum(len(action.slots_kwh) for device in DEMO_RECORDS for action in device.actions)

    assert count(db, DeviceInstance, saved_demo.id) == len(DEMO["devices"])
    assert count(db, DeviceProgram, saved_demo.id) == sum(len(device.get("programs", [])) for device in DEMO["devices"])
    assert count(db, DeviceAction, saved_demo.id) == len(DEMO["energy_usage"])
    assert count(db, DeviceSlotUsage, saved_demo.id) == expected_slots

    saved_kwh = (
        db.query(func.sum(DeviceSlotUsage.kwh)).filter(DeviceSlotUsage.energy_data_file_id == saved_demo.id).scalar()
    )
    assert saved_kwh == pytest.approx(sum(action["energy_kwh"] for action in DEMO["energy_usage"]), abs=0.01)


def test_saving_30_days_is_fast(db, user_a, energy_file):
    started = time.perf_counter()
    DeviceRepository(db).save_for_file(user_id=user_a.id, energy_data_file_id=energy_file.id, devices=DEMO_RECORDS)
    db.commit()

    assert time.perf_counter() - started < SAVE_LIMIT_SECONDS


def test_device_keeps_flexibility_and_programs(db, user_a, saved_demo):
    devices = {device.source_device_id: device for device in DeviceRepository(db).list_for_file(saved_demo.id, user_a.id)}
    washer = devices["dev_wm_01"]

    assert (washer.device_type, washer.device_category, washer.flexibility_mode) == ("washing_machine", "AGD", "shiftable")
    assert (washer.allowed_window_from.isoformat(), washer.allowed_window_to.isoformat()) == ("07:00:00", "22:00:00")
    assert devices["dev_hp_01"].max_shift_min == 60
    assert devices["dev_vent_01"].device_category == "Ogrzewanie"

    action = db.query(DeviceAction).filter(
        DeviceAction.device_instance_id == washer.id, DeviceAction.device_program_id.isnot(None)
    ).first()
    program = db.get(DeviceProgram, action.device_program_id)
    slots = (
        db.query(DeviceSlotUsage.kwh)
        .filter(DeviceSlotUsage.device_action_id == action.id)
        .order_by(DeviceSlotUsage.slot_start)
        .all()
    )
    assert program.device_instance_id == washer.id
    assert [kwh for (kwh,) in slots] == pytest.approx(program.profile_kwh)


def test_times_are_stored_in_utc_including_dst_change(db, saved_demo):
    # 25.10.2026: doba ze zmianą czasu ma 100 kwadransów.
    action = action_by_id(db, saved_demo, "act_0645")
    slot_starts = [
        slot_start for (slot_start,) in db.query(DeviceSlotUsage.slot_start)
        .filter(DeviceSlotUsage.device_action_id == action.id)
        .order_by(DeviceSlotUsage.slot_start)
    ]

    assert action.action_start == datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
    assert action.action_end == datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc)
    assert len(slot_starts) == 100
    assert slot_starts[-1] == datetime(2026, 10, 25, 22, 45, tzinfo=timezone.utc)


def test_ev_session_window_is_stored(db, saved_demo):
    action = action_by_id(db, saved_demo, "act_0115")

    assert action.plugged_in == datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
    assert action.deadline == datetime(2026, 10, 6, 5, 30, tzinfo=timezone.utc)


def test_deleting_file_removes_devices_actions_and_slots(db, saved_demo):
    file_id = saved_demo.id
    EnergyDataFileRepository(db).delete(saved_demo)

    for model in (DeviceInstance, DeviceProgram, DeviceAction, DeviceSlotUsage):
        assert count(db, model, file_id) == 0


def test_deleting_user_removes_devices_actions_and_slots(db, user_a, saved_demo):
    file_id = saved_demo.id
    db.delete(user_a)
    db.commit()

    for model in (DeviceInstance, DeviceProgram, DeviceAction, DeviceSlotUsage):
        assert count(db, model, file_id) == 0


def test_list_for_file_is_scoped_to_user(db, user_b, saved_demo):
    assert DeviceRepository(db).list_for_file(saved_demo.id, user_b.id) == []


def kettle(**overrides) -> DeviceRecord:
    start = datetime(2026, 10, 19, 6, 45, tzinfo=timezone(timedelta(hours=2)))
    action = ActionRecord("act_1", start, start + SLOT, 0.12, [0.12])
    return DeviceRecord(**{
        "device_id": "dev_kt_01",
        "name": "Czajnik",
        "device_type": "kettle",
        "device_category": "AGD",
        "flexibility_mode": "fixed",
        "max_power_kw": 2.2,
        "actions": [action],
        **overrides,
    })


def test_repository_leaves_commit_to_caller(db, user_a, energy_file):
    DeviceRepository(db).save_for_file(user_id=user_a.id, energy_data_file_id=energy_file.id, devices=[kettle()])
    db.rollback()

    assert count(db, DeviceInstance, energy_file.id) == 0


def test_unknown_type_is_rejected_and_nothing_is_saved(db, user_a, energy_file):
    with pytest.raises(IntegrityError):
        DeviceRepository(db).save_for_file(
            user_id=user_a.id, energy_data_file_id=energy_file.id, devices=[kettle(device_type="toaster")]
        )
    db.rollback()

    assert count(db, DeviceInstance, energy_file.id) == 0


def test_slots_not_matching_action_duration_are_rejected_before_any_insert(db, user_a, energy_file):
    broken = kettle(device_id="dev_kt_02")
    broken.actions[0].slots_kwh = [0.06, 0.06]

    with pytest.raises(ValueError, match="act_1"):
        DeviceRepository(db).save_for_file(
            user_id=user_a.id, energy_data_file_id=energy_file.id, devices=[kettle(), broken]
        )

    assert count(db, DeviceInstance, energy_file.id) == 0
    assert count(db, DeviceAction, energy_file.id) == 0
