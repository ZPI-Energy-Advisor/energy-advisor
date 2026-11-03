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
from app.models.DeviceInstanceFile import DeviceInstanceFile
from app.models.DeviceProgram import DeviceProgram
from app.models.DeviceSlotUsage import DeviceSlotUsage
from app.models.DeviceType import DeviceType
from app.models.EnergyDataFile import EnergyDataFile
from app.parsers import parse_energy_file
from app.parsers.device_records import ActionRecord, DeviceRecord, ProgramRecord
from app.parsers.device_validation import DEVICE_CATEGORIES, DEVICE_TYPES, SLOT
from app.repositories.device_repository import DeviceRepository
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.simulation_repository import SimulationRepository
from app.services.energy_file_service import EnergyFileService


DEMO_FILE = Path(__file__).parent / "fixtures" / "devices_demo_30d.json"
DEMO = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
SAVE_LIMIT_SECONDS = 3


with DEMO_FILE.open("rb") as demo_handle:
    DEMO_RECORDS = parse_energy_file(demo_handle).devices


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
    if model in (DeviceAction, DeviceSlotUsage):
        return query.filter(model.energy_data_file_id == file_id).scalar()
    link = DeviceInstanceFile.device_instance_id == (DeviceInstance.id if model is DeviceInstance else model.device_instance_id)
    return query.join(DeviceInstanceFile, link).filter(DeviceInstanceFile.energy_data_file_id == file_id).scalar()


def devices_of(db, user) -> dict[str, DeviceInstance]:
    return {device.source_device_id: device for device in DeviceRepository(db).list_for_user(user.id)}


def action_by_id(db, energy_file, action_id: str) -> DeviceAction:
    return (
        db.query(DeviceAction)
        .filter(DeviceAction.energy_data_file_id == energy_file.id, DeviceAction.source_action_id == action_id)
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


def delete_file(db, user, energy_file) -> None:
    EnergyFileService(EnergyDataFileRepository(db), SimulationRepository(db), DeviceRepository(db), None).delete_file(
        energy_file.id, user.id
    )


def test_deleting_only_file_removes_devices_actions_and_slots(db, user_a, saved_demo):
    file_id = saved_demo.id
    device_ids = [device.id for device in devices_of(db, user_a).values()]
    delete_file(db, user_a, saved_demo)

    assert devices_of(db, user_a) == {}
    assert db.query(DeviceProgram).filter(DeviceProgram.device_instance_id.in_(device_ids)).count() == 0
    for model in (DeviceAction, DeviceSlotUsage):
        assert count(db, model, file_id) == 0


def test_deleting_user_removes_devices_actions_and_slots(db, user_a, saved_demo):
    file_id = saved_demo.id
    user_id = user_a.id
    db.delete(user_a)
    db.commit()

    assert db.query(DeviceInstance).filter(DeviceInstance.user_id == user_id).count() == 0
    for model in (DeviceAction, DeviceSlotUsage):
        assert count(db, model, file_id) == 0


def test_list_for_file_is_scoped_to_user(db, user_b, saved_demo):
    assert DeviceRepository(db).list_for_file(saved_demo.id, user_b.id) == []


def kettle(action_id="act_1", **overrides) -> DeviceRecord:
    start = datetime(2026, 10, 19, 6, 45, tzinfo=timezone(timedelta(hours=2)))
    action = ActionRecord(action_id, start, start + SLOT, 0.12, [0.12])
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


def test_action_with_unknown_program_is_rejected_before_any_insert(db, user_a, energy_file):
    broken = kettle()
    broken.actions[0].program_id = "eco"

    with pytest.raises(ValueError, match="eco"):
        DeviceRepository(db).save_for_file(user_id=user_a.id, energy_data_file_id=energy_file.id, devices=[broken])

    assert count(db, DeviceInstance, energy_file.id) == 0


def test_time_without_timezone_is_rejected(db, user_a, energy_file):
    broken = kettle()
    broken.actions[0].deadline = datetime(2026, 10, 19, 8, 0)

    with pytest.raises(ValueError, match="bez strefy"):
        DeviceRepository(db).save_for_file(user_id=user_a.id, energy_data_file_id=energy_file.id, devices=[broken])

    assert count(db, DeviceInstance, energy_file.id) == 0


def new_file(db, user, name="kolejny.json") -> EnergyDataFile:
    return EnergyDataFileRepository(db).create(user_id=user.id, file_name=name)


def save(db, user, energy_file, devices) -> None:
    DeviceRepository(db).save_for_file(user_id=user.id, energy_data_file_id=energy_file.id, devices=devices)
    db.commit()


def washer(name: str, programs: list[ProgramRecord]) -> DeviceRecord:
    start = datetime(2026, 11, 2, 9, 0, tzinfo=timezone(timedelta(hours=1)))
    profile = programs[0].profile_kwh
    action = ActionRecord("act_1", start, start + len(profile) * SLOT, round(sum(profile), 2), list(profile),
                          program_id=programs[0].program_id)
    return DeviceRecord(device_id="dev_wm_01", name=name, device_type="washing_machine", device_category="AGD",
                        flexibility_mode="shiftable", programs=programs, actions=[action])


def slots_of(db, action: DeviceAction) -> list[float]:
    rows = db.query(DeviceSlotUsage.kwh).filter(DeviceSlotUsage.device_action_id == action.id)
    return [kwh for (kwh,) in rows.order_by(DeviceSlotUsage.slot_start)]


def test_second_file_of_the_same_home_does_not_duplicate_devices(db, user_a, saved_demo):
    second = new_file(db, user_a)
    save(db, user_a, second, DEMO_RECORDS)

    assert len(devices_of(db, user_a)) == len(DEMO["devices"])
    # Numeracja akcji powtarza się w obu plikach, a akcje każdego pliku są zapisane osobno.
    assert count(db, DeviceAction, saved_demo.id) == count(db, DeviceAction, second.id) == len(DEMO["energy_usage"])


def test_latest_file_updates_device_and_merges_programs(db, user_a, saved_demo):
    old_action = (
        db.query(DeviceAction)
        .join(DeviceProgram, DeviceAction.device_program_id == DeviceProgram.id)
        .filter(DeviceAction.energy_data_file_id == saved_demo.id, DeviceProgram.source_program_id == "cotton_60")
        .first()
    )
    old_slots = slots_of(db, old_action)

    save(db, user_a, new_file(db, user_a), [washer("Pralka Bosch Serie 6", [
        ProgramRecord("cotton_60", "Bawełna 60°C", 120, [0.5] * 8),
        ProgramRecord("wool_30", "Wełna 30°C", 45, [0.2, 0.1, 0.1]),
    ])])

    device = devices_of(db, user_a)["dev_wm_01"]
    programs = {
        program.source_program_id: program
        for program in db.query(DeviceProgram).filter(DeviceProgram.device_instance_id == device.id)
    }
    assert device.name == "Pralka Bosch Serie 6"
    assert programs["cotton_60"].profile_kwh == [0.5] * 8
    # quick_40 nie ma w nowym pliku, ale zostaje: mogą go używać akcje z poprzednich plików.
    assert set(programs) == {"cotton_60", "quick_40", "wool_30"}
    # Historia poprzedniego pliku się nie zmienia.
    assert slots_of(db, old_action) == old_slots


def test_device_absent_from_new_file_stays_in_home(db, user_a, saved_demo):
    save(db, user_a, new_file(db, user_a), [kettle()])

    assert len(devices_of(db, user_a)) == len(DEMO["devices"])


def test_deleting_file_keeps_devices_present_in_other_files(db, user_a, saved_demo):
    second = new_file(db, user_a)
    save(db, user_a, second, [kettle(), kettle(action_id="act_2", device_id="dev_kt_02", name="Czajnik w garażu")])

    delete_file(db, user_a, second)

    devices = devices_of(db, user_a)
    assert "dev_kt_01" in devices and "dev_kt_02" not in devices
    assert len(devices) == len(DEMO["devices"])
    assert count(db, DeviceAction, second.id) == 0
    assert count(db, DeviceAction, saved_demo.id) == len(DEMO["energy_usage"])


def test_device_without_actions_stays_while_its_file_exists(db, user_a, energy_file):
    lamp = kettle(device_id="dev_lamp_01", name="Lampa", device_type="light", device_category="Oświetlenie", actions=[])
    save(db, user_a, energy_file, [lamp])
    second = new_file(db, user_a)
    save(db, user_a, second, [kettle()])

    delete_file(db, user_a, second)

    assert set(devices_of(db, user_a)) == {"dev_lamp_01"}


def test_each_user_has_own_home(db, user_a, user_b, saved_demo):
    save(db, user_b, new_file(db, user_b), [kettle()])

    assert set(devices_of(db, user_b)) == {"dev_kt_01"}
    assert len(devices_of(db, user_a)) == len(DEMO["devices"])


def test_list_for_file_returns_only_devices_present_in_that_file(db, user_a, saved_demo):
    second = new_file(db, user_a)
    save(db, user_a, second, [kettle()])

    assert [device.source_device_id for device in DeviceRepository(db).list_for_file(second.id, user_a.id)] == [
        "dev_kt_01"
    ]
