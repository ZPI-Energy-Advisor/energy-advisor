"""ZP-93: dom właściciela – podłączenie, odłączenie i wysyłka rejestru urządzeń do huba."""
import json
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import update

from app.api.v1.deps import get_calculation_service, get_home_owner_email, get_hub_client
from app.clients.hub_client import API_KEY_HEADER, HubClient
from app.database import SessionLocal
from app.models.HomeConnection import HomeConnection
from app.models.User import User
from app.repositories.home_repository import HomeRepository
from app.services.calculation_service import CalculationService
from app.services.home_service import UNAVAILABLE_MESSAGE, HomeService, registry_hash
from main import app
from test_energy_files import _create_user, _delete, _flat_tariff_repository, _headers, client


HUB_URL = "http://hub.test"
API_KEY = "test-hub-key"
PERIOD = {"start": "2026-10-05T00:00:00+02:00", "end": "2026-10-06T00:00:00+02:00"}

WASHER = {
    "device": {
        "device_id": "dev_wm_01",
        "device_name": "Pralka Bosch",
        "device_type": "washing_machine",
        "device_category": "AGD",
        "flexibility": {"mode": "shiftable", "allowed_window": {"from": "07:00", "to": "22:00"}},
        "programs": [
            {"program_id": "quick_30", "program_name": "Szybkie 30°C", "duration_min": 30, "profile_kwh": [0.5, 0.4]},
            {"program_id": "cotton_60", "program_name": "Bawełna 60°C", "duration_min": 45, "profile_kwh": [0.6, 0.5, 0.3]},
        ],
    },
    "actions": [{
        "action_id": "act_wm_1", "device_id": "dev_wm_01", "program_id": "quick_30",
        "action_start": "2026-10-05T10:00:00+02:00", "action_end": "2026-10-05T10:30:00+02:00", "energy_kwh": 0.9,
    }],
}
LAMP = {
    "device": {
        "device_id": "dev_lamp_01",
        "device_name": "Lampa",
        "device_type": "other",
        "device_category": "Inne",
        "max_power_kw": 0.1,
        "flexibility": {"mode": "fixed"},
    },
    "actions": [{
        "action_id": "act_lamp_1", "device_id": "dev_lamp_01",
        "action_start": "2026-10-05T18:00:00+02:00", "action_end": "2026-10-05T19:00:00+02:00", "energy_kwh": 0.08,
    }],
}
HEAT_PUMP = {
    "device": {
        "device_id": "dev_hp_01",
        "device_name": "Pompa ciepła",
        "device_type": "heat_pump",
        "device_category": "Ogrzewanie",
        "max_power_kw": 3.0,
        "flexibility": {"mode": "shiftable", "max_shift_min": 60},
    },
    "actions": [{
        "action_id": "act_hp_1", "device_id": "dev_hp_01",
        "action_start": "2026-10-05T12:00:00+02:00", "action_end": "2026-10-05T13:00:00+02:00", "energy_kwh": 1.5,
    }],
}


def _devices_file(*entries) -> bytes:
    return json.dumps({
        "period": PERIOD,
        "devices": [entry["device"] for entry in entries],
        "energy_usage": [action for entry in entries for action in entry["actions"]],
    }).encode()


class FakeHub:
    """Hub z kontraktu: PUT /home/devices zapisuje rejestr; `mode` symuluje awarie."""

    def __init__(self):
        self.registries: list[list[dict]] = []
        self.mode = "ok"

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get(API_KEY_HEADER) != API_KEY:
            return httpx.Response(401, json={"detail": "Błędny klucz", "code": "invalid_api_key"})
        assert (request.method, request.url.path) == ("PUT", "/home/devices")
        if self.mode == "down":
            raise httpx.ConnectError("Connection refused", request=request)
        if self.mode == "reject":
            return httpx.Response(409, json={"detail": "Brak wolnych portów", "code": "port_pool_exhausted"})
        devices = json.loads(request.content)["devices"]
        self.registries.append(devices)
        return httpx.Response(200, json={
            "devices": [{"device_id": device["device_id"], "port": 9101 + index, "state": "off"}
                        for index, device in enumerate(devices)],
        })

    @property
    def last_ids(self) -> list[str]:
        return [device["device_id"] for device in self.registries[-1]]


def _reset_home(session) -> None:
    session.execute(update(HomeConnection).values(
        user_id=None, connected_at=None, registry_hash=None, synced_at=None, sync_error=None,
    ))
    session.commit()


@pytest.fixture
def db():
    session = SessionLocal()
    session.created_users = []
    yield session
    session.rollback()
    for user_id in session.created_users:
        session.query(User).filter(User.id == user_id).delete()
    session.commit()
    session.close()


@pytest.fixture
def home(db):
    """Właściciel domu, drugi użytkownik i hub podmieniony na FakeHub; wiersz domu wyzerowany."""
    owner, other = _create_user(db), _create_user(db)
    hub = FakeHub()
    hub_client = HubClient(httpx.Client(
        base_url=HUB_URL, transport=httpx.MockTransport(hub.handle), headers={API_KEY_HEADER: API_KEY},
    ))
    _reset_home(db)
    app.dependency_overrides[get_hub_client] = lambda: hub_client
    app.dependency_overrides[get_home_owner_email] = lambda: owner.email
    app.dependency_overrides[get_calculation_service] = lambda: CalculationService(_flat_tariff_repository())
    yield SimpleNamespace(owner=owner, other=other, hub=hub)
    for dependency in (get_hub_client, get_home_owner_email, get_calculation_service):
        app.dependency_overrides.pop(dependency, None)
    _reset_home(db)
    hub_client.close()


def _upload(user, content: bytes, name="urzadzenia.json"):
    return client.post(
        "/api/v1/upload", files={"file": (name, BytesIO(content), "application/json")}, headers=_headers(user),
    )


def _connect(user):
    return client.post("/api/v1/home/connect", headers=_headers(user))


def _disconnect(user):
    return client.delete("/api/v1/home", headers=_headers(user))


def _status(user):
    return client.get("/api/v1/home", headers=_headers(user))


def _me(user):
    return client.get("/api/v1/users/me", headers=_headers(user)).json()


# Kto widzi dom


def test_only_owner_has_home_access(home):
    assert _me(home.owner)["home_owner"] is True
    assert _me(home.other)["home_owner"] is False

    for request in (_status, _connect, _disconnect):
        assert request(home.other).status_code == 403
        assert request(home.owner).status_code == 200


def test_other_user_cannot_connect_or_disconnect_owner_home(home):
    _upload(home.owner, _devices_file(WASHER))
    _connect(home.owner)

    assert _connect(home.other).status_code == 403
    assert _disconnect(home.other).status_code == 403
    assert _status(home.owner).json()["connected"] is True
    assert len(home.hub.registries) == 1


def test_home_endpoints_are_unavailable_without_hub(home):
    app.dependency_overrides[get_hub_client] = lambda: None

    assert _me(home.owner)["home_owner"] is False
    assert _status(home.owner).status_code == 503
    assert _connect(home.other).status_code == 503
    assert _upload(home.owner, _devices_file(WASHER)).json()["home_sync"] is None


def test_owner_email_is_matched_case_insensitively():
    service = HomeService(repository=None, hub_client=object(), owner_email="owner@example.com")

    assert service.is_owner(User(email="Owner@Example.com "))
    assert not service.is_owner(User(email="other@example.com"))
    assert not HomeService(None, hub_client=object(), owner_email=None).is_owner(User(email="owner@example.com"))


# Podłączenie i odłączenie


def test_connect_sends_owner_devices_in_hub_registry_shape(home):
    _upload(home.owner, _devices_file(WASHER, LAMP, HEAT_PUMP))
    _upload(home.other, _devices_file(LAMP))

    response = _connect(home.owner)

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True and body["connected_at"] is not None
    assert body["devices_count"] == 3
    assert body["sync"]["status"] == "synced" and body["sync"]["error"] is None
    heat_pump, lamp, washer = home.hub.registries[-1]
    quick, cotton = WASHER["device"]["programs"]
    assert washer == {
        **WASHER["device"],
        "max_power_kw": None,
        "flexibility": {"mode": "shiftable", "allowed_window": {"from": "07:00", "to": "22:00"}, "max_shift_min": None},
        "programs": [cotton, quick],
    }
    assert lamp["max_power_kw"] == 0.1 and lamp["programs"] == []
    assert lamp["flexibility"] == {"mode": "fixed", "allowed_window": None, "max_shift_min": None}
    assert heat_pump["flexibility"] == {"mode": "shiftable", "allowed_window": None, "max_shift_min": 60}


def test_connect_again_resends_unchanged_registry(home):
    _upload(home.owner, _devices_file(WASHER))
    _connect(home.owner)

    _connect(home.owner)

    assert len(home.hub.registries) == 2
    assert home.hub.registries[0] == home.hub.registries[1]


def test_disconnect_sends_empty_registry(home):
    _upload(home.owner, _devices_file(WASHER))
    _connect(home.owner)

    response = _disconnect(home.owner)

    body = response.json()
    assert body["connected"] is False and body["devices_count"] == 0
    assert body["sync"]["status"] == "synced"
    assert home.hub.registries[-1] == []


def test_owner_upload_before_connecting_does_not_touch_hub(home):
    response = _upload(home.owner, _devices_file(WASHER))

    assert response.status_code == 200
    assert response.json()["home_sync"] is None
    assert home.hub.registries == []
    assert _status(home.owner).json()["sync"]["status"] == "synced"


# Upload i usunięcie pliku


def test_owner_upload_resends_registry_and_other_upload_does_not(home):
    _upload(home.owner, _devices_file(WASHER))
    _connect(home.owner)

    owner_upload = _upload(home.owner, _devices_file(LAMP))
    other_upload = _upload(home.other, _devices_file(HEAT_PUMP))

    assert owner_upload.json()["home_sync"]["status"] == "synced"
    assert other_upload.status_code == 200 and other_upload.json()["home_sync"] is None
    assert len(home.hub.registries) == 2
    assert home.hub.last_ids == ["dev_lamp_01", "dev_wm_01"]


def test_upload_without_registry_change_skips_hub(home):
    _upload(home.owner, _devices_file(WASHER))
    _connect(home.owner)

    response = _upload(home.owner, _devices_file(WASHER), name="ten-sam-dom.json")

    assert response.json()["home_sync"]["status"] == "synced"
    assert len(home.hub.registries) == 1


def test_upload_after_disconnect_does_not_touch_hub(home):
    _upload(home.owner, _devices_file(WASHER))
    _connect(home.owner)
    _disconnect(home.owner)

    response = _upload(home.owner, _devices_file(LAMP))

    assert response.json()["home_sync"] is None
    assert home.hub.registries[-1] == [] and len(home.hub.registries) == 2


def test_deleting_owner_file_removes_its_devices_from_hub(home):
    _upload(home.owner, _devices_file(WASHER))
    lamp_file = _upload(home.owner, _devices_file(LAMP)).json()["file_id"]
    _connect(home.owner)

    assert _delete(home.owner, lamp_file).status_code == 204

    assert home.hub.last_ids == ["dev_wm_01"]
    assert _status(home.owner).json()["devices_count"] == 1


def test_deleting_other_user_file_does_not_touch_hub(home):
    _upload(home.owner, _devices_file(WASHER))
    _connect(home.owner)
    other_file = _upload(home.other, _devices_file(LAMP)).json()["file_id"]

    _delete(home.other, other_file)

    assert len(home.hub.registries) == 1


# Niedostępny hub


def test_unavailable_hub_does_not_block_import_and_next_operation_retries(home):
    _upload(home.owner, _devices_file(WASHER))
    _connect(home.owner)
    home.hub.mode = "down"

    response = _upload(home.owner, _devices_file(LAMP))

    assert response.status_code == 200
    pending = response.json()["home_sync"]
    assert pending["status"] == "pending" and pending["error"] == UNAVAILABLE_MESSAGE
    assert _status(home.owner).json()["sync"]["status"] == "pending"
    assert _me(home.owner)["home_owner"] is True

    home.hub.mode = "ok"
    retried = _upload(home.owner, _devices_file(WASHER), name="kolejny.json")

    assert retried.json()["home_sync"]["status"] == "synced"
    assert home.hub.last_ids == ["dev_lamp_01", "dev_wm_01"]
    sync = _status(home.owner).json()["sync"]
    assert sync["status"] == "synced" and sync["error"] is None


def test_connect_with_unavailable_hub_keeps_connection_pending(home):
    _upload(home.owner, _devices_file(WASHER))
    home.hub.mode = "down"

    body = _connect(home.owner).json()

    assert body["connected"] is True
    assert body["sync"] == {"status": "pending", "synced_at": None, "error": UNAVAILABLE_MESSAGE}
    home.hub.mode = "ok"
    assert _connect(home.owner).json()["sync"]["status"] == "synced"
    assert home.hub.last_ids == ["dev_wm_01"]


def test_disconnect_with_unavailable_hub_is_retried_by_next_upload(home):
    _upload(home.owner, _devices_file(WASHER))
    _connect(home.owner)
    home.hub.mode = "down"

    body = _disconnect(home.owner).json()

    assert body["connected"] is False and body["sync"]["status"] == "pending"
    home.hub.mode = "ok"
    _upload(home.owner, _devices_file(LAMP))
    assert home.hub.registries[-1] == []
    assert _status(home.owner).json()["sync"]["status"] == "synced"


def test_registry_rejected_by_hub_is_reported(home):
    _upload(home.owner, _devices_file(WASHER))
    home.hub.mode = "reject"

    body = _connect(home.owner).json()

    assert body["sync"]["status"] == "pending"
    assert "Brak wolnych portów" in body["sync"]["error"]


# Rejestr


def test_registry_hash_depends_only_on_registry_content(db, home):
    _upload(home.owner, _devices_file(WASHER, LAMP))
    _upload(home.owner, _devices_file(LAMP, WASHER), name="inna-kolejnosc.json")
    repository = HomeRepository(db)

    registry = repository.registry(home.owner.id)

    assert [device.device_id for device in registry] == ["dev_lamp_01", "dev_wm_01"]
    assert registry_hash(registry) == registry_hash(repository.registry(home.owner.id))
    assert registry_hash(registry) != registry_hash(registry[:1])
    assert repository.registry(home.other.id) == []
