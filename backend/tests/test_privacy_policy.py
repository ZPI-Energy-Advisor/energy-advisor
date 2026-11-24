import uuid

import pytest

from app.models.PrivacyConsent import PrivacyConsent
from app.models.User import User
from app.services import auth_service, privacy_policy, user_service
from app.services.privacy_policy import PRIVACY_POLICY_VERSION
from conftest import TEST_EMAIL_DOMAIN


AUTH = "/api/v1/auth"
ME = "/api/v1/users/me"
CONSENT = "/api/v1/users/me/privacy-consent"
POLICY = "/api/v1/legal/privacy-policy"
PASSWORD = "Haslo123!"
NEW_VERSION = "2099-01-01"


def _register(client, email, **extra):
    return client.post(f"{AUTH}/register", json={"email": email, "password": PASSWORD, **extra})


def _consents(db, email):
    user = db.query(User).filter(User.email == email).one()
    return db.query(PrivacyConsent).filter(PrivacyConsent.user_id == user.id).all()


@pytest.fixture
def new_policy_version(monkeypatch):
    """Symuluje publikację nowej wersji polityki."""
    for module in (privacy_policy, auth_service, user_service):
        monkeypatch.setattr(module, "PRIVACY_POLICY_VERSION", NEW_VERSION)
    return NEW_VERSION


@pytest.fixture
def google_account(monkeypatch):
    """Logowanie Google bez zapytań do Google: każdy `google_code` to zweryfikowany token konta z tym `sub`."""
    accounts = {}

    def verify(token, request, client_id):
        return accounts[token]

    monkeypatch.setattr(auth_service, "CLIENT_ID", "test-client-id")
    monkeypatch.setattr(auth_service.id_token, "verify_oauth2_token", verify)

    def _account():
        code = f"google-{uuid.uuid4().hex[:12]}"
        accounts[code] = {"sub": code, "email": f"{code}@{TEST_EMAIL_DOMAIN}", "email_verified": True}
        return code, accounts[code]["email"]

    return _account


def test_policy_is_public(anonymous_client):
    response = anonymous_client.get(POLICY)

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == PRIVACY_POLICY_VERSION
    assert "energy-advisor@gmail.com" in body["content"]
    assert "Prezesa Urzędu Ochrony Danych Osobowych" in body["content"]
    assert "12 miesięcy" in body["content"]


def test_register_saves_consent_with_version_and_date(anonymous_client, db, new_email):
    response = _register(anonymous_client, new_email, accepted_policy_version=PRIVACY_POLICY_VERSION)

    assert response.status_code == 200
    [consent] = _consents(db, new_email)
    assert consent.policy_version == PRIVACY_POLICY_VERSION
    assert consent.source == "register"
    assert consent.accepted_at is not None


def test_register_without_consent_is_rejected(anonymous_client, db, new_email):
    assert _register(anonymous_client, new_email).status_code == 422
    assert db.query(User).filter(User.email == new_email).count() == 0


def test_register_with_outdated_version_is_rejected(anonymous_client, db, new_email):
    response = _register(anonymous_client, new_email, accepted_policy_version="2020-01-01")

    assert response.status_code == 400
    assert db.query(User).filter(User.email == new_email).count() == 0


def test_registered_user_does_not_need_acceptance(anonymous_client, new_email):
    tokens = _register(anonymous_client, new_email, accepted_policy_version=PRIVACY_POLICY_VERSION).json()

    status = anonymous_client.get(ME, headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()

    assert status["privacy_policy"]["accepted_version"] == PRIVACY_POLICY_VERSION
    assert status["privacy_policy"]["needs_acceptance"] is False


def test_first_google_login_without_consent_does_not_create_account(anonymous_client, db, google_account):
    code, email = google_account()

    response = anonymous_client.post(f"{AUTH}/google", json={"google_code": code})

    assert response.status_code == 403
    assert response.json()["code"] == "privacy_policy_required"
    assert db.query(User).filter(User.email == email).count() == 0


def test_first_google_login_with_consent_saves_it(anonymous_client, db, google_account):
    code, email = google_account()

    response = anonymous_client.post(
        f"{AUTH}/google", json={"google_code": code, "accepted_policy_version": PRIVACY_POLICY_VERSION}
    )

    assert response.status_code == 200
    [consent] = _consents(db, email)
    assert consent.policy_version == PRIVACY_POLICY_VERSION
    assert consent.source == "google"


def test_next_google_login_does_not_ask_for_consent(anonymous_client, db, google_account):
    code, email = google_account()
    anonymous_client.post(f"{AUTH}/google", json={"google_code": code, "accepted_policy_version": PRIVACY_POLICY_VERSION})

    response = anonymous_client.post(f"{AUTH}/google", json={"google_code": code})

    assert response.status_code == 200
    assert len(_consents(db, email)) == 1


def test_account_without_consent_needs_acceptance(client_a):
    status = client_a.get(ME).json()["privacy_policy"]

    assert status == {
        "current_version": PRIVACY_POLICY_VERSION,
        "accepted_version": None,
        "accepted_at": None,
        "needs_acceptance": True,
    }


def test_new_policy_version_asks_for_acceptance_again(anonymous_client, new_email, new_policy_version, monkeypatch):
    tokens = _register(anonymous_client, new_email, accepted_policy_version=NEW_VERSION).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert anonymous_client.get(ME, headers=headers).json()["privacy_policy"]["needs_acceptance"] is False

    newer = "2100-01-01"
    for module in (privacy_policy, auth_service, user_service):
        monkeypatch.setattr(module, "PRIVACY_POLICY_VERSION", newer)

    status = anonymous_client.get(ME, headers=headers).json()["privacy_policy"]
    assert status["accepted_version"] == NEW_VERSION
    assert status["current_version"] == newer
    assert status["needs_acceptance"] is True


def test_accepting_current_version_is_saved(client_a, db, user_a):
    response = client_a.post(CONSENT, json={"version": PRIVACY_POLICY_VERSION})

    assert response.status_code == 200
    assert response.json()["needs_acceptance"] is False
    [consent] = db.query(PrivacyConsent).filter(PrivacyConsent.user_id == user_a.id).all()
    assert consent.source == "reaccept"
    assert client_a.get(ME).json()["privacy_policy"]["needs_acceptance"] is False


def test_accepting_twice_keeps_one_row(client_a, db, user_a):
    client_a.post(CONSENT, json={"version": PRIVACY_POLICY_VERSION})
    client_a.post(CONSENT, json={"version": PRIVACY_POLICY_VERSION})

    assert db.query(PrivacyConsent).filter(PrivacyConsent.user_id == user_a.id).count() == 1


def test_accepting_outdated_version_is_rejected(client_a, db, user_a):
    response = client_a.post(CONSENT, json={"version": "2020-01-01"})

    assert response.status_code == 400
    assert db.query(PrivacyConsent).filter(PrivacyConsent.user_id == user_a.id).count() == 0


def test_history_of_acceptances_is_kept(client_a, db, user_a, new_policy_version):
    db.add(PrivacyConsent(user_id=user_a.id, policy_version="2020-01-01", source="register"))
    db.commit()

    client_a.post(CONSENT, json={"version": new_policy_version})

    versions = {c.policy_version for c in db.query(PrivacyConsent).filter(PrivacyConsent.user_id == user_a.id)}
    assert versions == {"2020-01-01", new_policy_version}


def test_consents_are_deleted_with_account(client_a, db, user_a):
    client_a.post(CONSENT, json={"version": PRIVACY_POLICY_VERSION})
    user_id = user_a.id

    assert client_a.request("DELETE", ME, json={"confirm_email": user_a.email}).status_code == 204

    db.expire_all()
    assert db.query(PrivacyConsent).filter(PrivacyConsent.user_id == user_id).count() == 0
