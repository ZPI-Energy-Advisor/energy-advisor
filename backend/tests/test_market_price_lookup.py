from datetime import datetime, timezone
from decimal import Decimal

from app.schemas.other import TypeOfMarketEnergyEnum
from app.services.new_calculations_service import CalculationsService
from app.services.pv_service import DynamicMarketPriceResolver


class _PriceRepository:
    def __init__(self):
        self.requested = []

    def get_prices_between(self, source, start_utc, end_utc):
        self.requested.append((start_utc, end_utc))
        return {start_utc: Decimal("400")}


def _requested_utc(repository):
    start, end = repository.requested[0]
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def test_pv_rce_price_treats_reading_time_as_local():
    repository = _PriceRepository()

    price = DynamicMarketPriceResolver(repository)(datetime(2026, 1, 15, 12, 0), TypeOfMarketEnergyEnum.RCE)

    assert price == 0.4
    assert _requested_utc(repository) == (
        datetime(2026, 1, 15, 11, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 15, 11, 15, tzinfo=timezone.utc),
    )


def test_dynamic_tariff_price_treats_reading_time_as_local():
    repository = _PriceRepository()
    service = CalculationsService(None, None, None, None, market_price_repository=repository)

    price = service.tariff_engine.dynamic_price_resolver(datetime(2026, 7, 15, 12, 0))

    assert price == 0.4
    assert _requested_utc(repository)[0] == datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
