from datetime import time

import pytest
from fastapi.testclient import TestClient

from app.models.Tariff import Tariff
from app.models.TariffRate import TariffRate
from app.models.UserProfile import UserProfile
from app.schemas.other import TariffTypeEnum
from app.services.tariff_service import to_profile_tariff_type
from main import app


TEST_TARIFFS = [
    ("G11", Tariff.TYPE_FIXED, [(time(0, 0), time(23, 59, 59), 1.15)]),
    ("G12", Tariff.TYPE_ZONED, [(time(0, 0), time(5, 59, 59), 0.75), (time(6, 0), time(23, 59, 59), 1.35)]),
    ("Dynamiczna", Tariff.TYPE_DYNAMIC, []),
]


@pytest.fixture
def tariffs(db) -> dict[str, Tariff]:
    """Taryfy z seeda; brakujące zakłada na czas testu i potem usuwa."""
    created = []
    result = {}
    for name, tariff_type, rates in TEST_TARIFFS:
        tariff = db.query(Tariff).filter(Tariff.name == name).order_by(Tariff.id).first()
        if tariff is None:
            tariff = Tariff(name=name, type=tariff_type, description=f"Taryfa testowa {name}")
            tariff.rates = [TariffRate(time_start=start, time_end=end, price_per_kwh=price) for start, end, price in rates]
            db.add(tariff)
            db.commit()
            created.append(tariff)
        result[name] = tariff
    yield result
    for tariff in created:
        db.delete(tariff)
    db.commit()


def profile_payload(tariff_type="G12"):
    return {
        "base_info": {
            "type_of_property": "apartment",
            "year_of_construction": 2000,
            "heating_area_m2": 60,
            "number_of_residents": 2,
            "town": "Wrocław",
            "postal_code": "50-370",
            "distribution_operator": "TAURON",
            "phase_type": "1_phase",
            "contracted_power_kw": 5,
            "billing_cycle": 2,
            "billing_period_start_date": "2026-01-01",
        },
        "consumption_and_tariff": {"tariff_type": tariff_type},
        "pv_config": {"mode": "none"},
    }


@pytest.mark.parametrize(
    ("name", "tariff_type", "expected"),
    [
        ("G11", Tariff.TYPE_FIXED, TariffTypeEnum.G11),
        ("G12W", Tariff.TYPE_ZONED, TariffTypeEnum.G12W),
        ("g12w", Tariff.TYPE_ZONED, TariffTypeEnum.G12W),
        ("Dynamiczna", Tariff.TYPE_DYNAMIC, TariffTypeEnum.DYNAMIC),
        ("Nieznana", Tariff.TYPE_FIXED, None),
    ],
)
def test_tariff_maps_to_profile_tariff_type(name, tariff_type, expected):
    assert to_profile_tariff_type(Tariff(name=name, type=tariff_type)) == expected


def test_me_without_profile_has_no_tariff(client_a, user_a):
    response = client_a.get("/api/v1/users/me")

    assert response.status_code == 200
    assert response.json() == {
        "email": user_a.email,
        "provider": "local",
        "current_tariff": None,
        "profile": {"exists": False, "needs_update": False, "tariff_type": None},
        "home_owner": False,
    }


def test_current_tariff_comes_from_profile(client_a, tariffs):
    assert client_a.put("/api/v1/users/me/profile", json=profile_payload("G12")).status_code == 200

    me = client_a.get("/api/v1/users/me").json()

    assert me["profile"] == {"exists": True, "needs_update": False, "tariff_type": "G12"}
    assert me["current_tariff"]["id"] == tariffs["G12"].id
    assert me["current_tariff"]["code"] == "G12"
    assert me["current_tariff"]["profile_tariff_type"] == "G12"


def test_changing_profile_tariff_changes_current_tariff(client_a, tariffs):
    client_a.put("/api/v1/users/me/profile", json=profile_payload("G12"))

    client_a.put("/api/v1/users/me/profile", json=profile_payload("G11"))

    assert client_a.get("/api/v1/users/me").json()["current_tariff"]["code"] == "G11"


def test_current_tariff_persists_across_sessions(client_a, user_a, make_token, tariffs):
    client_a.put("/api/v1/users/me/profile", json=profile_payload("G12"))

    other_session = TestClient(app, headers={"Authorization": f"Bearer {make_token(user_a.id)}"})

    assert other_session.get("/api/v1/users/me").json()["current_tariff"]["code"] == "G12"


def test_profile_tariff_without_prices_in_database(client_a, db, tariffs):
    if db.query(Tariff).filter(Tariff.name.ilike("G13")).first():
        pytest.skip("Baza zawiera taryfę G13.")

    client_a.put("/api/v1/users/me/profile", json=profile_payload("G13"))

    me = client_a.get("/api/v1/users/me").json()
    assert me["profile"] == {"exists": True, "needs_update": False, "tariff_type": "G13"}
    assert me["current_tariff"] is None


def test_outdated_profile_needs_update(client_a, user_a, db, tariffs):
    outdated = profile_payload("G12")
    del outdated["base_info"]["billing_period_start_date"]
    db.add(UserProfile(user_id=user_a.id, **outdated))
    db.commit()

    me = client_a.get("/api/v1/users/me").json()

    assert me["profile"] == {"exists": True, "needs_update": True, "tariff_type": "G12"}
    assert client_a.get("/api/v1/users/me/profile").status_code == 409


def test_dynamic_profile_tariff_points_to_dynamic_tariff(client_a, tariffs):
    client_a.put("/api/v1/users/me/profile", json=profile_payload("dynamic"))

    me = client_a.get("/api/v1/users/me").json()

    assert me["profile"] == {"exists": True, "needs_update": False, "tariff_type": "dynamic"}
    assert me["current_tariff"]["type"] == Tariff.TYPE_DYNAMIC
    assert me["current_tariff"]["profile_tariff_type"] == "dynamic"


def test_profile_is_isolated_between_users(client_a, client_b, tariffs):
    client_a.put("/api/v1/users/me/profile", json=profile_payload("G12"))

    assert client_b.get("/api/v1/users/me/profile").status_code == 404
    me_b = client_b.get("/api/v1/users/me").json()
    assert me_b["profile"]["exists"] is False
    assert me_b["current_tariff"] is None


def test_tariff_cannot_be_changed_outside_profile(client_a, tariffs):
    assert client_a.patch("/api/v1/users/me/tariff", json={"tariff_id": tariffs["G11"].id}).status_code in (404, 405)


def test_old_profile_endpoints_are_removed(client_a):
    assert client_a.get("/api/v1/upload/profile").status_code in (404, 405)
    assert client_a.post("/api/v1/upload/profile", json=profile_payload()).status_code in (404, 405)
