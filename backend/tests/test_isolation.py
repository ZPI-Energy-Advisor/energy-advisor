import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

import pytest

from app.models.EnergyDataFile import EnergyDataFile
from app.models.Simulation import Simulation
from main import app


PUBLIC_ENDPOINTS = {
    ("GET", "/api/health"),
    ("POST", "/api/v1/auth/google"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/dynamic-prices/sync"),
}


def _all_endpoints() -> set[tuple[str, str]]:
    return {(method.upper(), path) for path, operations in app.openapi()["paths"].items() for method in operations}


PROTECTED_ENDPOINTS = sorted(_all_endpoints() - PUBLIC_ENDPOINTS)


def _url(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), path)


def test_public_endpoints_exist():
    assert PUBLIC_ENDPOINTS <= _all_endpoints()


CREDENTIALS = {
    "brak-tokenu": lambda make_token: None,
    "zly-token": lambda make_token: "nie-jwt",
    "wygasly-token": lambda make_token: make_token(uuid.uuid4(), expires_in=timedelta(minutes=-1)),
    "token-refresh": lambda make_token: make_token(uuid.uuid4(), token_type="refresh"),
}


@pytest.mark.parametrize("credentials", CREDENTIALS.values(), ids=CREDENTIALS.keys())
@pytest.mark.parametrize("method, path", PROTECTED_ENDPOINTS, ids=[f"{m} {p}" for m, p in PROTECTED_ENDPOINTS])
def test_protected_endpoint_requires_valid_access_token(anonymous_client, make_token, method, path, credentials):
    token = credentials(make_token)
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    response = anonymous_client.request(method, _url(path), headers=headers)

    assert response.status_code == 401



SAMPLE_RESULTS = {
    "tariffs": {"G11": {"type": "stala", "total_usage_kwh": 1.0, "estimated_cost_pln": 1.0}},
    "chart_daily": [{"date": "2024-11-03", "kwh": 1.0}],
    "statistics": {"records_count": 3, "data_start": "2024-11-03", "data_end": "2024-11-05"},
}


def _create_file_with_simulation(db, user) -> tuple[EnergyDataFile, Simulation]:
    energy_file = EnergyDataFile(
        user_id=user.id,
        file_name="dane.csv",
        uploaded_at=datetime.utcnow(),
        data_start=date(2024, 11, 3),
        data_end=date(2024, 11, 5),
        records_count=3,
        status=EnergyDataFile.STATUS_COMPLETED,
    )
    db.add(energy_file)
    db.commit()
    simulation = Simulation(user_id=user.id, energy_data_file_id=energy_file.id, results=SAMPLE_RESULTS)
    db.add(simulation)
    db.commit()
    return energy_file, simulation


@dataclass(frozen=True)
class OwnedResource:
    create: Callable 
    read: str 
    delete: str | None = None  


OWNED_RESOURCES = {
    "energy-file": OwnedResource(
        create=lambda db, user: _create_file_with_simulation(db, user)[0].id,
        read="/api/v1/energy-files/{id}/data",
        delete="/api/v1/energy-files/{id}",
    ),
    "simulation": OwnedResource(
        create=lambda db, user: _create_file_with_simulation(db, user)[1].id,
        read="/api/v1/results/{id}",
    ),
}

resource_params = pytest.mark.parametrize("resource", OWNED_RESOURCES.values(), ids=OWNED_RESOURCES.keys())


@resource_params
def test_owner_can_read_resource(db, user_a, client_a, resource):
    resource_id = resource.create(db, user_a)

    assert client_a.get(resource.read.format(id=resource_id)).status_code == 200


@resource_params
def test_reading_other_users_resource_returns_404(db, user_a, client_b, resource):
    resource_id = resource.create(db, user_a)

    response = client_b.get(resource.read.format(id=resource_id))

    assert response.status_code == 404
    assert "results" not in response.json()


@resource_params
def test_reading_nonexistent_resource_returns_404(client_a, resource):
    assert client_a.get(resource.read.format(id=uuid.uuid4())).status_code == 404


@pytest.mark.parametrize(
    "resource",
    [r for r in OWNED_RESOURCES.values() if r.delete],
    ids=[name for name, r in OWNED_RESOURCES.items() if r.delete],
)
def test_deleting_other_users_resource_returns_404_and_keeps_it(db, user_a, client_a, client_b, resource):
    resource_id = resource.create(db, user_a)

    assert client_b.delete(resource.delete.format(id=resource_id)).status_code == 404
    assert client_a.get(resource.read.format(id=resource_id)).status_code == 200


def test_lists_and_aggregates_show_only_own_data(db, user_a, client_b):
    _create_file_with_simulation(db, user_a)

    assert client_b.get("/api/v1/energy-files").json()["total"] == 0
    assert client_b.get("/api/v1/results").json() == {
        "status": "no_data", "simulation_id": None, "created_at": None, "results": None,
    }
    assert client_b.get("/api/v1/energy-files/all/data").status_code == 409
