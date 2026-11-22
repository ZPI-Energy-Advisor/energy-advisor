import pytest

from app.config import CORS_ORIGINS
from app.core.security_headers import API_CONTENT_SECURITY_POLICY, SECURITY_HEADERS


@pytest.mark.parametrize("path", ["/api/health", "/api/v1/energy-files", "/api/v1/nie-ma-takiego"])
def test_api_responses_have_security_headers(anonymous_client, path):
    """Nagłówki są także na odpowiedziach błędów (401, 404)."""
    response = anonymous_client.get(path)

    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert response.headers["Content-Security-Policy"] == API_CONTENT_SECURITY_POLICY


def test_swagger_docs_are_not_blocked_by_api_csp(anonymous_client):
    response = anonymous_client.get("/docs")

    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_cors_preflight_still_works(anonymous_client):
    response = anonymous_client.options(
        "/api/v1/auth/login",
        headers={"Origin": CORS_ORIGINS[0], "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == CORS_ORIGINS[0]
