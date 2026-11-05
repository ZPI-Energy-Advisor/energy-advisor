from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from device.driver import IDLE, OFF, RUNNING, DeviceDriver, DeviceError
from device.models import DeviceConfig


CEST = timezone(timedelta(hours=2))
START = datetime(2026, 10, 19, 13, 0, tzinfo=CEST)
COTTON_PROFILE = [0.45, 0.45, 0.3, 0.1, 0.1, 0.15, 0.2, 0.2]


def _washing_machine() -> DeviceDriver:
    return DeviceDriver(DeviceConfig.model_validate({
        "device_id": "dev_wm_01",
        "device_name": "Pralka Bosch",
        "device_type": "washing_machine",
        "device_category": "AGD",
        "flexibility": {"mode": "shiftable", "allowed_window": {"from": "07:00", "to": "22:00"}},
        "programs": [
            {"program_id": "cotton_60", "program_name": "Bawełna 60°C", "duration_min": 120,
             "profile_kwh": COTTON_PROFILE},
            {"program_id": "quick_40", "program_name": "Szybkie 40°C", "duration_min": 60,
             "profile_kwh": [0.35, 0.25, 0.1, 0.1]},
        ],
    }))


def _plain_device(device_type="light", category="Oświetlenie", power=0.06, mode="fixed") -> DeviceDriver:
    return DeviceDriver(DeviceConfig.model_validate({
        "device_id": "dev_x",
        "device_name": "Urządzenie",
        "device_type": device_type,
        "device_category": category,
        "max_power_kw": power,
        "flexibility": {"mode": mode},
    }))


def _hours(value: float) -> datetime:
    return START + timedelta(hours=value)


def test_program_finishes_after_tick_and_reports_profile_sum():
    driver = _washing_machine()
    driver.tick(START)
    driver.start_program("cotton_60")

    result = driver.tick(_hours(2))

    assert driver.state == IDLE
    assert result["energy_kwh"] == pytest.approx(sum(COTTON_PROFILE))
    assert [event["type"] for event in result["events"]] == ["device_started", "device_finished"]
    finished = result["events"][1]
    assert finished["sim_time"] == "2026-10-19T15:00:00+02:00"
    assert finished["data"]["energy_kwh"] == pytest.approx(1.95)
    assert finished["data"]["interrupted"] is False
    assert driver.energy()["last_action"] == {
        "program_id": "cotton_60",
        "started_at": "2026-10-19T13:00:00+02:00",
        "ended_at": "2026-10-19T15:00:00+02:00",
        "energy_kwh": pytest.approx(1.95),
        "interrupted": False,
    }


def test_quarter_ticks_follow_profile_and_give_the_same_sum():
    driver = _washing_machine()
    driver.tick(START)
    driver.start_program("cotton_60")

    steps = [driver.tick(_hours((i + 1) / 4))["energy_kwh"] for i in range(8)]

    assert steps == pytest.approx(COTTON_PROFILE)
    assert driver.energy()["total_kwh"] == pytest.approx(1.95)
    assert driver.state == IDLE


def test_tick_past_program_end_stops_at_end_time():
    driver = _washing_machine()
    driver.tick(START)
    driver.start_program("cotton_60")

    result = driver.tick(_hours(5))

    assert result["energy_kwh"] == pytest.approx(1.95)
    assert result["events"][1]["sim_time"] == "2026-10-19T15:00:00+02:00"
    assert driver.tick(_hours(6))["energy_kwh"] == 0


def test_status_shows_running_program_and_quarter_power():
    driver = _washing_machine()
    driver.tick(START)
    driver.start_program("cotton_60")
    driver.tick(_hours(0.25))

    status = driver.status()

    assert status["state"] == RUNNING
    assert status["program_id"] == "cotton_60"
    assert status["program_started_at"] == "2026-10-19T13:00:00+02:00"
    assert status["program_ends_at"] == "2026-10-19T15:00:00+02:00"
    assert status["power_kw"] == pytest.approx(1.8)
    assert status["energy_kwh"] == pytest.approx(0.45)
    assert status["sim_time"] == "2026-10-19T13:15:00+02:00"


def test_program_in_progress_blocks_next_start_and_on():
    driver = _washing_machine()
    driver.tick(START)
    driver.start_program("cotton_60")

    with pytest.raises(DeviceError) as start_error:
        driver.start_program("quick_40")
    with pytest.raises(DeviceError) as on_error:
        driver.turn_on()

    assert (start_error.value.status_code, start_error.value.code) == (409, "invalid_state")
    assert (on_error.value.status_code, on_error.value.code) == (409, "invalid_state")


def test_unknown_program_is_rejected():
    with pytest.raises(DeviceError) as error:
        _washing_machine().start_program("nie_ma")

    assert (error.value.status_code, error.value.code) == (404, "program_not_found")


def test_off_during_program_interrupts_with_energy_so_far():
    driver = _washing_machine()
    driver.tick(START)
    driver.start_program("cotton_60")
    driver.tick(_hours(0.5))

    driver.turn_off()

    assert driver.state == OFF
    last_action = driver.energy()["last_action"]
    assert last_action["interrupted"] is True
    assert last_action["energy_kwh"] == pytest.approx(0.9)
    assert last_action["ended_at"] == "2026-10-19T13:30:00+02:00"
    assert driver.tick(_hours(1))["events"][0]["data"]["interrupted"] is True
    assert driver.energy()["total_kwh"] == pytest.approx(0.9)


def test_on_for_device_with_programs_only_waits():
    driver = _washing_machine()
    driver.tick(START)

    driver.turn_on()

    assert driver.state == IDLE
    assert driver.tick(_hours(1))["energy_kwh"] == 0


def test_lamp_two_hours_reports_energy_within_power_limit():
    driver = _plain_device()
    driver.tick(START)
    driver.turn_on()

    steps = [driver.tick(_hours((i + 1) / 4))["energy_kwh"] for i in range(8)]
    driver.turn_off()

    assert all(step <= 0.06 * 0.25 + 1e-9 for step in steps)
    last_action = driver.energy()["last_action"]
    assert last_action["energy_kwh"] == pytest.approx(0.12)
    assert last_action["program_id"] is None
    assert last_action["interrupted"] is False


def test_second_on_does_not_restart_action():
    driver = _plain_device()
    driver.tick(START)
    driver.turn_on()
    driver.tick(_hours(1))

    driver.turn_on()
    driver.tick(_hours(2))
    driver.turn_off()

    assert driver.energy()["last_action"]["started_at"] == "2026-10-19T13:00:00+02:00"


def test_ev_pause_and_resume_are_separate_actions():
    driver = _plain_device("ev_charger", "Pojazd elektryczny", 3.7, "interruptible")
    driver.tick(START)
    driver.turn_on()
    driver.tick(_hours(1))
    driver.turn_off()
    first_action = driver.energy()["last_action"]

    driver.tick(_hours(2))  # przerwa w ładowaniu
    assert driver.status()["power_kw"] == 0

    driver.turn_on()
    driver.tick(_hours(3))
    driver.turn_off()

    assert first_action["energy_kwh"] == pytest.approx(3.7)
    assert first_action["ended_at"] == "2026-10-19T14:00:00+02:00"
    assert driver.energy()["last_action"]["started_at"] == "2026-10-19T15:00:00+02:00"
    assert driver.energy()["total_kwh"] == pytest.approx(7.4)


def test_pv_reports_production_as_negative():
    driver = _plain_device("pv_inverter", "OZE", 6.0)
    driver.tick(START)
    driver.turn_on()

    result = driver.tick(_hours(1))

    assert result["energy_kwh"] == pytest.approx(-6.0)
    assert result["power_kw"] == pytest.approx(-6.0)
    assert driver.energy()["total_kwh"] == pytest.approx(-6.0)


def test_off_device_reports_plain_zero_for_pv():
    driver = _plain_device("pv_inverter", "OZE", 6.0)

    assert str(driver.status()["power_kw"]) == "0.0"


def test_repeated_tick_changes_nothing():
    driver = _plain_device()
    driver.tick(START)
    driver.turn_on()
    driver.tick(_hours(1))

    result = driver.tick(_hours(1))

    assert result["energy_kwh"] == 0
    assert result["events"] == []
    assert driver.energy()["total_kwh"] == pytest.approx(0.06)


def test_repeated_tick_keeps_command_events_for_next_step():
    driver = _plain_device()
    driver.tick(START)
    driver.turn_on()

    assert driver.tick(START)["events"] == []
    assert [event["type"] for event in driver.tick(_hours(1))["events"]] == ["device_started"]


def test_earlier_tick_is_rejected_and_keeps_state():
    driver = _plain_device()
    driver.tick(_hours(1))

    with pytest.raises(DeviceError) as error:
        driver.tick(START)

    assert (error.value.status_code, error.value.code) == (409, "stale_tick")
    assert driver.status()["sim_time"] == "2026-10-19T14:00:00+02:00"


def test_naive_tick_is_rejected():
    with pytest.raises(DeviceError) as error:
        _plain_device().tick(datetime(2026, 10, 19, 13, 0))

    assert (error.value.status_code, error.value.code) == (422, "validation_error")


def test_first_tick_sets_reference_without_energy():
    driver = _plain_device()
    driver.turn_on()

    result = driver.tick(START)

    assert result["energy_kwh"] == 0
    assert result["events"][0]["sim_time"] == "2026-10-19T13:00:00+02:00"
    assert driver.tick(_hours(1))["energy_kwh"] == pytest.approx(0.06)


def test_program_before_first_tick_starts_at_first_tick():
    driver = _washing_machine()
    driver.start_program("cotton_60")
    assert driver.status()["program_started_at"] is None

    driver.tick(START)

    assert driver.status()["program_started_at"] == "2026-10-19T13:00:00+02:00"
    assert driver.tick(_hours(2))["energy_kwh"] == pytest.approx(1.95)


def test_off_before_first_tick_leaves_no_action():
    driver = _plain_device()
    driver.turn_on()

    driver.turn_off()
    result = driver.tick(START)

    assert driver.energy()["last_action"] is None
    assert result["events"] == []


def test_energy_follows_real_elapsed_time_across_dst_change():
    warsaw = ZoneInfo("Europe/Warsaw")
    driver = _plain_device(power=1.0)
    driver.tick(datetime(2026, 10, 25, 1, 0, tzinfo=warsaw))
    driver.turn_on()

    # Między 1:00 a 4:00 czasu lokalnego tej nocy mijają 4 godziny, nie 3.
    result = driver.tick(datetime(2026, 10, 25, 4, 0, tzinfo=warsaw))

    assert result["energy_kwh"] == pytest.approx(4.0)


def test_tick_with_lower_offset_on_same_wall_clock_is_forward_in_time():
    driver = _plain_device(power=1.0)
    driver.tick(datetime(2026, 10, 25, 2, 30, tzinfo=timezone(timedelta(hours=2))))
    driver.turn_on()

    result = driver.tick(datetime(2026, 10, 25, 2, 15, tzinfo=timezone(timedelta(hours=1))))

    assert result["energy_kwh"] == pytest.approx(0.75)


def test_update_config_changes_name_without_touching_work():
    driver = _washing_machine()
    driver.tick(START)
    driver.start_program("cotton_60")

    driver.update_config({"device_name": "Pralka w łazience", "device_category": "Inne"})

    assert driver.config.device_name == "Pralka w łazience"
    assert driver.config.device_category == "Inne"
    assert driver.status()["state"] == RUNNING


def test_update_config_accepts_full_object_with_same_values():
    driver = _washing_machine()
    full_config = driver.config.model_dump(by_alias=True)

    driver.update_config({**full_config, "device_name": "Nowa nazwa"})

    assert driver.config.device_name == "Nowa nazwa"


@pytest.mark.parametrize("changes", [
    {"max_power_kw": 3.0},
    {"device_type": "dishwasher"},
    {"flexibility": {"mode": "fixed"}},
    {"programs": [{"program_id": "eco", "program_name": "Eco", "duration_min": 15, "profile_kwh": [0.1]}]},
])
def test_update_config_rejects_fields_requiring_restart(changes):
    driver = _washing_machine()

    with pytest.raises(DeviceError) as error:
        driver.update_config({**changes, "device_name": "Nowa nazwa"})

    assert (error.value.status_code, error.value.code) == (409, "config_requires_restart")
    assert driver.config.device_name == "Pralka Bosch"


def test_update_config_rejects_invalid_values():
    with pytest.raises(DeviceError) as error:
        _washing_machine().update_config({"device_name": None})

    assert (error.value.status_code, error.value.code) == (422, "validation_error")


def test_device_without_programs_requires_power():
    with pytest.raises(ValueError, match="max_power_kw"):
        _plain_device(power=None)


def test_program_profile_must_match_duration():
    with pytest.raises(ValueError, match="profile_kwh"):
        DeviceConfig.model_validate({
            "device_id": "d", "device_name": "d", "device_type": "dishwasher", "device_category": "AGD",
            "flexibility": {"mode": "shiftable"},
            "programs": [{"program_id": "p", "program_name": "p", "duration_min": 30, "profile_kwh": [0.1]}],
        })
