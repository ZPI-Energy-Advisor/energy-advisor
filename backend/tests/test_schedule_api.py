import datetime
from datetime import timezone
from zoneinfo import ZoneInfo

from app.api.v1.deps import get_dynamic_price_service
from app.models.EnergyDataFile import EnergyDataFile
from app.parsers.device_records import ActionRecord, DeviceRecord, ProgramRecord
from app.repositories.device_repository import DeviceRepository
from app.services.scheduling import SLOT
from main import app


WARSAW = ZoneInfo("Europe/Warsaw")
WASH = [0.5, 0.5, 0.25, 0.25]


def at(day: int, hour: int) -> datetime.datetime:
    return datetime.datetime(2026, 10, day, hour, tzinfo=WARSAW).astimezone(timezone.utc)


class _Prices:
    """Drogo przez całą dobę, tanio 13:00-15:00 każdego dnia."""

    def consumer_prices(self, start, end):
        prices, slot = {}, start
        while slot < end:
            prices[slot] = 0.2 if 13 <= slot.astimezone(WARSAW).hour < 15 else 1.0
            slot += SLOT
        return prices


def override_prices():
    app.dependency_overrides[get_dynamic_price_service] = _Prices


def create_devices_file(db, user) -> EnergyDataFile:
    energy_file = EnergyDataFile(
        user_id=user.id, file_name="dom.json", status=EnergyDataFile.STATUS_COMPLETED,
        data_start=datetime.date(2026, 10, 19), data_end=datetime.date(2026, 10, 20),
    )
    db.add(energy_file)
    db.commit()
    washer = DeviceRecord(
        device_id="dev_wm_01", name="Pralka", device_type="washing_machine", device_category="AGD",
        flexibility_mode="shiftable", programs=[ProgramRecord("cotton", "Bawełna", 60, WASH)],
        actions=[
            ActionRecord("act_1", at(19, 18), at(19, 19), 1.5, WASH, program_id="cotton"),
            ActionRecord("act_2", at(20, 18), at(20, 19), 1.5, WASH, program_id="cotton"),
        ],
    )
    tv = DeviceRecord(
        device_id="dev_tv_01", name="Telewizor", device_type="tv", device_category="RTV/IT",
        flexibility_mode="fixed", max_power_kw=0.2,
        actions=[ActionRecord("act_3", at(19, 20), at(19, 20) + 2 * SLOT, 0.1, [0.05, 0.05])],
    )
    DeviceRepository(db).save_for_file(user_id=user.id, energy_data_file_id=energy_file.id, devices=[washer, tv])
    db.commit()
    return energy_file


def test_schedule_moves_action_to_cheap_hours_and_keeps_fixed(db, user_a, client_a):
    energy_file = create_devices_file(db, user_a)
    override_prices()
    try:
        response = client_a.get(f"/api/v1/energy-files/{energy_file.id}/schedule", params={"from": "2026-10-19", "to": "2026-10-19"})
    finally:
        app.dependency_overrides.pop(get_dynamic_price_service, None)

    assert response.status_code == 200
    body = response.json()
    actions = {item["action_id"]: item for item in body["actions"]}
    assert set(actions) == {"act_1", "act_3"}
    assert actions["act_1"]["status"] == "moved"
    assert actions["act_1"]["device_name"] == "Pralka"
    assert actions["act_1"]["program_name"] == "Bawełna"
    assert actions["act_1"]["start"].startswith("2026-10-19T13:00") or actions["act_1"]["start"].startswith("2026-10-19T14:00")
    assert actions["act_1"]["original_start"] == "2026-10-19T18:00:00+02:00"
    assert actions["act_3"]["status"] == "unchanged"
    assert body["cost_after"] < body["cost_before"]
    assert len(body["prices"]) == 96


def test_schedule_uses_whole_file_period_without_range(db, user_a, client_a):
    energy_file = create_devices_file(db, user_a)
    override_prices()
    try:
        body = client_a.get(f"/api/v1/energy-files/{energy_file.id}/schedule").json()
    finally:
        app.dependency_overrides.pop(get_dynamic_price_service, None)

    assert {item["action_id"] for item in body["actions"]} == {"act_1", "act_2", "act_3"}
    assert len(body["prices"]) == 192


def test_prices_cover_the_day_on_which_the_last_action_ends(db, user_a, client_a):
    energy_file = create_devices_file(db, user_a)
    dishwasher = DeviceRecord(
        device_id="dev_dw_01", name="Zmywarka", device_type="dishwasher", device_category="AGD",
        flexibility_mode="fixed", max_power_kw=2.0,
        actions=[ActionRecord("act_4", at(19, 23), at(20, 1), 0.8, [0.1] * 8)],
    )
    DeviceRepository(db).save_for_file(user_id=user_a.id, energy_data_file_id=energy_file.id, devices=[dishwasher])
    db.commit()
    override_prices()
    try:
        body = client_a.get(
            f"/api/v1/energy-files/{energy_file.id}/schedule", params={"from": "2026-10-19", "to": "2026-10-19"}
        ).json()
    finally:
        app.dependency_overrides.pop(get_dynamic_price_service, None)

    assert len(body["prices"]) == 192
    assert body["actions"][-1]["end"].startswith("2026-10-20T01:00")


def test_file_without_device_actions_is_rejected(db, user_a, client_a):
    energy_file = EnergyDataFile(
        user_id=user_a.id, file_name="licznik.csv", status=EnergyDataFile.STATUS_COMPLETED,
        data_start=datetime.date(2026, 10, 19), data_end=datetime.date(2026, 10, 20),
    )
    db.add(energy_file)
    db.commit()

    response = client_a.get(f"/api/v1/energy-files/{energy_file.id}/schedule")

    assert response.status_code == 422
    assert "plików urządzeń" in response.json()["detail"]


def test_schedule_of_other_users_file_returns_404(db, user_a, client_b):
    energy_file = create_devices_file(db, user_a)

    assert client_b.get(f"/api/v1/energy-files/{energy_file.id}/schedule").status_code == 404
