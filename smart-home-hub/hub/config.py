import os
from dataclasses import dataclass
from pathlib import Path

# Wartość z .env.example: hub skopiowany bez zmian nie może wystartować ze znanym kluczem.
PLACEHOLDER_API_KEYS = frozenset({"generate_your_own_random_key"})
# Ta sama reguła co w backendzie (app/config.py): oba czytają ten sam HUB_API_KEY.
MIN_API_KEY_LENGTH = 32



@dataclass(frozen=True)
class HubSettings:
    api_key: str
    state_dir: Path
    device_bind_host: str = "127.0.0.1"
    first_port: int = 9101
    last_port: int = 9150
    health_interval_seconds: float = 5.0
    device_start_timeout_seconds: float = 30.0
    max_restarts: int = 3
    backend_url: str | None = None
    event_buffer_size: int = 50_000
    webhook_batch_size: int = 500
    webhook_timeout_seconds: float = 10.0
    webhook_retry_min_seconds: float = 0.5
    webhook_retry_max_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "HubSettings":
        api_key = os.getenv("HUB_API_KEY")
        if not api_key:
            raise RuntimeError("HUB_API_KEY must be configured")
        if api_key in PLACEHOLDER_API_KEYS:
            raise RuntimeError("HUB_API_KEY still has the placeholder value from .env.example")
        if len(api_key) < MIN_API_KEY_LENGTH:
            raise RuntimeError(f"HUB_API_KEY must be at least {MIN_API_KEY_LENGTH} characters long")
        return cls(
            api_key=api_key,
            state_dir=Path(os.getenv("HUB_STATE_DIR", "/data")),
            device_bind_host=os.getenv("DEVICE_BIND_HOST", "127.0.0.1"),
            health_interval_seconds=float(os.getenv("HUB_HEALTH_INTERVAL_SECONDS", "5")),
            backend_url=(os.getenv("BACKEND_URL") or "").strip().rstrip("/") or None,
            event_buffer_size=int(os.getenv("HUB_EVENT_BUFFER_SIZE", "50000")),
        )
