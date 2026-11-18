from datetime import date

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.v1.deps import get_user_repository, get_user_service
from app.models.UserProfile import UserProfile
from app.schemas.other import TariffTypeEnum
from app.services.user_service import UserService
from main import app
from tariff_helpers import FlatTariffRepository, flat_definition


def _rates():
    old_g12 = flat_definition(TariffTypeEnum.G12, energy=("0.4", "0.9"), network=("0", "0"))
    old_g12.valid_from, old_g12.valid_to = date(2020, 1, 1), date(2025, 12, 31)
    old_g12.name = "G12 do 2025"
    new_g12 = flat_definition(TariffTypeEnum.G12, energy=("0.5", "1.0"), network=("0", "0"))
    new_g12.valid_from = date(2026, 1, 1)
    dynamic = flat_definition(TariffTypeEnum.DYNAMIC, energy=("0.1",), distribution_group=TariffTypeEnum.G12)
    dynamic.name = "Prąd z ceną dynamiczną"
    return FlatTariffRepository([flat_definition(TariffTypeEnum.G11), old_g12, new_g12, dynamic])


@pytest.fixture
def rates():
    repository = _rates()

    def override(user_repository=Depends(get_user_repository)):
        return UserService(user_repository, repository)

    app.dependency_overrides[get_user_service] = override
    yield repository
    app.dependency_overrides.pop(get_user_service, None)


def profile_payload(tariff_type="G12", dynamic=False):
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
        "consumption_and_tariff": {"tariff_type": tariff_type, "dynamic_price": dynamic},
        "pv_config": {"mode": "none"},
    }


def test_me_without_profile_has_no_tariff(client_a, user_a, rates):
    response = client_a.get("/api/v1/users/me")

    assert response.status_code == 200
    assert response.json() == {
        "email": user_a.email,
        "provider": "local",
        "current_tariff": None,
        "profile": {"exists": False, "needs_update": False, "tariff_type": None},
        "home_owner": False,
    }


def test_current_tariff_is_definition_of_profile_tariff_valid_today(client_a, rates):
    assert client_a.put("/api/v1/users/me/profile", json=profile_payload("G12")).status_code == 200

    me = client_a.get("/api/v1/users/me").json()

    assert me["profile"] == {"exists": True, "needs_update": False, "tariff_type": "G12"}
    assert me["current_tariff"] == {
        "code": "G12",
        "label": "G12",
        "name": None,
        "operator": "TAURON",
        "tariff_code": "G12",
        "distribution_group": "G12",
        "dynamic": False,
        "valid_from": "2026-01-01",
        "valid_to": "2035-12-31",
    }


def test_current_tariff_depends_on_date(user_a, rates, db):
    db.add(UserProfile(user_id=user_a.id, **profile_payload("G12")))
    db.commit()

    service = UserService(get_user_repository(db), rates)

    assert service.get_current_user(user_a, today=date(2025, 6, 1)).current_tariff.name == "G12 do 2025"
    assert service.get_current_user(user_a, today=date(2026, 6, 1)).current_tariff.valid_from == date(2026, 1, 1)


def test_changing_profile_tariff_changes_current_tariff(client_a, rates):
    client_a.put("/api/v1/users/me/profile", json=profile_payload("G12"))

    client_a.put("/api/v1/users/me/profile", json=profile_payload("G11"))

    assert client_a.get("/api/v1/users/me").json()["current_tariff"]["code"] == "G11"


def test_current_tariff_persists_across_sessions(client_a, user_a, make_token, rates):
    client_a.put("/api/v1/users/me/profile", json=profile_payload("G12"))

    other_session = TestClient(app, headers={"Authorization": f"Bearer {make_token(user_a.id)}"})

    assert other_session.get("/api/v1/users/me").json()["current_tariff"]["code"] == "G12"


def test_profile_tariff_without_rates_has_no_current_tariff(client_a, user_a, db, rates):
    db.add(UserProfile(user_id=user_a.id, **profile_payload("G13")))
    db.commit()

    me = client_a.get("/api/v1/users/me").json()

    assert me["profile"] == {"exists": True, "needs_update": False, "tariff_type": "G13"}
    assert me["current_tariff"] is None


def test_outdated_profile_needs_update(client_a, user_a, db, rates):
    outdated = profile_payload("G12")
    del outdated["base_info"]["billing_period_start_date"]
    db.add(UserProfile(user_id=user_a.id, **outdated))
    db.commit()

    me = client_a.get("/api/v1/users/me").json()

    assert me["profile"] == {"exists": True, "needs_update": True, "tariff_type": "G12"}
    assert me["current_tariff"] is None
    response = client_a.get("/api/v1/users/me/profile")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["message"] == "Profil użytkownika wymaga ponownego uzupełnienia."
    assert detail["fields"] == ["base_info.billing_period_start_date"]
    assert detail["profile"]["base_info"]["postal_code"] == outdated["base_info"]["postal_code"]


def test_dynamic_profile_points_to_dynamic_offer_of_its_group(client_a, rates):
    assert client_a.put("/api/v1/users/me/profile", json=profile_payload("G12", dynamic=True)).status_code == 200

    me = client_a.get("/api/v1/users/me").json()

    assert me["profile"]["tariff_type"] == "G12"
    tariff = me["current_tariff"]
    assert (tariff["code"], tariff["label"], tariff["dynamic"]) == ("G12-dynamic", "G12 z ceną dynamiczną", True)
    assert (tariff["tariff_code"], tariff["distribution_group"]) == ("dynamic", "G12")
    assert tariff["name"] == "Prąd z ceną dynamiczną"


def test_profile_is_isolated_between_users(client_a, client_b, rates):
    client_a.put("/api/v1/users/me/profile", json=profile_payload("G12"))

    assert client_b.get("/api/v1/users/me/profile").status_code == 404
    me_b = client_b.get("/api/v1/users/me").json()
    assert me_b["profile"]["exists"] is False
    assert me_b["current_tariff"] is None


def test_tariff_cannot_be_changed_outside_profile(client_a, rates):
    assert client_a.patch("/api/v1/users/me/tariff", json={"tariff_id": 1}).status_code in (404, 405)


def test_old_profile_endpoints_are_removed(client_a):
    assert client_a.get("/api/v1/upload/profile").status_code in (404, 405)
    assert client_a.post("/api/v1/upload/profile", json=profile_payload()).status_code in (404, 405)
