import asyncio
import itertools
import logging
import uuid
from collections import deque
from enum import Enum

import httpx

from hub.config import HubSettings



logger = logging.getLogger(__name__)

EVENTS_PATH = "/api/v1/home/events"
RETRYABLE_STATUSES = {408, 429}


class _Outcome(Enum):
    DELIVERED = "delivered"
    RETRY = "retry"


class EventPublisher:
    """Kolejka zdarzeń dla backendu i ich wysyłka partiami: hub → backend, POST /api/v1/home/events.

    Zdarzenie dostaje `event_id` przy dodaniu do kolejki i wychodzi z niej dopiero po odpowiedzi backendu,
    więc ponowiona partia ma te same identyfikatory, a backend pomija zdarzenia, które już zapisał.
    Partie idą po kolei, jedna naraz, więc backend dostaje zdarzenia w kolejności powstania.

    Timeout, błąd połączenia, 5xx, 408 i 429: ta sama partia jeszcze raz, z rosnącą przerwą.
    401 i 403: błąd konfiguracji HUB_API_KEY, partia jest odrzucana bez ponawiania. Pozostałe 4xx:
    backend uznał partię za niepoprawną, ponowienie nic nie zmieni, więc też jest odrzucana.
    """

    def __init__(self, settings: HubSettings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.url = f"{settings.backend_url}{EVENTS_PATH}" if settings.backend_url else None
        self.dropped = 0
        self._pending: deque[dict] = deque()
        self._available = asyncio.Event()
        self._client = None
        if self.url:
            self._client = httpx.AsyncClient(
                timeout=settings.webhook_timeout_seconds,
                headers={"X-Hub-Api-Key": settings.api_key},
                transport=transport,
                trust_env=False,
            )

    @property
    def enabled(self) -> bool:
        return self.url is not None

    @property
    def pending(self) -> list[dict]:
        """Zdarzenia czekające na potwierdzenie backendu, w kolejności wysyłki."""
        return list(self._pending)

    def publish(self, simulation_id: str, events: list[dict]) -> None:
        if not self.enabled or not events:
            return
        self._pending.extend(
            {"event_id": f"evt_{uuid.uuid4().hex}", "simulation_id": simulation_id, **event} for event in events
        )
        overflow = len(self._pending) - self.settings.event_buffer_size
        if overflow > 0:
            for _ in range(overflow):
                self._pending.popleft()
            if not self.dropped:
                logger.error("Backend nie odbiera zdarzeń: kolejka pełna, najstarsze zdarzenia są odrzucane")
            self.dropped += overflow
        self._available.set()

    async def run(self) -> None:
        delay = self.settings.webhook_retry_min_seconds
        while True:
            if not self._pending:
                self._available.clear()
                await self._available.wait()
                continue
            if await self._send_batch() is _Outcome.RETRY:
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.settings.webhook_retry_max_seconds)
            else:
                delay = self.settings.webhook_retry_min_seconds

    async def flush(self) -> None:
        """Jedna próba wysłania wszystkiego, co czeka, np. przy zamykaniu huba."""
        while self._pending and await self._send_batch() is _Outcome.DELIVERED:
            pass

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _send_batch(self) -> _Outcome:
        batch = list(itertools.islice(self._pending, self.settings.webhook_batch_size))
        try:
            response = await self._client.post(self.url, json={"events": batch})
        except httpx.HTTPError as e:
            logger.warning("Backend nie odebrał %d zdarzeń, ponowienie: %s", len(batch), e)
            return _Outcome.RETRY

        status = response.status_code
        if status >= 500 or status in RETRYABLE_STATUSES:
            logger.warning("Backend odpowiedział HTTP %d na partię %d zdarzeń, ponowienie", status, len(batch))
            return _Outcome.RETRY
        if status in (401, 403):
            logger.error(
                "Backend odrzucił X-Hub-Api-Key (HTTP %d): sprawdź HUB_API_KEY po obu stronach. Odrzucono %d zdarzeń",
                status, len(batch),
            )
        elif not response.is_success:
            logger.error("Backend odrzucił partię %d zdarzeń (HTTP %d): %s", len(batch), status, response.text[:500])
        self._acknowledge(batch)
        return _Outcome.DELIVERED

    def _acknowledge(self, batch: list[dict]) -> None:
        # Po identyfikatorach, bo w trakcie wysyłki pełna kolejka mogła już odrzucić początek partii.
        sent = {event["event_id"] for event in batch}
        while self._pending and self._pending[0]["event_id"] in sent:
            self._pending.popleft()
