from contextlib import contextmanager
from typing import ContextManager, Iterator, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine



class LockNotAcquiredError(Exception):
    pass


class DistributedLock(Protocol):
    def acquire(self) -> ContextManager[None]:
        """Zakłada blokadę lub rzuca LockNotAcquiredError, jeśli trzyma ją ktoś inny."""
        ...


class PostgresAdvisoryLock:
    """Blokada między procesami (API i worker) oparta o pg_try_advisory_lock."""

    def __init__(self, engine: Engine, key: int):
        self.engine = engine
        self.key = key

    @contextmanager
    def acquire(self) -> Iterator[None]:
        with self.engine.connect() as connection:
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key}
            ).scalar()
            if not acquired:
                raise LockNotAcquiredError(f"Blokada {self.key} jest już zajęta")
            try:
                yield
            finally:
                # Blokada sesyjna przetrwałaby zwrot połączenia do puli - zwalniamy ją jawnie.
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.key})
                connection.commit()
