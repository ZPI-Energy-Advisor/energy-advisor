import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR.parent / ".env")

_configured_db = os.getenv("POSTGRES_DB", "energy_advisor")
TEST_DATABASE = _configured_db if _configured_db.endswith("_test") else f"{_configured_db}_test"
os.environ["POSTGRES_DB"] = TEST_DATABASE
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-only-for-pytest-0123456789")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.database import SessionLocal, database_url  # noqa: E402
from app.models.User import User  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from main import app  # noqa: E402


TEST_EMAIL_DOMAIN = "tests.example.com"


def pytest_configure(config):
    config.addinivalue_line("markers", "perf: test wydajności z limitem czasu; pominięcie: -m \"not perf\"")


def pytest_report_header(config):
    from timing import MACHINE_FACTOR, TIME_LIMIT_SCALE

    return f"limity testów wydajności: ×{TIME_LIMIT_SCALE:.2f} (maszyna ×{MACHINE_FACTOR:.2f} względem wzorcowej)"


def _prepare_test_database() -> str | None:
    """Zakłada bazę testową, jeśli nie istnieje, i migruje ją do head. Zwraca opis błędu albo None."""
    url = make_url(database_url)
    try:
        admin_engine = create_engine(
            url.set(database="postgres"),
            isolation_level="AUTOCOMMIT",
            connect_args={"connect_timeout": 3},
        )
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{url.database}"'))
        admin_engine.dispose()
    except Exception:
        pass  

    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        return str(exc).splitlines()[0]
    return None


DATABASE_ERROR = _prepare_test_database()


@pytest.fixture(autouse=True)
def _rate_limit_off():
    """Testy rejestrują wielu użytkowników z jednego adresu, więc limity prób są domyślnie wyłączone.
    Fixture `rate_limited` włącza je dla pojedynczego testu."""
    from app.core.rate_limit import limiter

    limiter.enabled = False
    yield
    limiter.enabled = False


@pytest.fixture
def rate_limited():
    from app.core.rate_limit import limiter

    limiter.reset()
    limiter.enabled = True
    yield limiter
    limiter.enabled = False
    limiter.reset()


@pytest.fixture(autouse=True)
def _fresh_device_series():
    # Seria urządzeń źródła jest w pamięci procesu (ZP-147): każdy test zaczyna z pustą.
    from app.services.device_series import series_cache

    series_cache.clear()
    yield
    series_cache.clear()


@pytest.fixture(autouse=True)
def _fresh_price_cache():
    # Testy wstawiają różne ceny RCE dla tych samych miesięcy, więc pamięć cen nie może przechodzić między nimi.
    from app.services.pv_service import clear_rce_cache

    clear_rce_cache()
    yield
    clear_rce_cache()


class OfflineGeocoder:
    def by_postal_code(self, postal_code):
        from app.providers.geocoding import GeocoderError

        raise GeocoderError("testy nie pytają Nominatim", unavailable=True)

    def by_town(self, town, near=None):
        return []

    def postal_code_at(self, place):
        return None


@pytest.fixture(autouse=True)
def _offline_geocoder(monkeypatch):
    from app.providers import geocoding

    monkeypatch.setattr(geocoding, "default_geocoder", OfflineGeocoder)


class OfflineWeather:
    def forecast(self, *args):
        from app.providers.weather import WeatherProviderError

        raise WeatherProviderError("testy nie pytają Open-Meteo", retryable=False)

    archive = forecast


@pytest.fixture(autouse=True)
def _offline_weather(monkeypatch):
    from app.providers import weather

    monkeypatch.setattr(weather, "default_client", OfflineWeather)
    monkeypatch.setattr(weather, "interactive_client", OfflineWeather)


@pytest.fixture(autouse=True)
def _fresh_fetch_attempts():
    from app.services.weather_service import clear_fetch_attempts

    clear_fetch_attempts()
    yield
    clear_fetch_attempts()


@pytest.fixture
def db():
    if DATABASE_ERROR:
        pytest.skip(f"Baza testowa niedostępna: {DATABASE_ERROR}")

    session = SessionLocal()
    yield session
    session.rollback()
    session.query(User).filter(User.email.like(f"%@{TEST_EMAIL_DOMAIN}")).delete(synchronize_session=False)
    session.commit()
    session.close()


@pytest.fixture
def new_email(db):
    return f"user-{uuid.uuid4().hex[:12]}@{TEST_EMAIL_DOMAIN}"


def _create_user(db, label: str) -> User:
    user = User(email=f"{label}-{uuid.uuid4().hex[:12]}@{TEST_EMAIL_DOMAIN}", provider="local")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def user_a(db) -> User:
    return _create_user(db, "user-a")


@pytest.fixture
def user_b(db) -> User:
    return _create_user(db, "user-b")


@pytest.fixture
def make_token():
    auth = AuthService(repository=None)

    def _make(user_id, token_type: str = "access", expires_in: timedelta = timedelta(minutes=5)) -> str:
        return auth.generate_token(user_id, token_type, datetime.now(timezone.utc) + expires_in)

    return _make


@pytest.fixture
def anonymous_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def client_a(user_a, make_token) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {make_token(user_a.id)}"})


@pytest.fixture
def client_b(user_b, make_token) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {make_token(user_b.id)}"})


@pytest.fixture
def flat_tariffs():
    """Endpointy kosztów (silnik rachunku i ceny kwadransów) liczą na cenniku z `FlatTariffRepository`
    (G11 za 1 zł/kWh) zamiast na pustym cenniku bazy."""
    from app.api.v1.deps import get_tariff_definition_repository
    from tariff_helpers import FlatTariffRepository

    app.dependency_overrides[get_tariff_definition_repository] = FlatTariffRepository
    yield
    app.dependency_overrides.pop(get_tariff_definition_repository, None)
