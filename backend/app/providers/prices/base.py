from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo



# Strefa doby handlowej rynku energii w Polsce - w niej liczymy "dzień" cen i slotów z plików.
MARKET_TIMEZONE = ZoneInfo("Europe/Warsaw")


def local_day_bounds_utc(business_date: date) -> tuple[datetime, datetime]:
    """Początek i koniec doby lokalnej jako momenty UTC (doba trwa 23/24/25 h)."""
    start = datetime.combine(business_date, time(), MARKET_TIMEZONE).astimezone(timezone.utc)
    end = datetime.combine(business_date + timedelta(days=1), time(), MARKET_TIMEZONE).astimezone(timezone.utc)
    return start, end


def expected_intervals(business_date: date, interval_minutes: int = 15) -> int:
    """Liczba interwałów w dobie lokalnej - 92/100 dla kwadransów w dniach zmiany czasu."""
    start, end = local_day_bounds_utc(business_date)
    return int((end - start).total_seconds() // (interval_minutes * 60))


@dataclass(frozen=True)
class PricePoint:
    """Pojedyncza obserwacja ceny energii w ujednoliconym formacie aplikacji."""

    source: str
    interval_start: datetime  # zawsze tz-aware, UTC
    interval_minutes: int
    business_date: date  # doba handlowa w strefie Europe/Warsaw
    price_pln_mwh: Decimal

    def __post_init__(self):
        if self.interval_start.tzinfo is None:
            raise ValueError("interval_start musi zawierać strefę czasową")


class PriceProvider(Protocol):
    """Kontrakt adaptera dostawcy cen dynamicznych.

    Nowe źródło (np. ENTSO-E albo API konkretnego sprzedawcy) to nowa klasa
    implementująca ten protokół - bez zmian w serwisie synchronizacji.
    """

    source: str

    def fetch_day(self, business_date: date) -> list[PricePoint]:
        """Zwraca ceny dla doby handlowej.

        Rzuca PriceDataNotAvailableError, gdy dostawca nie opublikował jeszcze danych,
        oraz PriceProviderError przy błędach komunikacji lub formatu.
        """
        ...


class PriceProviderError(Exception):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class PriceDataNotAvailableError(PriceProviderError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False)
