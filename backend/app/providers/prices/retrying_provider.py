import logging
import time
from datetime import date
from typing import Callable

from app.providers.prices.base import PricePoint, PriceProvider, PriceProviderError



logger = logging.getLogger(__name__)


class RetryingPriceProvider:
    """Dekorator dodający ponawianie z wykładniczym backoffem do dowolnego dostawcy."""

    def __init__(
        self,
        inner: PriceProvider,
        max_attempts: int = 3,
        base_delay_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts musi być >= 1")
        self.inner = inner
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.sleep = sleep

    @property
    def source(self) -> str:
        return self.inner.source

    def fetch_day(self, business_date: date) -> list[PricePoint]:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self.inner.fetch_day(business_date)
            except PriceProviderError as e:
                if not e.retryable or attempt == self.max_attempts:
                    raise
                delay = self.base_delay_seconds * 2 ** (attempt - 1)
                logger.warning(
                    "Próba %d/%d pobrania cen %s z %s nieudana: %s. Ponawiam za %.1fs",
                    attempt, self.max_attempts, business_date, self.source, e, delay,
                )
                self.sleep(delay)
        raise AssertionError("unreachable")
