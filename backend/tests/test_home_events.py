"""ZP-95: webhook zdarzeń huba (POST /api/v1/home/events) i stan domu (GET /api/v1/home/state)."""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, update

from app.api.v1.deps import get_home_owner_email, get_hub_api_key, get_hub_client, get_schedule_price_service
from app.clients.hub_client import API_KEY_HEADER, HubClient
from app.database import SessionLocal
from app.models.HomeConnection import HomeConnection
from app.models.HomeEvent import HomeEvent
from app.models.User import User
from app.repositories.home_event_repository import EnergyStep
from app.services.home_state_service import NOT_CONNECTED_MESSAGE, day_energy
from app.services.schedule_prices import SchedulePrices
from main import app
from test_energy_files import _create_user, _headers, client


WARSAW = ZoneInfo("Europe/Warsaw")
API_KEY = "test-hub-key"
HUB_URL = "http://hub.test"
SIMULATION_PREFIX = "sim_test_"


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _event(event_type: str, device_id: str, sim_time: str, data: dict | None = None, **fields) -> dict:
    return {
        "event_id": fields.get("event_id") or f"evt_{uuid.uuid4().hex}",
        "simulation_id": fields["simulation_id"],
        "type": event_type,
        "device_id": device_id,
        "sim_time": sim_time,
        "data": data or {},
    }


def _report(simulation_id: str, device_id: str, interval_start: str, energy_kwh: float, minutes: int = 15) -> dict:
    end = (_at(interval_start) + timedelta(minutes=minutes)).astimezone(WARSAW).isoformat()
    return _event(
        "energy_report", device_id, end,
        {"interval_start": interval_start, "energy_kwh": energy_kwh}, simulation_id=simulation_id,
    )


class FakeHub:
    """GET /home/clock i GET /home/devices z kontraktu; `down` symuluje niedostępny hub."""

    def __init__(self):
        self.down = False
        self.clock = {"sim_time": "2026-10-19T12:00:00+02:00", "running": True, "speed": 288.0}
        self.devices: list[dict] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers.get(API_KEY_HEADER) == API_KEY
        if self.down:
            raise httpx.ConnectError("Connection refused", request=request)
        if request.url.path == "/home/clock":
            return httpx.Response(200, json=self.clock)
        assert (request.method, request.url.path) == ("GET", "/home/devices")
        return httpx.Response(200, json={"sim_time": self.clock["sim_time"], "devices": self.devices})


def _device(device_id: str, state: str = "running", power_kw: float | None = 0.06, **fields) -> dict:
    return {
        "device_id": device_id, "device_name": fields.get("name", device_id), "port": 9101, "state": state,
        "program_id": fields.get("program_id"), "program_started_at": None, "program_ends_at": None,
        "power_kw": power_kw, "energy_kwh": 0.0,
    }


class FlatPrices:
    """Cena 2 zł/kWh w każdym kwadransie, jak SchedulePriceService.for_user; `error` symuluje brak profilu."""

    PRICE = 2.0

    def __init__(self):
        self.error: Exception | None = None
        self.calls: list[tuple] = []

    def for_user(self, user_id, start_utc, end_utc, exports=None) -> SchedulePrices:
        self.calls.append((user_id, start_utc, end_utc))
        if self.error:
            raise self.error
        prices, slot = {}, start_utc
        while slot < end_utc:
            prices[slot] = self.PRICE
            slot += timedelta(minutes=15)
        return SchedulePrices(prices=prices, description="test")


@pytest.fixture
def db():
    session = SessionLocal()
    session.created_users = []
    yield session
    session.rollback()
    session.execute(delete(HomeEvent).where(HomeEvent.simulation_id.like(f"{SIMULATION_PREFIX}%")))
    for user_id in session.created_users:
        session.query(User).filter(User.id == user_id).delete()
    session.execute(update(HomeConnection).values(
        user_id=None, connected_at=None, registry_hash=None, synced_at=None, sync_error=None,
    ))
    session.commit()
    session.close()


@pytest.fixture
def home(db):
    """Podłączony dom właściciela, drugi użytkownik, FakeHub i stałe ceny kwadransów."""
    owner, other = _create_user(db), _create_user(db)
    db.execute(update(HomeConnection).values(user_id=owner.id, connected_at=datetime.now(timezone.utc)))
    db.commit()
    hub, prices = FakeHub(), FlatPrices()
    simulation_id = f"{SIMULATION_PREFIX}{uuid.uuid4().hex}"
    hub.clock["simulation_id"] = simulation_id
    hub_client = HubClient(httpx.Client(
        base_url=HUB_URL, transport=httpx.MockTransport(hub.handle), headers={API_KEY_HEADER: API_KEY},
    ))
    overrides = {
        get_hub_client: lambda: hub_client,
        get_home_owner_email: lambda: owner.email,
        get_hub_api_key: lambda: API_KEY,
        get_schedule_price_service: lambda: prices,
    }
    app.dependency_overrides.update(overrides)
    yield SimpleNamespace(owner=owner, other=other, hub=hub, prices=prices, simulation_id=simulation_id, db=db)
    for dependency in overrides:
        app.dependency_overrides.pop(dependency, None)
    hub_client.close()


def _send(events: list[dict], key: str | None = API_KEY):
    headers = {API_KEY_HEADER: key} if key is not None else {}
    return client.post("/api/v1/home/events", json={"events": events}, headers=headers)


def _state(user):
    return client.get("/api/v1/home/state", headers=_headers(user))


def _stored(db, simulation_id: str) -> list[HomeEvent]:
    db.expire_all()
    return db.execute(
        select(HomeEvent).where(HomeEvent.simulation_id == simulation_id).order_by(HomeEvent.id)
    ).scalars().all()


# Webhook: uwierzytelnienie


@pytest.mark.parametrize("key", [None, "", "zly-klucz"])
def test_webhook_rejects_missing_or_wrong_key(home, key):
    response = _send([_report(home.simulation_id, "dev_lt_01", "2026-10-19T11:45:00+02:00", 0.015)], key=key)

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_api_key"
    assert _stored(home.db, home.simulation_id) == []


def test_webhook_rejects_everyone_without_configured_key(home):
    app.dependency_overrides[get_hub_api_key] = lambda: None

    response = _send([], key="")

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_api_key"


def test_webhook_does_not_need_user_token(home):
    response = _send([_report(home.simulation_id, "dev_lt_01", "2026-10-19T11:45:00+02:00", 0.015)])

    assert response.status_code == 202
    assert response.json() == {"accepted": 1, "duplicates": 0}


# Webhook: zapis i idempotencja


def test_events_are_stored_with_owner_and_energy(home):
    started = _event("device_started", "dev_wm_01", "2026-10-19T11:30:00+02:00",
                     {"program_id": "cotton_60", "command_id": "cmd_1"}, simulation_id=home.simulation_id)
    report = _report(home.simulation_id, "dev_wm_01", "2026-10-19T11:30:00+02:00", 0.45)

    _send([started, report])

    stored_started, stored_report = _stored(home.db, home.simulation_id)
    assert stored_started.user_id == home.owner.id
    assert stored_started.data == {"program_id": "cotton_60", "command_id": "cmd_1"}
    assert stored_started.energy_kwh is None
    assert stored_report.energy_kwh == pytest.approx(0.45)
    assert stored_report.interval_start == _at("2026-10-19T11:30:00+02:00")
    assert stored_report.sim_time == _at("2026-10-19T11:45:00+02:00")


def test_same_batch_sent_twice_does_not_double_energy(home):
    batch = [
        _report(home.simulation_id, "dev_lt_01", "2026-10-19T11:30:00+02:00", 0.015),
        _report(home.simulation_id, "dev_lt_01", "2026-10-19T11:45:00+02:00", 0.015),
    ]

    first = _send(batch)
    second = _send(batch)

    assert first.json() == {"accepted": 2, "duplicates": 0}
    assert second.status_code == 202
    assert second.json() == {"accepted": 0, "duplicates": 2}
    assert len(_stored(home.db, home.simulation_id)) == 2
    assert _state(home.owner).json()["today"]["consumption_kwh"] == pytest.approx(0.03)


def test_retried_batch_with_new_events_stores_only_new_ones(home):
    old = _report(home.simulation_id, "dev_lt_01", "2026-10-19T11:30:00+02:00", 0.015)
    new = _report(home.simulation_id, "dev_lt_01", "2026-10-19T11:45:00+02:00", 0.015)
    _send([old])

    assert _send([old, new]).json() == {"accepted": 1, "duplicates": 1}


def test_repeated_event_id_in_one_batch_is_stored_once(home):
    report = _report(home.simulation_id, "dev_lt_01", "2026-10-19T11:30:00+02:00", 0.015)

    assert _send([report, report]).json() == {"accepted": 1, "duplicates": 1}


@pytest.mark.parametrize("data", [
    {"interval_start": "2026-10-19T11:30:00+02:00"},
    {"energy_kwh": 0.1},
    {"interval_start": "2026-10-19T11:30:00", "energy_kwh": 0.1},
    {"interval_start": "2026-10-19T11:45:00+02:00", "energy_kwh": 0.1},
    {"interval_start": "2026-10-19T11:30:00+02:00", "energy_kwh": "dużo"},
])
def test_invalid_energy_report_rejects_whole_batch(home, data):
    valid = _report(home.simulation_id, "dev_lt_01", "2026-10-19T11:15:00+02:00", 0.015)
    invalid = _event("energy_report", "dev_lt_01", "2026-10-19T11:45:00+02:00", data, simulation_id=home.simulation_id)

    response = _send([valid, invalid])

    assert response.status_code == 422
    assert _stored(home.db, home.simulation_id) == []


def test_event_time_without_timezone_is_rejected(home):
    event = _event("device_error", "dev_lt_01", "2026-10-19T11:45:00", {"code": "x"}, simulation_id=home.simulation_id)

    assert _send([event]).status_code == 422


def test_unknown_event_type_is_stored(home):
    event = _event("device_paused", "dev_ev_01", "2026-10-19T11:45:00+02:00", {"reason": "x"},
                   simulation_id=home.simulation_id)

    assert _send([event]).json()["accepted"] == 1
    stored, = _stored(home.db, home.simulation_id)
    assert stored.type == "device_paused"


def test_events_of_disconnected_home_have_no_owner(home):
    home.db.execute(update(HomeConnection).values(user_id=None))
    home.db.commit()

    _send([_report(home.simulation_id, "dev_lt_01", "2026-10-19T11:30:00+02:00", 0.015)])

    stored, = _stored(home.db, home.simulation_id)
    assert stored.user_id is None


def test_too_large_batch_is_rejected(home):
    events = [_report(home.simulation_id, "dev_lt_01", "2026-10-19T11:30:00+02:00", 0.015) for _ in range(1001)]

    assert _send(events).status_code == 422


# Stan domu: dostęp


def test_state_is_only_for_owner(home):
    assert _state(home.other).status_code == 403
    assert _state(home.owner).status_code == 200


def test_state_of_disconnected_home_is_conflict(home):
    home.db.execute(update(HomeConnection).values(user_id=None))
    home.db.commit()

    response = _state(home.owner)

    assert response.status_code == 409
    assert response.json()["detail"] == NOT_CONNECTED_MESSAGE


def test_state_is_unavailable_without_hub(home):
    app.dependency_overrides[get_hub_client] = lambda: None

    assert _state(home.owner).status_code == 503


# Stan domu: zegar, urządzenia, moc


def test_state_has_clock_devices_and_home_power(home):
    home.hub.devices = [
        _device("dev_wm_01", power_kw=1.8, program_id="cotton_60", name="Pralka"),
        _device("dev_pv_01", power_kw=-3.0),
        _device("dev_lt_01", state="off", power_kw=0.0),
        _device("dev_dw_01", state="unreachable", power_kw=None),
    ]

    body = _state(home.owner).json()

    assert body["hub_available"] is True
    assert body["simulation_id"] == home.simulation_id
    assert body["clock"] == {"sim_time": "2026-10-19T12:00:00+02:00", "running": True, "speed": 288.0}
    assert body["power"] == {"consumption_kw": 1.8, "production_kw": 3.0, "net_kw": -1.2}
    washer = body["devices"][0]
    assert (washer["device_name"], washer["state"], washer["program_id"]) == ("Pralka", "running", "cotton_60")
    assert [device["state"] for device in body["devices"]] == ["running", "running", "off", "unreachable"]


# Stan domu: zużycie i koszt doby


def test_today_sums_energy_reports_of_current_day_and_simulation(home):
    home.hub.devices = [_device("dev_wm_01"), _device("dev_lt_01")]
    other_run = f"{SIMULATION_PREFIX}{uuid.uuid4().hex}"
    _send([
        _report(home.simulation_id, "dev_wm_01", "2026-10-19T10:00:00+02:00", 0.45),
        _report(home.simulation_id, "dev_wm_01", "2026-10-19T10:15:00+02:00", 0.45),
        _report(home.simulation_id, "dev_lt_01", "2026-10-19T11:45:00+02:00", 0.015),
        # Poprzednia doba i inny przebieg tej samej doby (np. po cofnięciu zegara) się nie liczą.
        _report(home.simulation_id, "dev_lt_01", "2026-10-18T23:30:00+02:00", 0.015),
        _report(other_run, "dev_wm_01", "2026-10-19T10:00:00+02:00", 5.0),
    ])

    today = _state(home.owner).json()["today"]

    assert today["day_start"] == "2026-10-19T00:00:00+02:00"
    assert today["until"] == "2026-10-19T12:00:00+02:00"
    assert today["consumption_kwh"] == pytest.approx(0.915)
    assert today["production_kwh"] == 0.0
    assert today["cost_pln"] == pytest.approx(0.915 * FlatPrices.PRICE)
    devices = {device["device_id"]: device["energy_today_kwh"] for device in _state(home.owner).json()["devices"]}
    assert devices == {"dev_wm_01": pytest.approx(0.9), "dev_lt_01": pytest.approx(0.015)}


def test_device_energy_today_equals_sum_of_its_reports(home):
    home.hub.devices = [_device("dev_wm_01")]
    profile = [0.45, 0.45, 0.3, 0.1, 0.1, 0.15, 0.2, 0.2]
    start = _at("2026-10-19T09:00:00+02:00")
    _send([
        _report(home.simulation_id, "dev_wm_01", (start + timedelta(minutes=15 * index)).isoformat(), kwh)
        for index, kwh in enumerate(profile)
    ] + [_event("device_finished", "dev_wm_01", "2026-10-19T11:00:00+02:00",
                {"program_id": "cotton_60", "energy_kwh": 1.95, "interrupted": False},
                simulation_id=home.simulation_id)])

    device, = _state(home.owner).json()["devices"]

    assert device["energy_today_kwh"] == pytest.approx(sum(profile)) == pytest.approx(1.95)


def test_pv_production_covers_consumption_in_same_quarter(home):
    _send([
        _report(home.simulation_id, "dev_hp_01", "2026-10-19T11:00:00+02:00", 0.75),
        _report(home.simulation_id, "dev_pv_01", "2026-10-19T11:00:00+02:00", -0.5),
        _report(home.simulation_id, "dev_pv_01", "2026-10-19T11:15:00+02:00", -0.5),
    ])

    today = _state(home.owner).json()["today"]

    assert (today["consumption_kwh"], today["production_kwh"]) == (pytest.approx(0.75), pytest.approx(1.0))
    assert today["net_kwh"] == pytest.approx(-0.25)
    assert today["grid_import_kwh"] == pytest.approx(0.25)
    assert today["cost_pln"] == pytest.approx(0.25 * FlatPrices.PRICE)


def test_cost_uses_prices_of_user_tariff_for_import_quarters(home):
    _send([_report(home.simulation_id, "dev_hp_01", "2026-10-19T11:00:00+02:00", 0.75)])

    _state(home.owner)

    user_id, start, end = home.prices.calls[-1]
    assert user_id == home.owner.id
    assert (start, end) == (_at("2026-10-19T11:00:00+02:00"), _at("2026-10-19T11:15:00+02:00"))


def test_cost_error_does_not_hide_energy(home):
    home.prices.error = HTTPException(status_code=409, detail="Uzupełnij profil")
    _send([_report(home.simulation_id, "dev_hp_01", "2026-10-19T11:00:00+02:00", 0.75)])

    today = _state(home.owner).json()["today"]

    assert today["consumption_kwh"] == pytest.approx(0.75)
    assert (today["cost_pln"], today["cost_error"]) == (None, "Uzupełnij profil")


def test_incomplete_tariff_data_gives_cost_error_not_server_error(home):
    home.prices.error = ValueError("Taryfa G12w nie ma godzin stref dla dnia 2026-10-19.")
    _send([_report(home.simulation_id, "dev_hp_01", "2026-10-19T11:00:00+02:00", 0.75)])

    response = _state(home.owner)

    assert response.status_code == 200
    today = response.json()["today"]
    assert today["consumption_kwh"] == pytest.approx(0.75)
    assert (today["cost_pln"], today["cost_error"]) == (None, "Taryfa G12w nie ma godzin stref dla dnia 2026-10-19.")


def test_day_without_energy_costs_nothing_and_skips_prices(home):
    today = _state(home.owner).json()["today"]

    assert (today["consumption_kwh"], today["cost_pln"], today["cost_error"]) == (0.0, 0.0, None)
    assert home.prices.calls == []


def test_unavailable_hub_shows_last_known_day(home):
    _send([
        _report(home.simulation_id, "dev_lt_01", "2026-10-19T11:30:00+02:00", 0.015),
        _report(home.simulation_id, "dev_lt_01", "2026-10-19T11:45:00+02:00", 0.015),
    ])
    home.hub.down = True

    body = _state(home.owner).json()

    assert body["hub_available"] is False
    assert (body["clock"], body["power"], body["devices"]) == (None, None, [])
    assert body["simulation_id"] == home.simulation_id
    assert body["today"]["until"] == "2026-10-19T12:00:00+02:00"
    assert body["today"]["consumption_kwh"] == pytest.approx(0.03)


def test_unavailable_hub_without_events_has_no_day(home):
    home.hub.down = True

    body = _state(home.owner).json()

    assert (body["hub_available"], body["today"]) == (False, None)


def test_events_of_other_owner_are_not_shown(home):
    _send([_report(home.simulation_id, "dev_lt_01", "2026-10-19T11:30:00+02:00", 0.015)])
    home.db.execute(update(HomeConnection).values(user_id=home.other.id))
    home.db.commit()
    app.dependency_overrides[get_home_owner_email] = lambda: home.other.email

    assert _state(home.other).json()["today"]["consumption_kwh"] == 0.0


# Rozkład energii na kwadranse


def _step(start: str, minutes: int, kwh: float, device_id: str = "dev") -> EnergyStep:
    return EnergyStep(device_id, _at(start), _at(start) + timedelta(minutes=minutes), kwh)


def test_longer_step_is_split_evenly_into_quarters():
    energy = day_energy(
        [_step("2026-10-19T10:00:00+02:00", 30, 0.6)],
        _at("2026-10-19T00:00:00+02:00"), _at("2026-10-19T12:00:00+02:00"),
    )

    assert dict(energy.by_slot) == {
        _at("2026-10-19T10:00:00+02:00"): pytest.approx(0.3),
        _at("2026-10-19T10:15:00+02:00"): pytest.approx(0.3),
    }


def test_step_crossing_midnight_counts_only_part_in_day():
    energy = day_energy(
        [_step("2026-10-18T23:45:00+02:00", 30, 0.6)],
        _at("2026-10-19T00:00:00+02:00"), _at("2026-10-19T12:00:00+02:00"),
    )

    assert energy.consumption_kwh == pytest.approx(0.3)
    assert list(energy.by_slot) == [_at("2026-10-19T00:00:00+02:00")]


def test_day_with_extra_hour_keeps_both_repeated_hours():
    start, end = _at("2026-10-25T00:00:00+02:00"), _at("2026-10-26T00:00:00+01:00")
    steps = [_step("2026-10-25T02:00:00+02:00", 15, 0.1), _step("2026-10-25T02:00:00+01:00", 15, 0.1)]

    energy = day_energy(steps, start, end)

    assert len(energy.by_slot) == 2
    assert energy.consumption_kwh == pytest.approx(0.2)
