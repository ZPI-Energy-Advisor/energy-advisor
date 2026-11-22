import pytest

from app.config import RATE_LIMIT_LOGIN, RATE_LIMIT_REGISTER
from app.core.rate_limit import rate_limit_message, retry_after_text

AUTH = "/api/v1/auth"
PASSWORD = "Haslo123!"


def _allowed(limit: str) -> int:
    return int(limit.split("/")[0])


def test_login_is_limited_with_polish_message(anonymous_client, rate_limited, new_email):
    body = {"email": new_email, "password": "ZleHaslo1!"}
    for _ in range(_allowed(RATE_LIMIT_LOGIN)):
        assert anonymous_client.post(f"{AUTH}/login", json=body).status_code == 401

    response = anonymous_client.post(f"{AUTH}/login", json=body)

    assert response.status_code == 429
    assert response.json()["detail"].startswith("Zbyt wiele prób. Spróbuj ponownie za")
    assert response.json()["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) > 0


def test_register_is_limited(anonymous_client, rate_limited, new_email):
    for i in range(_allowed(RATE_LIMIT_REGISTER)):
        anonymous_client.post(f"{AUTH}/register", json={"email": f"{i}-{new_email}", "password": PASSWORD})

    response = anonymous_client.post(f"{AUTH}/register", json={"email": f"x-{new_email}", "password": PASSWORD})

    assert response.status_code == 429


def test_login_limit_does_not_block_registration(anonymous_client, rate_limited, new_email):
    body = {"email": new_email, "password": "ZleHaslo1!"}
    for _ in range(_allowed(RATE_LIMIT_LOGIN) + 1):
        anonymous_client.post(f"{AUTH}/login", json=body)

    response = anonymous_client.post(f"{AUTH}/register", json={"email": new_email, "password": PASSWORD})

    assert response.status_code == 200


def test_refresh_is_not_limited(anonymous_client, rate_limited):
    """Refresh token to długi losowy JWT, a 429 przy odświeżaniu wylogowałby użytkownika we frontendzie."""
    for _ in range(_allowed(RATE_LIMIT_LOGIN) + 1):
        response = anonymous_client.post(f"{AUTH}/refresh", json={"refresh_token": "niepoprawny"})
        assert response.status_code != 429


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(1, "1 sekundę"), (30, "30 sekund"), (60, "1 minutę"), (120, "2 minuty"), (300, "5 minut"), (3600, "60 minut")],
)
def test_retry_after_text_in_polish(seconds, text):
    assert retry_after_text(seconds) == text


def test_rate_limit_message():
    assert rate_limit_message(60) == "Zbyt wiele prób. Spróbuj ponownie za 1 minutę."
