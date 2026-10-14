import uuid
from datetime import timedelta

import pytest


AUTH = "/api/v1/auth"
PROTECTED = "/api/v1/energy-files"
PASSWORD = "Haslo123!"


def _register(client, email, password=PASSWORD):
    return client.post(f"{AUTH}/register", json={"email": email, "password": password})


def _login(client, email, password=PASSWORD):
    return client.post(f"{AUTH}/login", json={"email": email, "password": password})


def _refresh(client, refresh_token):
    return client.post(f"{AUTH}/refresh", json={"refresh_token": refresh_token})


def _logout(client, refresh_token):
    return client.post(f"{AUTH}/logout", json={"refresh_token": refresh_token})


def _bearer(access_token):
    return {"Authorization": f"Bearer {access_token}"}


def test_register_returns_working_tokens(anonymous_client, new_email):
    response = _register(anonymous_client, new_email)

    assert response.status_code == 200
    tokens = response.json()
    assert tokens.keys() == {"access_token", "refresh_token"}
    assert anonymous_client.get(PROTECTED, headers=_bearer(tokens["access_token"])).status_code == 200


def test_register_duplicate_email_is_rejected(anonymous_client, new_email):
    _register(anonymous_client, new_email)

    response = _register(anonymous_client, new_email.upper())

    assert response.status_code == 409


@pytest.mark.parametrize("password", ["krotkie", "bezwielkichliter1!", "BezCyfr!!", "BezSpecjalnych1"])
def test_register_rejects_weak_password(anonymous_client, new_email, password):
    assert _register(anonymous_client, new_email, password).status_code == 422


def test_login_with_valid_credentials(anonymous_client, new_email):
    _register(anonymous_client, new_email)

    response = _login(anonymous_client, f"  {new_email.upper()} ")

    assert response.status_code == 200
    assert anonymous_client.get(PROTECTED, headers=_bearer(response.json()["access_token"])).status_code == 200


def test_login_with_wrong_password(anonymous_client, new_email):
    _register(anonymous_client, new_email)

    assert _login(anonymous_client, new_email, "Zle-haslo123!").status_code == 401


def test_login_unknown_user(anonymous_client, new_email):
    assert _login(anonymous_client, new_email).status_code == 401


def test_refresh_returns_working_tokens(anonymous_client, new_email):
    refresh_token = _register(anonymous_client, new_email).json()["refresh_token"]

    response = _refresh(anonymous_client, refresh_token)

    assert response.status_code == 200
    assert anonymous_client.get(PROTECTED, headers=_bearer(response.json()["access_token"])).status_code == 200


def test_refresh_rejects_access_token(anonymous_client, new_email):
    access_token = _register(anonymous_client, new_email).json()["access_token"]

    assert _refresh(anonymous_client, access_token).status_code == 400


def test_refresh_rejects_invalid_token(anonymous_client):
    assert _refresh(anonymous_client, "nie-jwt").status_code == 401


def test_refresh_rejects_expired_token(anonymous_client, user_a, make_token):
    expired = make_token(user_a.id, token_type="refresh", expires_in=timedelta(minutes=-1))

    assert _refresh(anonymous_client, expired).status_code == 401


def test_refresh_rejects_token_not_issued_by_server(anonymous_client, user_a, make_token):
    forged = make_token(user_a.id, token_type="refresh", expires_in=timedelta(days=1))

    assert _refresh(anonymous_client, forged).status_code == 401


def test_logout_invalidates_refresh_token(anonymous_client, new_email):
    refresh_token = _register(anonymous_client, new_email).json()["refresh_token"]

    assert _logout(anonymous_client, refresh_token).status_code == 204
    assert _refresh(anonymous_client, refresh_token).status_code == 401
    assert _logout(anonymous_client, refresh_token).status_code == 401


@pytest.mark.xfail(
    strict=True,
    reason="Znany błąd: bcrypt porównuje tylko 72 pierwsze bajty JWT, więc po odświeżeniu stary "
    "refresh token nadal jest przyjmowany. Usuń xfail po naprawie.",
)
def test_refresh_rotates_refresh_token(anonymous_client, new_email, monkeypatch):
    old_token = _register(anonymous_client, new_email).json()["refresh_token"]
    monkeypatch.setattr("app.services.auth_service.REFRESH_TOKEN_EXPIRE_DAYS", 8)
    new_token = _refresh(anonymous_client, old_token).json()["refresh_token"]
    assert new_token != old_token

    assert _refresh(anonymous_client, old_token).status_code == 401


def test_expired_access_token_is_rejected(anonymous_client, user_a, make_token):
    expired = make_token(user_a.id, expires_in=timedelta(minutes=-1))

    response = anonymous_client.get(PROTECTED, headers=_bearer(expired))

    assert response.status_code == 401
    assert response.json()["detail"] == "Token wygasł"


def test_access_token_of_deleted_user_is_rejected(anonymous_client, make_token, db):
    assert anonymous_client.get(PROTECTED, headers=_bearer(make_token(uuid.uuid4()))).status_code == 401
