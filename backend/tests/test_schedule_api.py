import datetime
from datetime import timezone
from zoneinfo import ZoneInfo

from app.api.v1.deps import get_schedule_price_service
from app.models.EnergyDataFile import EnergyDataFile
from app.parsers.device_records import ActionRecord, DeviceRecord, ProgramRecord
from app.repositories.device_repository import DeviceRepository
from app.services.energy_file_service import EnergyFileService
from app.services.schedule_prices import SchedulePrices
from app.services.scheduling import SLOT
from main import app


WARSAW = ZoneInfo("Europe/Warsaw")
WASH = [0.5, 0.5, 0.25, 0.25]


def at(day: int, hour: int) -> datetime.datetime:
    return datetime.datetime(2026, 10, day, hour, tzinfo=WARSAW).astimezone(timezone.utc)


class _Prices:
    """Ceny kwadransów taryfy z profilu: drogo przez całą dobę, tanio 13:00-15:00 każdego dnia."""

    def prices(self, start, end):
        prices, slot = {}, start
        while slot < end:
            prices[slot] = 0.2 if 13 <= slot.astimezone(WARSAW).hour < 15 else 1.0
            slot += SLOT
        return prices

    def for_user(self, user_id, start, end, exports=None):
        return SchedulePrices(prices=self.prices(start, end), description="PGE, G11")


class _PricesWithGridLimit(_Prices):
    def for_user(self, user_id, start, end, exports=None):
        return SchedulePrices(prices=self.prices(start, end), description="PGE, G11", max_grid_kw=12.5)


class _PricesWithPvNote(_Prices):
    def for_user(self, user_id, start, end, exports=None):
        return SchedulePrices(prices=self.prices(start, end), description="PGE, G11", pv_note="Uzupełnij PV.")


class _NoPricesOn20th(_Prices):
    def prices(self, start, end):
        return {slot: price for slot, price in super().prices(start, end).items()
                if slot.astimezone(WARSAW).day != 20}


class _NoPrices(_Prices):
    def prices(self, start, end):
        return {}


def override_prices(prices=_Prices):
    app.dependency_overrides[get_schedule_price_service] = prices


def get_schedule(client, energy_file, prices=_Prices, **params):
    override_prices(prices)
    try:
        return client.get(f"/api/v1/energy-files/{energy_file.id}/schedule", params=params)
    finally:
        app.dependency_overrides.pop(get_schedule_price_service, None)


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
        app.dependency_overrides.pop(get_schedule_price_service, None)

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
        app.dependency_overrides.pop(get_schedule_price_service, None)

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
        app.dependency_overrides.pop(get_schedule_price_service, None)

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


def test_period_with_only_pv_production_is_rejected(db, user_a, client_a):
    energy_file = create_devices_file(db, user_a)
    pv = DeviceRecord(
        device_id="dev_pv_01", name="Falownik PV", device_type="pv_inverter", device_category="OZE",
        flexibility_mode="fixed", max_power_kw=5.0,
        actions=[ActionRecord("act_pv", at(21, 12), at(21, 13), -2.0, [-0.5] * 4)],
    )
    DeviceRepository(db).save_for_file(user_id=user_a.id, energy_data_file_id=energy_file.id, devices=[pv])
    energy_file.data_end = datetime.date(2026, 10, 21)
    db.commit()

    response = get_schedule(client_a, energy_file, **{"from": "2026-10-21", "to": "2026-10-21"})

    assert response.status_code == 422
    assert "poboru energii" in response.json()["detail"]


def test_period_without_any_prices_is_rejected(db, user_a, client_a):
    energy_file = create_devices_file(db, user_a)

    response = get_schedule(client_a, energy_file, _NoPrices)

    assert response.status_code == 422
    assert "Brak cen" in response.json()["detail"]


def test_actions_without_prices_are_counted_with_their_days(db, user_a, client_a):
    energy_file = create_devices_file(db, user_a)

    body = get_schedule(client_a, energy_file, _NoPricesOn20th).json()

    assert body["missing_price_actions"] == 1
    assert body["missing_price_days"] == ["2026-10-20"]
    actions = {item["action_id"]: item for item in body["actions"]}
    assert actions["act_2"]["reason"] == "missing_prices"
    assert actions["act_1"]["status"] == "moved"


def test_schedule_passes_pv_warning(db, user_a, client_a):
    energy_file = create_devices_file(db, user_a)

    body = get_schedule(client_a, energy_file, prices=_PricesWithPvNote).json()

    assert body["pv_note"] == "Uzupełnij PV."
    assert get_schedule(client_a, energy_file).json()["pv_note"] is None


def test_schedule_returns_grid_limit_from_profile(db, user_a, client_a):
    energy_file = create_devices_file(db, user_a)

    assert get_schedule(client_a, energy_file, prices=_PricesWithGridLimit).json()["max_grid_kw"] == 12.5


def test_schedule_of_other_users_file_returns_404(db, user_a, client_b):
    energy_file = create_devices_file(db, user_a)

    assert client_b.get(f"/api/v1/energy-files/{energy_file.id}/schedule").status_code == 404


def test_ev_session_keeps_original_end_and_returns_charging_periods(db, user_a, client_a):
    energy_file = EnergyDataFile(
        user_id=user_a.id, file_name="ev.json", status=EnergyDataFile.STATUS_COMPLETED,
        data_start=datetime.date(2026, 10, 19), data_end=datetime.date(2026, 10, 19),
    )
    db.add(energy_file)
    db.commit()
    # 7,5 kWh od 8:00 (10 kwadransów po 3 kW), auto do 17:00; tanie 13:00-15:00 mieszczą 6 kWh,
    # reszta idzie na najwcześniejsze kwadranse, więc plan ma przerwę.
    charger = DeviceRecord(
        device_id="dev_ev_01", name="Ładowarka EV", device_type="ev_charger", device_category="Pojazd elektryczny",
        flexibility_mode="interruptible", max_power_kw=3.0,
        actions=[ActionRecord(
            "ev_1", at(19, 8), at(19, 8) + 10 * SLOT, 7.5, [0.75] * 10, plugged_in=at(19, 8), deadline=at(19, 17),
        )],
    )
    DeviceRepository(db).save_for_file(user_id=user_a.id, energy_data_file_id=energy_file.id, devices=[charger])
    db.commit()

    body = get_schedule(client_a, energy_file).json()

    ev, = body["actions"]
    assert ev["original_start"] == "2026-10-19T08:00:00+02:00"
    assert ev["original_end"] == "2026-10-19T10:30:00+02:00"  # oryginał, nie długość planu z przerwą
    assert ev["status"] == "moved"
    assert ev["energy_kwh"] == 7.5
    assert ev["charging"] == [
        {"start": "2026-10-19T08:00:00+02:00", "end": "2026-10-19T08:30:00+02:00"},
        {"start": "2026-10-19T13:00:00+02:00", "end": "2026-10-19T15:00:00+02:00"},
    ]
    assert ev["cost_after"] < ev["cost_before"]


def _create_file_with(db, user, *devices) -> EnergyDataFile:
    energy_file = EnergyDataFile(
        user_id=user.id, file_name="dom.json", status=EnergyDataFile.STATUS_COMPLETED,
        data_start=datetime.date(2026, 10, 19), data_end=datetime.date(2026, 10, 19),
    )
    db.add(energy_file)
    db.commit()
    DeviceRepository(db).save_for_file(user_id=user.id, energy_data_file_id=energy_file.id, devices=list(devices))
    db.commit()
    return energy_file


def test_charging_periods_only_for_ev_sessions(db, user_a, client_a):
    # Pralka z przerwą w programie (0 kWh w środku) nie jest ładowaniem z przerwami: jeden pasek start-end.
    washer = DeviceRecord(
        device_id="dev_wm_01", name="Pralka", device_type="washing_machine", device_category="AGD",
        flexibility_mode="shiftable",
        actions=[ActionRecord("act_1", at(19, 18), at(19, 18) + 3 * SLOT, 0.5, [0.3, 0.0, 0.2])],
    )
    energy_file = _create_file_with(db, user_a, washer)

    action, = get_schedule(client_a, energy_file).json()["actions"]

    assert action["status"] == "moved"
    assert action["charging"] is None


def test_bill_until_shows_tail_after_period(db, user_a, client_a, monkeypatch):
    # Ładowanie EV zaczęte 19.10 o 23:00 kończy się 20.10 o 1:00: rachunek obejmuje ten ogon.
    charger = DeviceRecord(
        device_id="dev_ev_01", name="Ładowarka EV", device_type="ev_charger", device_category="Pojazd elektryczny",
        flexibility_mode="interruptible", max_power_kw=3.0,
        actions=[ActionRecord(
            "ev_1", at(19, 23), at(20, 1), 6.0, [0.75] * 8, plugged_in=at(19, 23), deadline=at(20, 1),
        )],
    )
    energy_file = _create_file_with(db, user_a, charger)

    assert get_schedule(client_a, energy_file).json()["bill_until"] is None  # bez rachunku nie ma czego opisywać

    monkeypatch.setattr(EnergyFileService, "_bills", lambda *args: {"bill_before": 10.0, "bill_after": 9.0})
    body = get_schedule(client_a, energy_file).json()

    assert body["bill_until"] == "2026-10-20T01:00:00+02:00"
