from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

from app.providers.prices.base import (
    PriceDataNotAvailableError,
    PricePoint,
    PriceProviderError,
)


class PseRcePriceProvider:
    """Adapter API raportowego PSE - Rynkowa Cena Energii (RCE) w PLN/MWh.

    Opis źródła i formatu: docs/dynamic-prices.md
    """

    source = "pse_rce"

    DEFAULT_BASE_URL = "https://api.raporty.pse.pl/api"
    MAX_PAGES = 20

    def __init__(self, client: httpx.Client, base_url: str = DEFAULT_BASE_URL):
        self.client = client
        self.base_url = base_url.rstrip("/")

    def fetch_day(self, business_date: date) -> list[PricePoint]:
        records = self._fetch_all_records(business_date)
        if not records:
            raise PriceDataNotAvailableError(
                f"PSE nie opublikowało jeszcze cen RCE dla {business_date.isoformat()}"
            )
        return [self._to_price_point(record) for record in records]

    def _fetch_all_records(self, business_date: date) -> list[dict]:
        url = f"{self.base_url}/rce-pln"
        params = {"$filter": f"business_date eq '{business_date.isoformat()}'"}
        records: list[dict] = []

        for _ in range(self.MAX_PAGES):
            payload = self._get_json(url, params)
            records.extend(payload.get("value") or [])

            next_link = payload.get("nextLink")
            if not next_link:
                return records
            # nextLink zawiera już pełny URL razem z filtrem i kursorem.
            url, params = next_link, None

        raise PriceProviderError(
            f"Przekroczono limit {self.MAX_PAGES} stron odpowiedzi PSE", retryable=False
        )

    def _get_json(self, url: str, params: dict | None) -> dict:
        try:
            response = self.client.get(url, params=params)
        except httpx.HTTPError as e:
            raise PriceProviderError(f"Błąd połączenia z API PSE: {e}") from e

        if response.status_code >= 500 or response.status_code == 429:
            raise PriceProviderError(f"API PSE zwróciło HTTP {response.status_code}")
        if response.status_code >= 400:
            raise PriceProviderError(
                f"API PSE odrzuciło zapytanie: HTTP {response.status_code}", retryable=False
            )

        try:
            payload = response.json()
        except ValueError as e:
            raise PriceProviderError("API PSE zwróciło niepoprawny JSON", retryable=False) from e

        if not isinstance(payload, dict):
            raise PriceProviderError("Nieoczekiwany format odpowiedzi API PSE", retryable=False)
        return payload

    def _to_price_point(self, record: dict) -> PricePoint:
        # Używamy wyłącznie pól UTC - pola lokalne w dniu zmiany czasu
        # zawierają godziny typu "02a:15", których nie da się jednoznacznie sparsować.
        try:
            interval_minutes = self._interval_minutes(record["period_utc"])
            interval_end = datetime.strptime(record["dtime_utc"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
            return PricePoint(
                source=self.source,
                interval_start=interval_end - timedelta(minutes=interval_minutes),
                interval_minutes=interval_minutes,
                business_date=date.fromisoformat(record["business_date"]),
                price_pln_mwh=Decimal(str(record["rce_pln"])),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as e:
            raise PriceProviderError(
                f"Nieprawidłowy rekord w odpowiedzi PSE: {record!r}", retryable=False
            ) from e

    @staticmethod
    def _interval_minutes(period: str) -> int:
        # PSE zapisuje północ jako "24:00" (np. "23:45 - 24:00"), czego nie akceptuje strptime.
        def to_minutes(value: str) -> int:
            hours, minutes = value.strip().split(":")
            total = int(hours) * 60 + int(minutes)
            if not 0 <= total <= 24 * 60:
                raise ValueError(f"Nieprawidłowa godzina: {value}")
            return total

        start_str, end_str = period.split("-")
        minutes = (to_minutes(end_str) - to_minutes(start_str)) % (24 * 60)
        if minutes <= 0:
            raise ValueError(f"Nieprawidłowy okres: {period}")
        return minutes
