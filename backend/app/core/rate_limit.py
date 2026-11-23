"""Limity prób logowania i rejestracji (ZP-134).

Liczniki są w pamięci procesu i liczone na adres IP klienta. Dwa ograniczenia do pamiętania:
- kilka workerów uvicorna (ZP-136) ma osobne liczniki, więc faktyczny limit mnoży się przez ich liczbę;
- za reverse proxy (ZP-132) uvicorn musi dostać --proxy-headers i --forwarded-allow-ips,
  inaczej wszyscy użytkownicy mają adres proxy i dzielą jeden licznik.
"""

import math

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import RATE_LIMIT_ENABLED

limiter = Limiter(key_func=get_remote_address, enabled=RATE_LIMIT_ENABLED)

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
