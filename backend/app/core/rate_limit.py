"""Limity prób logowania i rejestracji (ZP-134).

Liczniki są w pamięci procesu i liczone na adres IP klienta. Dwa ograniczenia do pamiętania:
- kilka workerów uvicorna (ZP-136) ma osobne liczniki, więc faktyczny limit mnoży się przez ich liczbę;
- za reverse proxy wszyscy użytkownicy mieliby adres proxy i dzieliliby jeden licznik. nginx kontenera frontendu
  przekazuje /api do backendu z nagłówkiem X-Real-IP; ufamy mu tylko, gdy zapytanie przyszło z adresu tego
  kontenera (TRUSTED_PROXY_HOST, domyślnie „frontend” w sieci Dockera). Port 8000 jest wystawiony na zewnątrz,
  więc nagłówek od kogokolwiek innego pozwoliłby obejść limit.
"""

import math
import socket

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import RATE_LIMIT_ENABLED, TRUSTED_PROXY_HOST


def _trusted_proxy_ips() -> set[str]:
    """Adresy kontenera z nginx; poza Dockerem nazwa się nie rozwiązuje i nikomu nie ufamy."""
    if not TRUSTED_PROXY_HOST:
        return set()
    try:
        return {info[4][0] for info in socket.getaddrinfo(TRUSTED_PROXY_HOST, None)}
    except OSError:
        return set()


def client_ip(request: Request) -> str:
    """Adres klienta do limitów: z X-Real-IP tylko od zaufanego proxy, w pozostałych przypadkach adres połączenia."""
    direct = get_remote_address(request)
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip and direct in _trusted_proxy_ips():
        return real_ip
    return direct


limiter = Limiter(key_func=client_ip, enabled=RATE_LIMIT_ENABLED)

DEFAULT_RETRY_AFTER_SECONDS = 60


def _plural(count: int, one: str, few: str, many: str) -> str:
    if count == 1:
        return one
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return few
    return many


def retry_after_text(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} {_plural(seconds, 'sekundę', 'sekundy', 'sekund')}"
    minutes = math.ceil(seconds / 60)
    return f"{minutes} {_plural(minutes, 'minutę', 'minuty', 'minut')}"


def rate_limit_message(seconds: int) -> str:
    return f"Zbyt wiele prób. Spróbuj ponownie za {retry_after_text(seconds)}."


def _retry_after_seconds(error: RateLimitExceeded) -> int:
    """Okno limitu (np. 60 s dla "5/minute") jako górne oszacowanie czasu do odblokowania."""
    try:
        return max(1, int(error.limit.limit.get_expiry()))
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_RETRY_AFTER_SECONDS


def register_rate_limiting(app: FastAPI) -> None:
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def handle_rate_limit_exceeded(request: Request, error: RateLimitExceeded):
        seconds = _retry_after_seconds(error)
        return JSONResponse(
            status_code=429,
            content={"detail": rate_limit_message(seconds), "code": "rate_limited"},
            headers={"Retry-After": str(seconds)},
        )
