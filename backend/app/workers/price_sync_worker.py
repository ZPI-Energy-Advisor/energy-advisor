import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.price_sync_factory import build_http_client, build_price_sync_service
from app.database import SessionLocal, engine
from app.models.PriceSyncRun import PriceSyncTrigger
from app.providers.prices.base import MARKET_TIMEZONE
from app.services.price_sync_service import SyncAlreadyRunningError



# Stała nazwa zamiast __name__: uruchamiany przez `python -m` moduł ma __name__ == "__main__".
logger = logging.getLogger("price_sync_worker")

BACKFILL_CHUNK_DAYS = 31
# PSE publikuje ceny na jutro ok. 13:45 - o 15:00 są już dostępne.
SYNC_HOUR = 15
SYNC_MINUTE = 0


def wait_for_database(timeout_seconds: float = 300, interval_seconds: float = 5, sleep=time.sleep) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM price_sync_runs LIMIT 1"))
            return True
        except OperationalError as e:
            reason = f"baza niedostępna ({e.orig})"
        except ProgrammingError:
            reason = "brak tabel - uruchom `alembic upgrade head`"

        if time.monotonic() >= deadline:
            logger.error("Baza nie jest gotowa po %.0fs: %s", timeout_seconds, reason)
            return False
        logger.warning("Czekam na bazę: %s. Ponowię za %.0fs", reason, interval_seconds)
        sleep(interval_seconds)


def run_startup_sync() -> None:
    if wait_for_database():
        run_sync_missing()
    else:
        logger.error("Pomijam synchronizację startową - nadrobi ją najbliższe zaplanowane uruchomienie")


def run_sync_missing(trigger: str = PriceSyncTrigger.SCHEDULED) -> None:
    db = SessionLocal()
    http_client = build_http_client()
    try:
        service = build_price_sync_service(db, http_client)
        run = service.sync_missing(trigger=trigger)
        logger.info("Synchronizacja zakończona: status=%s, rekordy=%d", run.status, run.records_upserted)
    except SyncAlreadyRunningError:
        logger.warning("Pominięto - synchronizacja cen jest już w toku")
    except Exception:
        # Celowo bez raise: jeden nieudany przebieg nie może zatrzymać schedulera.
        # Błąd jest w logu, a serwis zapisał go też w price_sync_runs (status failed).
        logger.exception("Synchronizacja cen zakończona błędem")
    finally:
        http_client.close()
        db.close()


def split_into_chunks(date_from: date, date_to: date, chunk_days: int) -> list[tuple[date, date]]:
    """Dzieli zakres [date_from, date_to] na kolejne paczki po maksymalnie chunk_days dni (oba końce włącznie)."""
    chunks = []
    chunk_start = date_from
    while chunk_start <= date_to:
        chunk_end = min(chunk_start + timedelta(days=chunk_days - 1), date_to)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return chunks


def run_backfill(date_from: date, date_to: date) -> None:
    db = SessionLocal()
    http_client = build_http_client()
    try:
        service = build_price_sync_service(db, http_client)
        # Paczki po miesiącu: osobny wpis w price_sync_runs dla każdej, widać postęp i która się nie udała.
        for chunk_start, chunk_end in split_into_chunks(date_from, date_to, BACKFILL_CHUNK_DAYS):
            run = service.sync_range(chunk_start, chunk_end, trigger=PriceSyncTrigger.CLI)
            logger.info("Backfill %s..%s: status=%s, rekordy=%d", chunk_start, chunk_end, run.status, run.records_upserted)
    finally:
        http_client.close()
        db.close()


def run_scheduler() -> None:
    scheduler = BlockingScheduler(timezone=MARKET_TIMEZONE)
    scheduler.add_job(
        run_sync_missing,
        CronTrigger(hour=SYNC_HOUR, minute=SYNC_MINUTE, timezone=MARKET_TIMEZONE),
        id="price_sync_daily",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        run_startup_sync,
        "date",
        run_date=datetime.now(timezone.utc),
        id="price_sync_startup",
    )
    logger.info(
        "Worker cen uruchomiony - codziennie o %02d:%02d (%s)",
        SYNC_HOUR, SYNC_MINUTE, MARKET_TIMEZONE.key,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker cen zatrzymany")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Synchronizacja cen dynamicznych")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="uruchom harmonogram (domyślne)")
    subparsers.add_parser("once", help="jednorazowo uzupełnij brakujące doby")
    backfill = subparsers.add_parser("backfill", help="pobierz ponownie zakres dat")
    backfill.add_argument("date_from", type=date.fromisoformat)
    backfill.add_argument("date_to", type=date.fromisoformat)
    args = parser.parse_args(argv)

    if args.command == "once":
        run_sync_missing(trigger=PriceSyncTrigger.CLI)
    elif args.command == "backfill":
        if args.date_from > args.date_to:
            parser.error("date_from nie może być późniejsza niż date_to")
        run_backfill(args.date_from, args.date_to)
    else:
        run_scheduler()
    return 0


if __name__ == "__main__":
    sys.exit(main())
