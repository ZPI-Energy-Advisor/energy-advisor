from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import pytest

from app.providers.prices.base import PriceDataNotAvailableError, PriceProviderError
from app.providers.prices.pse_provider import PseRcePriceProvider
from app.providers.prices.retrying_provider import RetryingPriceProvider


BASE_URL = "https://pse.test/api"


def _record(period_utc: str, dtime_utc: str, price, business_date="2025-01-01"):
    return {
        "business_date": business_date,
        "period": "lokalny okres - ignorowany",
        "period_utc": period_utc,
        "dtime": "2025-01-01 02a:15:00",  # pole lokalne bywa niejednoznaczne - adapter go nie używa
        "dtime_utc": dtime_utc,
        "rce_pln": price,
    }


def _provider(handler) -> PseRcePriceProvider:
    return PseRcePriceProvider(httpx.Client(transport=httpx.MockTransport(handler)), base_url=BASE_URL)


def test_fetch_day_maps_records_to_utc_price_points():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(200, json={"value": [
            _record("23:00 - 23:15", "2024-12-31 23:15:00", 16.26),
            _record("23:45 - 24:00", "2025-01-01 00:00:00", -5.5),  # PSE zapisuje północ jako 24:00
        ]})

    points = _provider(handler).fetch_day(date(2025, 1, 1))

    assert requests[0].url.params["$filter"] == "business_date eq '2025-01-01'"
    assert [p.interval_start for p in points] == [
        datetime(2024, 12, 31, 23, 0, tzinfo=timezone.utc),
        datetime(2024, 12, 31, 23, 45, tzinfo=timezone.utc),
    ]
    assert points[0].interval_minutes == 15
    assert points[0].business_date == date(2025, 1, 1)
    assert points[0].price_pln_mwh == Decimal("16.26")
    assert points[1].price_pln_mwh == Decimal("-5.5")  # ujemne ceny są poprawne
    assert all(p.source == "pse_rce" for p in points)


def test_fetch_day_follows_next_link():
    def handler(request: httpx.Request):
        if "$after" in str(request.url):
            return httpx.Response(200, json={"value": [_record("00:15 - 00:30", "2025-01-01 00:30:00", 2)]})
        return httpx.Response(200, json={
            "value": [_record("00:00 - 00:15", "2025-01-01 00:15:00", 1)],
            "nextLink": f"{BASE_URL}/rce-pln?$filter=x&$after=cursor",
        })

    points = _provider(handler).fetch_day(date(2025, 1, 1))

    assert [p.price_pln_mwh for p in points] == [Decimal(1), Decimal(2)]


def test_empty_response_means_data_not_available():
    provider = _provider(lambda request: httpx.Response(200, json={"value": []}))

    with pytest.raises(PriceDataNotAvailableError) as exc_info:
        provider.fetch_day(date(2030, 1, 1))
    assert exc_info.value.retryable is False


@pytest.mark.parametrize("status_code, retryable", [(500, True), (503, True), (429, True), (400, False)])
def test_http_errors_are_mapped_to_provider_errors(status_code, retryable):
    provider = _provider(lambda request: httpx.Response(status_code))

    with pytest.raises(PriceProviderError) as exc_info:
        provider.fetch_day(date(2025, 1, 1))
    assert exc_info.value.retryable is retryable


def test_connection_error_is_retryable():
    def handler(request):
        raise httpx.ConnectError("brak sieci")

    with pytest.raises(PriceProviderError) as exc_info:
        _provider(handler).fetch_day(date(2025, 1, 1))
    assert exc_info.value.retryable is True


def test_malformed_record_is_not_retryable():
    provider = _provider(lambda request: httpx.Response(200, json={"value": [{"rce_pln": 1}]}))

    with pytest.raises(PriceProviderError) as exc_info:
        provider.fetch_day(date(2025, 1, 1))
    assert exc_info.value.retryable is False


class _FlakyProvider:
    source = "flaky"

    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def fetch_day(self, business_date):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return ["ok"]


def test_retrying_provider_retries_with_backoff_until_success():
    inner = _FlakyProvider([PriceProviderError("503"), PriceProviderError("timeout")])
    delays = []

    result = RetryingPriceProvider(inner, max_attempts=3, base_delay_seconds=2, sleep=delays.append).fetch_day(date(2025, 1, 1))

    assert result == ["ok"]
    assert inner.calls == 3
    assert delays == [2, 4]


def test_retrying_provider_gives_up_after_max_attempts():
    inner = _FlakyProvider([PriceProviderError("503")] * 5)

    with pytest.raises(PriceProviderError):
        RetryingPriceProvider(inner, max_attempts=3, sleep=lambda _: None).fetch_day(date(2025, 1, 1))
    assert inner.calls == 3


@pytest.mark.parametrize("error", [PriceDataNotAvailableError("brak"), PriceProviderError("400", retryable=False)])
def test_retrying_provider_does_not_retry_non_retryable_errors(error):
    inner = _FlakyProvider([error])

    with pytest.raises(PriceProviderError):
        RetryingPriceProvider(inner, max_attempts=3, sleep=lambda _: None).fetch_day(date(2025, 1, 1))
    assert inner.calls == 1
