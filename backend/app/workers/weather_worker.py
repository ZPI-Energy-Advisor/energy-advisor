import argparse
import logging
import sys
from datetime import datetime, timezone

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.locks import LockNotAcquiredError, PostgresAdvisoryLock
from app.core.logging_config import configure_logging
from app.database import SessionLocal, engine
from app.providers.prices.base import MARKET_TIMEZONE
from app.services import weather_sync
from app.workers.price_sync_worker import wait_for_database

logger = logging.getLogger("weather_worker")

WEATHER_LOCK_KEY = 0x5A50_0117
FORECAST_HOURS = "*/3"
FORECAST_MINUTE = 20
HISTORY_HOURS = "2,14"
HISTORY_MINUTE = 40
PRUNE_HOUR = 3
PRUNE_MINUTE = 50


def _run(name: str, job) -> None:
    db = SessionLocal()
    try:
        with PostgresAdvisoryLock(engine, WEATHER_LOCK_KEY).acquire():
            result = job(db)
        logger.info("%s: komórki=%d, rekordy=%d, błędy=%d", name, result.cells, result.stored, result.failed)
    except LockNotAcquiredError:
        logger.warning("Pominięto %s: inne pobieranie pogody jest w toku", name)
    except Exception:
        logger.exception("%s zakończone błędem", name)
    finally:
        db.close()


def run_forecasts() -> None:
    _run("Prognoza pogody", weather_sync.refresh_forecasts)


def run_history() -> None:
    _run("Historia pogody", weather_sync.sync_history)


def run_prune() -> None:
    _run("Usuwanie starych prognoz", weather_sync.prune)


def run_startup() -> None:
    if wait_for_database(table="weather_observations"):
        run_forecasts()
        run_history()
        run_prune()
    else:
        logger.error("Pomijam pobieranie startowe: nadrobi je najbliższe zaplanowane uruchomienie")


def run_scheduler() -> None:
    scheduler = BlockingScheduler(timezone=MARKET_TIMEZONE, executors={"default": ThreadPoolExecutor(1)})
    options = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 3600}
    scheduler.add_job(
        run_forecasts,
        CronTrigger(hour=FORECAST_HOURS, minute=FORECAST_MINUTE, timezone=MARKET_TIMEZONE),
        id="weather_forecast",
        **options,
    )
    scheduler.add_job(
        run_history,
        CronTrigger(hour=HISTORY_HOURS, minute=HISTORY_MINUTE, timezone=MARKET_TIMEZONE),
        id="weather_history",
        **options,
    )
    scheduler.add_job(
        run_prune,
        CronTrigger(hour=PRUNE_HOUR, minute=PRUNE_MINUTE, timezone=MARKET_TIMEZONE),
        id="weather_prune",
        **options,
    )
    scheduler.add_job(
        run_startup, "date", run_date=datetime.now(timezone.utc), id="weather_startup", misfire_grace_time=None
    )
    logger.info("Worker pogody uruchomiony: prognoza co 3 h, historia o %s:%02d", HISTORY_HOURS, HISTORY_MINUTE)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker pogody zatrzymany")


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Pobieranie pogody z Open-Meteo")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="uruchom harmonogram (domyślne)")
    subparsers.add_parser("forecast", help="jednorazowo odśwież prognozę")
    subparsers.add_parser("history", help="jednorazowo uzupełnij historię dla plików")
    args = parser.parse_args(argv)
    if args.command == "forecast":
        run_forecasts()
    elif args.command == "history":
        run_history()
    else:
        run_scheduler()
    return 0


if __name__ == "__main__":
    sys.exit(main())
