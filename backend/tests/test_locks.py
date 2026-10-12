import pytest
from sqlalchemy import text

from app.core.locks import LockNotAcquiredError, PostgresAdvisoryLock
from app.database import engine


try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
except Exception as exc:  # brak bazy
    pytest.skip(f"Baza danych niedostępna: {exc}", allow_module_level=True)


# Inny numer niż PRICE_SYNC_LOCK_KEY, żeby test nie kolidował z działającym workerem.
TEST_LOCK_KEY = 0x7E57_0001


def test_second_acquire_fails_while_lock_is_held():
    first = PostgresAdvisoryLock(engine, TEST_LOCK_KEY)
    second = PostgresAdvisoryLock(engine, TEST_LOCK_KEY)

    with first.acquire():
        with pytest.raises(LockNotAcquiredError):
            with second.acquire():
                pass


def test_lock_is_released_after_block_also_on_error():
    lock = PostgresAdvisoryLock(engine, TEST_LOCK_KEY)

    with pytest.raises(RuntimeError):
        with lock.acquire():
            raise RuntimeError("błąd w trakcie synchronizacji")

    # Gdyby unlock nie zadziałał, połączenie wróciłoby do puli z założoną blokadą i to by się nie udało.
    with lock.acquire():
        pass
