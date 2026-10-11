import datetime
import uuid
from io import BytesIO

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.v1.deps import get_calculation_service
from app.database import SessionLocal, engine
from app.models.EnergyDataFile import EnergyDataFile
from app.models.Simulation import Simulation
from app.models.User import User
from app.services.auth_service import AuthService
from main import app


try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1 FROM energy_data_files LIMIT 1"))
except Exception as exc:  # brak bazy lub niewykonane migracje
    pytest.skip(f"Baza danych niedostępna: {exc}", allow_module_level=True)


client = TestClient(app)
auth = AuthService(repository=None)

SAMPLE_RESULTS = {
    "tariffs": {"G11": {"type": "stala", "total_usage_kwh": 1.0, "estimated_cost_pln": 1.0}},
    "chart_daily": [{"date": "2024-11-03", "kwh": 1.0}],
    "statistics": {"records_count": 3, "data_start": "2024-11-03", "data_end": "2024-11-05"},
}


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


def _create_user(db) -> User:
    user = User(email=f"test-{uuid.uuid4().hex}@example.com", provider="local")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.created_users.append(user.id)
    return user


def _create_file(db, user, *, name="dane.csv", uploaded_at=None, status=EnergyDataFile.STATUS_COMPLETED, with_simulation=True):
    energy_file = EnergyDataFile(
        user_id=user.id,
        file_name=name,
        uploaded_at=uploaded_at or datetime.datetime.utcnow(),
        data_start=datetime.date(2024, 11, 3),
        data_end=datetime.date(2024, 11, 5),
        records_count=3,
        status=status,
    )
    db.add(energy_file)
    db.commit()
    if with_simulation:
        db.add(Simulation(user_id=user.id, energy_data_file_id=energy_file.id, results=SAMPLE_RESULTS))
        db.commit()
    db.refresh(energy_file)
    return energy_file


def _token(user_id, token_type="access", expires_in=datetime.timedelta(minutes=5)):
    return auth.generate_token(user_id, token_type, datetime.datetime.now(datetime.timezone.utc) + expires_in)


def _headers(user):
    return {"Authorization": f"Bearer {_token(user.id)}"}


def test_list_empty(db):
    user = _create_user(db)

    response = client.get("/api/v1/energy-files", headers=_headers(user))

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "page_size": 20, "total": 0, "total_pages": 0}


def test_list_pagination(db):
    user = _create_user(db)
    base = datetime.datetime(2026, 1, 1)
    for i in range(5):
        _create_file(db, user, name=f"plik{i}.csv", uploaded_at=base + datetime.timedelta(days=i))

    first = client.get("/api/v1/energy-files?page=1&page_size=2", headers=_headers(user)).json()
    last = client.get("/api/v1/energy-files?page=3&page_size=2", headers=_headers(user)).json()
    beyond = client.get("/api/v1/energy-files?page=4&page_size=2", headers=_headers(user)).json()

    assert first["total"] == 5
    assert first["total_pages"] == 3
    assert first["page"] == 1 and first["page_size"] == 2
    assert [item["file_name"] for item in first["items"]] == ["plik4.csv", "plik3.csv"]
    assert [item["file_name"] for item in last["items"]] == ["plik0.csv"]
    assert beyond["items"] == [] and beyond["total"] == 5


def test_list_item_metadata(db):
    user = _create_user(db)
    energy_file = _create_file(db, user)

    item = client.get("/api/v1/energy-files", headers=_headers(user)).json()["items"][0]

    assert item["id"] == str(energy_file.id)
    assert item["file_name"] == "dane.csv"
    assert item["data_start"] == "2024-11-03"
    assert item["data_end"] == "2024-11-05"
    assert item["records_count"] == 3
    assert item["status"] == "completed"
    assert item["days_count"] == 3
    assert item["label"] == "dane.csv (03.11.2024 – 05.11.2024)"


def test_list_shows_only_own_files(db):
    owner = _create_user(db)
    other = _create_user(db)
    _create_file(db, owner)

    response = client.get("/api/v1/energy-files", headers=_headers(other))

    assert response.json()["total"] == 0


@pytest.mark.parametrize("params", ["page=0", "page_size=0", "page_size=101"])
def test_list_invalid_pagination(db, params):
    user = _create_user(db)

    response = client.get(f"/api/v1/energy-files?{params}", headers=_headers(user))

    assert response.status_code == 422


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer nie-jwt",
        f"Bearer {_token(uuid.uuid4())}",
        f"Bearer {_token(uuid.uuid4(), token_type='refresh')}",
        f"Bearer {_token(uuid.uuid4(), expires_in=datetime.timedelta(minutes=-1))}",
    ],
    ids=["brak-tokenu", "zly-token", "nieznany-uzytkownik", "token-refresh", "wygasly-token"],
)
def test_requires_valid_access_token(authorization):
    headers = {"Authorization": authorization} if authorization else {}

    assert client.get("/api/v1/energy-files", headers=headers).status_code == 401
    assert client.get(f"/api/v1/energy-files/{uuid.uuid4()}/data", headers=headers).status_code == 401


def test_get_file_data(db):
    user = _create_user(db)
    energy_file = _create_file(db, user)

    response = client.get(f"/api/v1/energy-files/{energy_file.id}/data", headers=_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["file"]["id"] == str(energy_file.id)
    assert body["results"] == SAMPLE_RESULTS


def test_get_data_of_nonexistent_file(db):
    user = _create_user(db)

    response = client.get(f"/api/v1/energy-files/{uuid.uuid4()}/data", headers=_headers(user))

    assert response.status_code == 404


def test_get_data_of_other_users_file(db):
    owner = _create_user(db)
    intruder = _create_user(db)
    energy_file = _create_file(db, owner)

    response = client.get(f"/api/v1/energy-files/{energy_file.id}/data", headers=_headers(intruder))

    assert response.status_code == 404
    assert "results" not in response.json()


def test_get_data_of_failed_file(db):
    user = _create_user(db)
    energy_file = _create_file(db, user, status=EnergyDataFile.STATUS_FAILED, with_simulation=False)

    response = client.get(f"/api/v1/energy-files/{energy_file.id}/data", headers=_headers(user))

    assert response.status_code == 409


class _StubCalculationService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def calculate_all_tariffs(self, file_obj):
        if self.error:
            raise self.error
        return self.result


def _upload(user, calculation_service):
    app.dependency_overrides[get_calculation_service] = lambda: calculation_service
    try:
        return client.post(
            "/api/v1/upload",
            files={"file": ("zuzycie.csv", BytesIO(b"x"), "text/csv")},
            headers=_headers(user),
        )
    finally:
        app.dependency_overrides.pop(get_calculation_service, None)


def test_upload_links_simulation_with_file(db):
    user = _create_user(db)

    response = _upload(user, _StubCalculationService(result=SAMPLE_RESULTS))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["file_name"] == "zuzycie.csv"

    energy_file = db.get(EnergyDataFile, uuid.UUID(body["file_id"]))
    assert energy_file.user_id == user.id
    assert energy_file.status == "completed"
    assert energy_file.data_start == datetime.date(2024, 11, 3)
    assert energy_file.data_end == datetime.date(2024, 11, 5)
    assert energy_file.records_count == 3

    simulation = db.get(Simulation, uuid.UUID(body["simulation_id"]))
    assert simulation.energy_data_file_id == energy_file.id

    latest = client.get("/api/v1/results", headers=_headers(user)).json()
    assert latest["simulation_id"] == body["simulation_id"]


def test_upload_failure_marks_file_as_failed(db):
    user = _create_user(db)

    response = _upload(user, _StubCalculationService(error=HTTPException(status_code=422, detail="Nierozpoznany format")))

    assert response.status_code == 422
    files = client.get("/api/v1/energy-files", headers=_headers(user)).json()["items"]
    assert len(files) == 1
    assert files[0]["status"] == "failed"
    assert files[0]["error_message"] == "Nierozpoznany format"
