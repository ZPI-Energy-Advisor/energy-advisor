from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.schemas.other import TypeOfMarketEnergyEnum
from app.services.new_calculations_service import CalculationsService
from app.services.pv_service import DynamicMarketPriceResolver


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class _PriceRepository:
    """Ceny RCE dla każdego kwadransa żądanego zakresu [start, koniec), różne w każdym kwadransie:
    cena w zł/MWh to godzina i minuta UTC (HHMM), np. 11:15 UTC → 1115 zł/MWh."""

    def __init__(self, prices=True):
        self.prices = prices
        self.requested = []

    def get_prices_between(self, source, start_utc, end_utc):
        self.requested.append((start_utc, end_utc))
        prices, moment = {}, start_utc.astimezone(timezone.utc)
        while self.prices and moment < end_utc:
            prices[moment] = Decimal(moment.hour * 100 + moment.minute)
            moment += timedelta(minutes=15)
        return prices


def test_pv_rce_price_treats_reading_time_as_local():
    repository = _PriceRepository()

    price = DynamicMarketPriceResolver(repository)(datetime(2026, 1, 15, 12, 0), TypeOfMarketEnergyEnum.RCE)

    # 12:00 czasu zimowego (CET) to 11:00 UTC
    assert price == pytest.approx(1.1)
    # ceny wczytane za cały lokalny styczeń: od 1.01 00:00 CET do 1.02 00:00 CET
    assert repository.requested == [(_utc(2025, 12, 31, 23, 0), _utc(2026, 1, 31, 23, 0))]


def test_dynamic_tariff_price_treats_reading_time_as_local():
    repository = _PriceRepository()
    service = CalculationsService(None, None, None, None, market_price_repository=repository)

    price = service.tariff_engine.dynamic_price_resolver(datetime(2026, 7, 15, 12, 15))

    # 12:15 czasu letniego (CEST) to 10:15 UTC
    assert price == pytest.approx(1.015)
    assert repository.requested == [(_utc(2026, 6, 30, 22, 0), _utc(2026, 7, 31, 22, 0))]


def test_rce_prices_are_loaded_once_per_local_month():
    repository = _PriceRepository()
    resolver = DynamicMarketPriceResolver(repository)

    january = [resolver.rce(moment) for moment in (datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 31, 23, 45))]
    # 1.02 00:00 czasu lokalnego to jeszcze 31.01 23:00 UTC, ale cenę bierzemy z cen lutego
    february = resolver.rce(datetime(2026, 2, 1, 0, 0))

    assert january == [pytest.approx(2.3), pytest.approx(2.245)]  # 23:00 i 22:45 UTC
    assert february == pytest.approx(2.3)
    assert repository.requested == [
        (_utc(2025, 12, 31, 23, 0), _utc(2026, 1, 31, 23, 0)),
        (_utc(2026, 1, 31, 23, 0), _utc(2026, 2, 28, 23, 0)),
    ]


def test_rce_on_dst_change_days_uses_utc_interval_of_local_quarter():
    resolver = DynamicMarketPriceResolver(_PriceRepository())

    # 30.03.2025: po 01:45 CET (00:45 UTC) następuje 03:00 CEST (01:00 UTC)
    assert resolver.rce(datetime(2025, 3, 30, 1, 45)) == pytest.approx(0.045)
    assert resolver.rce(datetime(2025, 3, 30, 3, 0)) == pytest.approx(0.1)
    # 26.10.2025: kwadrans 02:15 (oba wystąpienia zsumowane przy imporcie) wyceniamy ceną pierwszego
    # wystąpienia — 00:15 UTC, a nie 01:15 UTC; 03:00 CET to 02:00 UTC
    assert resolver.rce(datetime(2025, 10, 26, 2, 15)) == pytest.approx(0.015)
    assert resolver.rce(datetime(2025, 10, 26, 3, 0)) == pytest.approx(0.2)


def test_missing_rce_price_names_the_interval():
    resolver = DynamicMarketPriceResolver(_PriceRepository(prices=False))

    with pytest.raises(ValueError, match="Brak ceny RCE dla interwału 2026-01-15T12:00:00"):
        resolver.rce(datetime(2026, 1, 15, 12, 0))

