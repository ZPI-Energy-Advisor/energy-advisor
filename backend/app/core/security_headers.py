"""Nagłówki bezpieczeństwa dla odpowiedzi API (ZP-134).

API zwraca JSON, więc CSP blokuje wszystko. Wyjątek: dokumentacja Swagger/ReDoc, która ładuje
skrypty z CDN. Frontend dostaje własne nagłówki z nginx (frontend/security-headers.conf).
"""

from fastapi import FastAPI, Request

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}
API_CONTENT_SECURITY_POLICY = "default-src 'none'; frame-ancestors 'none'"
DOCS_PATHS = ("/docs", "/redoc")


def add_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if not request.url.path.startswith(DOCS_PATHS):
            response.headers.setdefault("Content-Security-Policy", API_CONTENT_SECURITY_POLICY)
        return response
