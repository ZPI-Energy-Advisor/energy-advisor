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
from app.services.calculation_service import CalculationService
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
    assert response.json() == {"items": [], "page": 1, "page_size": 20, "total": 0, "total_pages": 0, "aggregate": None}


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


def _results_with_series():
    # 03.11 - 0,25 kWh w każdym slocie, 04.11 - brak pomiarów, 05.11 - 0,5 kWh w każdym slocie.
    usage = {"2024-11-03": [0.25] * 96, "2024-11-05": [0.5] * 96}
    slot_prices = {"G11": {"type": "stala", "prices": [1.0] * 96}}
    results = CalculationService.summarize_usage(usage, slot_prices)
    return {**results, "usage_15min": usage, "slot_prices": slot_prices}


def _create_file_with_series(db, user):
    energy_file = _create_file(db, user, with_simulation=False)
    db.add(Simulation(user_id=user.id, energy_data_file_id=energy_file.id, results=_results_with_series()))
    db.commit()
    return energy_file


def _get_data(user, energy_file, query=""):
    return client.get(f"/api/v1/energy-files/{energy_file.id}/data{query}", headers=_headers(user))


def test_get_file_data_without_range_returns_whole_period(db):
    user = _create_user(db)
    energy_file = _create_file_with_series(db, user)

    body = _get_data(user, energy_file).json()

    assert body["date_from"] == "2024-11-03"
    assert body["date_to"] == "2024-11-05"
    assert "usage_15min" not in body["results"] and "slot_prices" not in body["results"]
    assert body["results"]["tariffs"]["G11"]["total_usage_kwh"] == 72.0


def test_get_file_data_for_range(db):
    user = _create_user(db)
    energy_file = _create_file_with_series(db, user)

    response = _get_data(user, energy_file, "?from=2024-11-04&to=2024-11-05")

    assert response.status_code == 200
    body = response.json()
    assert body["date_from"] == "2024-11-04"
    assert body["date_to"] == "2024-11-05"
    assert [row["date"] for row in body["results"]["chart_daily"]] == ["2024-11-05"]
    assert body["results"]["tariffs"]["G11"]["total_usage_kwh"] == 48.0
    assert "usage_15min" not in body["results"]


def test_get_file_data_for_range_with_one_bound(db):
    user = _create_user(db)
    energy_file = _create_file_with_series(db, user)

    body = _get_data(user, energy_file, "?to=2024-11-03").json()

    assert body["date_from"] == "2024-11-03"
    assert body["date_to"] == "2024-11-03"
    assert body["results"]["tariffs"]["G11"]["total_usage_kwh"] == 24.0


def test_get_file_data_for_range_without_measurements(db):
    user = _create_user(db)
    energy_file = _create_file_with_series(db, user)

    response = _get_data(user, energy_file, "?from=2024-11-04&to=2024-11-04")

    assert response.status_code == 200
    results = response.json()["results"]
    assert results["chart_daily"] == []
    assert results["statistics"]["days_analyzed"] == 0


@pytest.mark.parametrize(
    "query, message",
    [
        ("?from=2024-11-05&to=2024-11-03", "Data początkowa nie może być późniejsza"),
        ("?from=2024-11-01&to=2024-11-04", "Zakres musi mieścić się"),
        ("?from=2024-11-04&to=2024-11-30", "Zakres musi mieścić się"),
    ],
    ids=["odwrocona-kolejnosc", "przed-poczatkiem-danych", "po-koncu-danych"],
)
def test_get_file_data_rejects_invalid_range(db, query, message):
    user = _create_user(db)
    energy_file = _create_file_with_series(db, user)

    response = _get_data(user, energy_file, query)

    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_get_file_data_rejects_malformed_date(db):
    user = _create_user(db)
    energy_file = _create_file_with_series(db, user)

    assert _get_data(user, energy_file, "?from=03.11.2024").status_code == 422


def test_range_on_file_without_usage_series(db):
    user = _create_user(db)
    energy_file = _create_file(db, user)

    response = _get_data(user, energy_file, "?from=2024-11-03&to=2024-11-04")

    assert response.status_code == 409
    assert "Wgraj go ponownie" in response.json()["detail"]


SLOT_PRICES = {"G11": {"type": "stala", "prices": [1.0] * 96}}


def _days(start, count, kwh_per_slot):
    first = datetime.date.fromisoformat(start)
    return {(first + datetime.timedelta(days=i)).isoformat(): [kwh_per_slot] * 96 for i in range(count)}


def _series_results(usage):
    return {**CalculationService.summarize_usage(usage, SLOT_PRICES), "usage_15min": usage, "slot_prices": SLOT_PRICES}


def _create_series_file(db, user, usage, *, name, uploaded_at):
    """Plik z prawdziwą serią 15-minutową; zakres dat wynika z danych."""
    results = _series_results(usage)
    energy_file = EnergyDataFile(
        user_id=user.id,
        file_name=name,
        uploaded_at=uploaded_at,
        data_start=datetime.date.fromisoformat(min(usage)),
        data_end=datetime.date.fromisoformat(max(usage)),
        records_count=results["statistics"]["records_count"],
        status=EnergyDataFile.STATUS_COMPLETED,
    )
    db.add(energy_file)
    db.commit()
    db.add(Simulation(user_id=user.id, energy_data_file_id=energy_file.id, results=results))
    db.commit()
    db.refresh(energy_file)
    return energy_file


def _all_data(user, query=""):
    return client.get(f"/api/v1/energy-files/all/data{query}", headers=_headers(user))


def _list(user):
    return client.get("/api/v1/energy-files", headers=_headers(user)).json()


def _delete(user, file_id):
    return client.delete(f"/api/v1/energy-files/{file_id}", headers=_headers(user))


def _total_kwh(user):
    return _all_data(user).json()["results"]["tariffs"]["G11"]["total_usage_kwh"]


T0 = datetime.datetime(2026, 1, 1, 12, 0)
T1 = T0 + datetime.timedelta(hours=1)
T2 = T0 + datetime.timedelta(hours=2)


def test_first_upload_makes_file_and_aggregate_available(db):
    user = _create_user(db)
    _create_series_file(db, user, _days("2024-06-01", 30, 0.25), name="czerwiec.csv", uploaded_at=T0)

    listing = _list(user)

    assert [item["file_name"] for item in listing["items"]] == ["czerwiec.csv"]
    assert listing["aggregate"] == {
        "id": "all",
        "file_name": "Wszystkie pliki",
        "data_start": "2024-06-01",
        "data_end": "2024-06-30",
        "files_count": 1,
        "days_count": 30,
        "label": "Wszystkie pliki (01.06.2024 – 30.06.2024)",
    }


def test_aggregate_summary_ignores_failed_and_other_users_files(db):
    user = _create_user(db)
    other = _create_user(db)
    _create_series_file(db, user, _days("2024-06-01", 5, 0.25), name="moj.csv", uploaded_at=T0)
    _create_series_file(db, other, _days("2023-01-01", 5, 0.25), name="cudzy.csv", uploaded_at=T0)
    _create_file(db, user, name="zly.csv", status=EnergyDataFile.STATUS_FAILED, with_simulation=False)

    listing = _list(user)

    assert listing["total"] == 2
    assert listing["aggregate"]["files_count"] == 1
    assert listing["aggregate"]["data_start"] == "2024-06-01"


def test_single_file_shows_only_its_data(db):
    user = _create_user(db)
    june = _create_series_file(db, user, _days("2024-06-01", 30, 0.25), name="czerwiec.csv", uploaded_at=T0)
    _create_series_file(db, user, _days("2024-07-01", 31, 0.5), name="lipiec.csv", uploaded_at=T1)

    body = _get_data(user, june).json()

    assert body["results"]["tariffs"]["G11"]["total_usage_kwh"] == 30 * 24
    assert {row["date"][:7] for row in body["results"]["chart_daily"]} == {"2024-06"}


def test_all_files_data_with_gap_between_files(db):
    user = _create_user(db)
    january = _create_series_file(db, user, _days("2024-01-01", 31, 0.25), name="styczen.csv", uploaded_at=T0)
    march = _create_series_file(db, user, _days("2024-03-01", 31, 0.5), name="marzec.csv", uploaded_at=T1)

    body = _all_data(user).json()

    assert body["file"]["id"] == "all"
    assert body["file"]["data_start"] == "2024-01-01" and body["file"]["data_end"] == "2024-03-31"
    assert body["file"]["files_count"] == 2
    assert body["simulation_id"] is None
    assert [f["id"] for f in body["file"]["files"]] == [str(january.id), str(march.id)]
    results = body["results"]
    assert results["tariffs"]["G11"]["total_usage_kwh"] == 31 * 24 + 31 * 48
    assert results["statistics"]["days_analyzed"] == 62
    assert not any(row["date"].startswith("2024-02") for row in results["chart_daily"])
    assert "usage_15min" not in results


def test_all_files_data_range_inside_gap_is_empty(db):
    user = _create_user(db)
    _create_series_file(db, user, _days("2024-01-01", 31, 0.25), name="styczen.csv", uploaded_at=T0)
    _create_series_file(db, user, _days("2024-03-01", 31, 0.5), name="marzec.csv", uploaded_at=T1)

    response = _all_data(user, "?from=2024-02-01&to=2024-02-29")

    assert response.status_code == 200
    assert response.json()["results"]["statistics"]["days_analyzed"] == 0
    assert response.json()["results"]["chart_daily"] == []


def test_all_files_data_overlap_newer_upload_wins(db):
    user = _create_user(db)
    older = _create_series_file(db, user, _days("2024-05-01", 61, 0.25), name="maj-czerwiec.csv", uploaded_at=T0)
    newer = _create_series_file(db, user, _days("2024-06-01", 61, 0.5), name="czerwiec-lipiec.csv", uploaded_at=T1)

    body = _all_data(user).json()

    daily = {row["date"]: row["kwh"] for row in body["results"]["chart_daily"]}
    assert daily["2024-05-31"] == 24.0  # tylko starszy plik
    assert daily["2024-06-15"] == 48.0  # czerwiec w obu plikach - wygrywa nowszy, bez sumowania
    assert daily["2024-07-31"] == 48.0  # tylko nowszy plik
    assert len(daily) == 31 + 30 + 31
    contributions = {f["id"]: f["days_used"] for f in body["file"]["files"]}
    assert contributions == {str(older.id): 31, str(newer.id): 61}
    assert body["file"]["records_count"] == len(daily) * 24


def test_all_files_data_older_upload_with_newer_data_loses_overlap(db):
    # O pierwszeństwie decyduje data uploadu, a nie to, który plik ma późniejsze daty pomiarów.
    user = _create_user(db)
    _create_series_file(db, user, _days("2024-06-01", 30, 0.5), name="wgrany-pozniej.csv", uploaded_at=T1)
    _create_series_file(db, user, _days("2024-06-15", 30, 0.25), name="wgrany-wczesniej.csv", uploaded_at=T0)

    daily = {row["date"]: row["kwh"] for row in _all_data(user).json()["results"]["chart_daily"]}

    assert daily["2024-06-20"] == 48.0
    assert daily["2024-07-10"] == 24.0


def test_all_files_data_duplicate_upload_is_not_doubled(db):
    user = _create_user(db)
    usage = _days("2024-06-01", 30, 0.25)
    _create_series_file(db, user, usage, name="czerwiec.csv", uploaded_at=T0)
    _create_series_file(db, user, usage, name="czerwiec (kopia).csv", uploaded_at=T1)

    body = _all_data(user).json()

    assert body["results"]["tariffs"]["G11"]["total_usage_kwh"] == 30 * 24
    assert body["file"]["records_count"] == 30 * 24
    assert [f["days_used"] for f in body["file"]["files"]] == [0, 30]


def test_all_files_data_for_range_and_validation(db):
    user = _create_user(db)
    _create_series_file(db, user, _days("2024-01-01", 31, 0.25), name="styczen.csv", uploaded_at=T0)
    _create_series_file(db, user, _days("2024-03-01", 31, 0.5), name="marzec.csv", uploaded_at=T1)

    ranged = _all_data(user, "?from=2024-01-31&to=2024-03-01").json()

    assert [row["date"] for row in ranged["results"]["chart_daily"]] == ["2024-01-31", "2024-03-01"]
    assert ranged["date_from"] == "2024-01-31" and ranged["date_to"] == "2024-03-01"
    assert _all_data(user, "?from=2023-12-31").status_code == 422
    assert _all_data(user, "?from=2024-03-02&to=2024-03-01").status_code == 422


def test_all_files_data_excludes_other_users_files(db):
    user = _create_user(db)
    other = _create_user(db)
    _create_series_file(db, user, _days("2024-06-01", 2, 0.25), name="moj.csv", uploaded_at=T0)
    _create_series_file(db, other, _days("2024-06-01", 2, 10.0), name="cudzy.csv", uploaded_at=T1)

    body = _all_data(user).json()

    assert body["file"]["files_count"] == 1
    assert body["results"]["tariffs"]["G11"]["total_usage_kwh"] == 48.0


def test_all_files_data_without_files(db):
    user = _create_user(db)

    response = _all_data(user)

    assert response.status_code == 409
    assert response.json()["detail"] == "Nie masz jeszcze poprawnie zaimportowanych plików."


def test_all_files_data_skips_files_without_usage_series(db):
    user = _create_user(db)
    legacy = _create_file(db, user, name="stary.csv")
    _create_series_file(db, user, _days("2024-06-01", 2, 0.25), name="nowy.csv", uploaded_at=T1)

    body = _all_data(user).json()

    assert body["file"]["files_count"] == 1
    assert [f["id"] for f in body["file"]["skipped_files"]] == [str(legacy.id)]


def test_all_files_data_only_legacy_files(db):
    user = _create_user(db)
    _create_file(db, user, name="stary.csv")

    response = _all_data(user)

    assert response.status_code == 409
    assert "Wgraj je ponownie" in response.json()["detail"]


def test_new_upload_updates_aggregate(db):
    user = _create_user(db)
    _create_series_file(db, user, _days("2024-06-01", 30, 0.25), name="czerwiec.csv", uploaded_at=T0)

    response = _upload(user, _StubCalculationService(result=_series_results(_days("2024-07-01", 31, 0.5))))

    assert response.status_code == 200
    listing = _list(user)
    assert listing["aggregate"]["files_count"] == 2
    assert listing["aggregate"]["data_end"] == "2024-07-31"
    assert _total_kwh(user) == 30 * 24 + 31 * 48


def test_delete_file_updates_aggregate(db):
    user = _create_user(db)
    june = _create_series_file(db, user, _days("2024-06-01", 30, 0.25), name="czerwiec.csv", uploaded_at=T0)
    july = _create_series_file(db, user, _days("2024-07-01", 31, 0.5), name="lipiec.csv", uploaded_at=T1)

    response = _delete(user, july.id)

    assert response.status_code == 204
    assert db.query(Simulation).filter(Simulation.energy_data_file_id == july.id).count() == 0
    listing = _list(user)
    assert [item["id"] for item in listing["items"]] == [str(june.id)]
    assert listing["aggregate"]["data_end"] == "2024-06-30"
    assert _total_kwh(user) == 30 * 24


def test_delete_newer_overlapping_file_restores_older_values(db):
    user = _create_user(db)
    _create_series_file(db, user, _days("2024-06-01", 30, 0.25), name="stary.csv", uploaded_at=T0)
    newer = _create_series_file(db, user, _days("2024-06-01", 30, 0.5), name="nowy.csv", uploaded_at=T2)
    assert _total_kwh(user) == 30 * 48

    _delete(user, newer.id)

    assert _total_kwh(user) == 30 * 24


def test_delete_last_file_removes_aggregate(db):
    user = _create_user(db)
    only = _create_series_file(db, user, _days("2024-06-01", 2, 0.25), name="jedyny.csv", uploaded_at=T0)

    _delete(user, only.id)

    assert _list(user)["aggregate"] is None
    assert _all_data(user).status_code == 409


def test_delete_other_users_or_missing_file(db):
    owner = _create_user(db)
    intruder = _create_user(db)
    energy_file = _create_series_file(db, owner, _days("2024-06-01", 2, 0.25), name="cudzy.csv", uploaded_at=T0)

    assert _delete(intruder, energy_file.id).status_code == 404
    assert _delete(owner, uuid.uuid4()).status_code == 404
    assert _list(owner)["total"] == 1


def test_aggregate_endpoints_require_token():
    assert client.get("/api/v1/energy-files/all/data").status_code == 401
    assert client.delete(f"/api/v1/energy-files/{uuid.uuid4()}").status_code == 401


def _create_file_with_resolution(db, user, usage, resolution, *, name, uploaded_at):
    results = {
        **CalculationService.summarize_usage(usage, SLOT_PRICES, resolution),
        "usage_15min": usage,
        "slot_prices": SLOT_PRICES,
    }
    energy_file = EnergyDataFile(
        user_id=user.id,
        file_name=name,
        uploaded_at=uploaded_at,
        data_start=datetime.date.fromisoformat(min(usage)),
        data_end=datetime.date.fromisoformat(max(usage)),
        records_count=results["statistics"]["records_count"],
        status=EnergyDataFile.STATUS_COMPLETED,
    )
    db.add(energy_file)
    db.commit()
    db.add(Simulation(user_id=user.id, energy_data_file_id=energy_file.id, results=results))
    db.commit()
    return energy_file


def test_all_files_counts_records_per_file_resolution(db):
    user = _create_user(db)
    _create_file_with_resolution(db, user, _days("2025-01-01", 2, 0.25), 60, name="godzinowy.csv", uploaded_at=T0)
    _create_file_with_resolution(db, user, _days("2025-01-03", 1, 0.25), 15, name="kwadransowy.csv", uploaded_at=T1)

    body = _all_data(user).json()

    assert body["file"]["records_count"] == 2 * 24 + 96
    assert body["results"]["statistics"]["resolution_minutes"] is None
    assert body["results"]["statistics"]["records_count"] is None


def test_all_files_with_one_resolution_keeps_it(db):
    user = _create_user(db)
    _create_file_with_resolution(db, user, _days("2025-01-01", 1, 0.25), 15, name="a.csv", uploaded_at=T0)
    _create_file_with_resolution(db, user, _days("2025-01-02", 1, 0.25), 15, name="b.csv", uploaded_at=T1)

    body = _all_data(user).json()

    assert body["file"]["records_count"] == 2 * 96
    assert body["results"]["statistics"]["resolution_minutes"] == 15
    assert body["results"]["statistics"]["records_count"] == 2 * 96


def test_quarter_hour_file_overrides_hourly_data_per_slot(db):
    user = _create_user(db)
    _create_file_with_resolution(db, user, _days("2025-01-01", 1, 0.25), 60, name="godzinowy.csv", uploaded_at=T0)
    _create_file_with_resolution(db, user, {"2025-01-01": [1.0] * 4 + [None] * 92}, 15, name="kwadrans.csv", uploaded_at=T1)

    body = _all_data(user).json()

    assert body["results"]["tariffs"]["G11"]["total_usage_kwh"] == 4 + 92 * 0.25
    assert body["file"]["records_count"] == 4 + 23
