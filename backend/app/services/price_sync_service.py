import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from app.core.locks import DistributedLock, LockNotAcquiredError
from app.models.PriceSyncRun import PriceSyncRun, PriceSyncStatus, PriceSyncTrigger
from app.providers.prices.base import (
    MARKET_TIMEZONE,
    PriceDataNotAvailableError,
    PriceProvider,
    PriceProviderError,
    expected_intervals,
)
from app.repositories.dynamic_price_repository import DynamicPriceRepository
from app.repositories.price_sync_run_repository import PriceSyncRunRepository



logger = logging.getLogger(__name__)

MAX_ERROR_MESSAGE_LENGTH = 4000
CATCHUP_DAYS = 7


class SyncAlreadyRunningError(Exception):
    pass


@dataclass(frozen=True)
class PriceSyncStatusSummary:
    source: str
    last_run: PriceSyncRun | None
    last_successful_run: PriceSyncRun | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PriceSyncService:

    def __init__(
        self,
        provider: PriceProvider,
        price_repository: DynamicPriceRepository,
        run_repository: PriceSyncRunRepository,
        lock: DistributedLock,
        clock: Callable[[], datetime] = utc_now,
        catchup_days: int = CATCHUP_DAYS,
    ):
        self.provider = provider
        self.price_repository = price_repository
        self.run_repository = run_repository
        self.lock = lock
        self.clock = clock
        self.catchup_days = catchup_days

    def today(self) -> date:
        return self.clock().astimezone(MARKET_TIMEZONE).date()

    def sync(self, date_from: date | None = None, date_to: date | None = None, trigger: str = PriceSyncTrigger.MANUAL) -> PriceSyncRun:
        """Bez zakresu uzupełnia braki (jak worker), z zakresem pobiera ponownie wskazane doby."""
        if date_from is None and date_to is None:
            return self.sync_missing(trigger=trigger)
        if date_from is None or date_to is None:
            raise ValueError("Podaj oba pola date_from i date_to albo żadne")
        return self.sync_range(date_from, date_to, trigger=trigger)

    def sync_range(self, date_from: date, date_to: date, trigger: str = PriceSyncTrigger.MANUAL) -> PriceSyncRun:
        if date_from > date_to:
            raise ValueError("date_from nie może być późniejsza niż date_to")
        days = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
        return self._run(days, date_from, date_to, trigger)

    def sync_missing(self, trigger: str = PriceSyncTrigger.SCHEDULED) -> PriceSyncRun:
        """Uzupełnia brakujące lub niepełne doby z ostatnich `catchup_days` dni oraz jutro."""
        today = self.today()
        date_from = today - timedelta(days=self.catchup_days)
        date_to = today + timedelta(days=1)

        counts = self.price_repository.count_by_business_date(self.provider.source, date_from, date_to)
        days = [
            day
            for day in (date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1))
            if counts.get(day, 0) < expected_intervals(day)
        ]
        return self._run(days, date_from, date_to, trigger)

    def get_status(self) -> PriceSyncStatusSummary:
        source = self.provider.source
        return PriceSyncStatusSummary(
            source=source,
            last_run=self.run_repository.get_latest(source),
            last_successful_run=self.run_repository.get_latest_with_status(source, PriceSyncStatus.SUCCESS),
        )

    def _run(self, days: list[date], date_from: date, date_to: date, trigger: str) -> PriceSyncRun:
        try:
            with self.lock.acquire():
                return self._run_locked(days, date_from, date_to, trigger)
        except LockNotAcquiredError as e:
            raise SyncAlreadyRunningError("Synchronizacja cen jest już w toku") from e

    def _run_locked(self, days: list[date], date_from: date, date_to: date, trigger: str) -> PriceSyncRun:
        source = self.provider.source
        run = self.run_repository.start(
            source=source,
            trigger=trigger,
            date_from=date_from,
            date_to=date_to,
            days_requested=len(days),
            started_at=self.clock(),
        )
        logger.info("Start synchronizacji cen %s (%s): %d dób do pobrania", source, trigger, len(days))

        days_synced = 0
        records_upserted = 0
        missing_days: list[date] = []
        errors: list[str] = []

        try:
            # Każda doba osobno: brak danych lub błąd dostawcy dla jednej doby nie przerywa
            # pozostałych - trafia do statusu (partial/no_data/failed) i error_message.
            for day in days:
                try:
                    points = self.provider.fetch_day(day)
                except PriceDataNotAvailableError as e:
                    logger.info("Brak danych %s: %s", source, e)
                    missing_days.append(day)
                    continue
                except PriceProviderError as e:
                    logger.error("Błąd dostawcy %s dla %s: %s", source, day, e)
                    errors.append(f"{day.isoformat()}: {e}")
                    continue

                records_upserted += self.price_repository.upsert_many(points)
                days_synced += 1
        except Exception as e:
            logger.exception("Nieoczekiwany błąd synchronizacji cen %s", source)
            self.run_repository.finish(
                run,
                status=PriceSyncStatus.FAILED,
                days_synced=days_synced,
                records_upserted=records_upserted,
                error_message=f"Nieoczekiwany błąd: {e}"[:MAX_ERROR_MESSAGE_LENGTH],
                finished_at=self.clock(),
            )
            raise

        status = self._resolve_status(len(days), days_synced, missing_days, errors)
        error_message = self._build_error_message(missing_days, errors)
        run = self.run_repository.finish(
            run,
            status=status,
            days_synced=days_synced,
            records_upserted=records_upserted,
            error_message=error_message,
            finished_at=self.clock(),
        )
        logger.info(
            "Koniec synchronizacji cen %s: status=%s, doby=%d/%d, rekordy=%d",
            source, status, days_synced, len(days), records_upserted,
        )
        return run

    @staticmethod
    def _resolve_status(days_requested: int, days_synced: int, missing_days: list[date], errors: list[str]) -> str:
        if days_synced == days_requested:
            return PriceSyncStatus.SUCCESS
        if days_synced > 0:
            return PriceSyncStatus.PARTIAL
        if errors:
            return PriceSyncStatus.FAILED
        return PriceSyncStatus.NO_DATA

    @staticmethod
    def _build_error_message(missing_days: list[date], errors: list[str]) -> str | None:
        parts = []
        if errors:
            parts.append("Błędy dostawcy: " + "; ".join(errors))
        if missing_days:
            parts.append("Brak opublikowanych danych dla: " + ", ".join(d.isoformat() for d in missing_days))
        if not parts:
            return None
        return " | ".join(parts)[:MAX_ERROR_MESSAGE_LENGTH]
