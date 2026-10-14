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
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

import pytest 
from alembic import command  
from alembic.config import Config  
from fastapi.testclient import TestClient  
from sqlalchemy import create_engine, text  
from sqlalchemy.engine import make_url  

from app.database import SessionLocal, database_url  
from app.models.User import User  
from app.services.auth_service import AuthService  
from main import app  



TEST_EMAIL_DOMAIN = "tests.example.com"


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
