import httpx
from sqlalchemy.orm import Session

from app.core.locks import PostgresAdvisoryLock
from app.providers.prices.base import PriceProvider
from app.providers.prices.pse_provider import PseRcePriceProvider
from app.providers.prices.retrying_provider import RetryingPriceProvider
from app.repositories.dynamic_price_repository import DynamicPriceRepository
from app.repositories.price_sync_run_repository import PriceSyncRunRepository
from app.services.price_sync_service import PriceSyncService



# Numer pg_advisory_lock - musi być identyczny w API i workerze, żeby wykluczały się nawzajem.
PRICE_SYNC_LOCK_KEY = 0x5A50_0009
HTTP_TIMEOUT_SECONDS = 15.0


def build_http_client() -> httpx.Client:
    return httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, headers={"Accept": "application/json"})


def build_price_provider(http_client: httpx.Client) -> PriceProvider:
    return RetryingPriceProvider(PseRcePriceProvider(http_client))


def build_price_sync_service(db: Session, http_client: httpx.Client) -> PriceSyncService:
    return PriceSyncService(
        provider=build_price_provider(http_client),
        price_repository=DynamicPriceRepository(db),
        run_repository=PriceSyncRunRepository(db),
        lock=PostgresAdvisoryLock(db.get_bind(), PRICE_SYNC_LOCK_KEY),
    )
