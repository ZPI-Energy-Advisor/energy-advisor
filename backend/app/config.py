import os

from dotenv import load_dotenv


load_dotenv()

# Wartości z .env.example: aplikacja skopiowana bez zmian nie może wystartować ze znanym sekretem.
PLACEHOLDER_SECRETS = frozenset({"generate_your_own_random_secret", "generate_your_own_random_key"})
MIN_SECRET_LENGTH = 32
SECRET_HINT = 'wygeneruj go: python -c "import secrets; print(secrets.token_urlsafe(48))"'


def require_secret(name: str, value: str | None) -> str:
    """Sekret musi być ustawiony, nie może być zaślepką z .env.example i musi mieć co najmniej 32 znaki."""
    if not value:
        raise RuntimeError(f"{name} must be configured ({SECRET_HINT})")
    if value in PLACEHOLDER_SECRETS:
        raise RuntimeError(f"{name} still has the placeholder value from .env.example ({SECRET_HINT})")
    if len(value) < MIN_SECRET_LENGTH:
        raise RuntimeError(f"{name} must be at least {MIN_SECRET_LENGTH} characters long ({SECRET_HINT})")
    return value


def optional_secret(name: str, value: str | None) -> str | None:
    """Pusty sekret wyłącza funkcję. Ustawiony musi spełniać te same warunki co wymagany."""
    return require_secret(name, value) if value else None


SECRET_KEY = require_secret("JWT_SECRET_KEY", os.getenv("JWT_SECRET_KEY"))

SIGNATURE_ALGORITHM = os.getenv("SIGNATURE_ALGORITHM", "HS256")
if SIGNATURE_ALGORITHM != "HS256":
    raise RuntimeError("Only HS256 is supported")

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") or None

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRATION_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRATION_DAYS", "7"))

CORS_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

PRICE_SYNC_ADMIN_KEY = optional_secret("PRICE_SYNC_ADMIN_KEY", os.getenv("PRICE_SYNC_ADMIN_KEY"))

HUB_URL = os.getenv("HUB_URL") or None
HUB_API_KEY = optional_secret("HUB_API_KEY", os.getenv("HUB_API_KEY"))
HUB_TIMEOUT_SECONDS = float(os.getenv("HUB_TIMEOUT_SECONDS") or 5)
HUB_HOME_USER_EMAIL = (os.getenv("HUB_HOME_USER_EMAIL") or "").strip().lower() or None

# Limity prób na /auth (ZP-134), format biblioteki limits, np. "5/minute". Liczone na adres IP.
RATE_LIMIT_ENABLED = (os.getenv("RATE_LIMIT_ENABLED") or "true").strip().lower() not in {"0", "false", "no"}
RATE_LIMIT_LOGIN = os.getenv("RATE_LIMIT_LOGIN") or "5/minute"
RATE_LIMIT_REGISTER = os.getenv("RATE_LIMIT_REGISTER") or "3/hour"
# Sprawdzanie adresu w profilu: każde to do 3 zapytań do Nominatim (1/s dla całej aplikacji), więc bez limitu
# seria zapytań zajęłaby wątki API i groziła blokadą naszego klienta w Nominatim.
RATE_LIMIT_ADDRESS_LOOKUP = os.getenv("RATE_LIMIT_ADDRESS_LOOKUP") or "20/minute"
# Pogoda na żądanie (ZP-117): brakujący miesiąc to zapytania do Open-Meteo, którego darmowy limit dzielą
# wszyscy użytkownicy i worker pogody.
RATE_LIMIT_WEATHER = os.getenv("RATE_LIMIT_WEATHER") or "30/minute"
# Ekran „Fotowoltaika” (ZP-150) czyta głównie bazę, a ten sam brakujący zakres pogody pobiera najwyżej raz na 5 minut,
# więc limit jest tylko zabezpieczeniem przed zalewem zapytań, a nie przy przeglądaniu dni.
RATE_LIMIT_PV_SCREEN = os.getenv("RATE_LIMIT_PV_SCREEN") or "300/minute"
