from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.providers.prices.base import PriceProviderError
from app.providers.prices.pse_rcem_provider import PseRcemProvider, parse_rcem_page

PAGE = """
<table>
  <tr><th>2025</th></tr>
  <tr><td colspan="3">grudzień</td></tr>
  <tr><td>RCEm</td><td>466,08</td><td>12.01.2026</td></tr>
  <tr><td>skorygowana RCEm*</td><td>-</td><td>-</td></tr>
  <tr><th>2026</th></tr>
  <tr><td colspan="3">styczeń</td></tr>
  <tr><td>RCEm</td><td>550,00</td><td>10.02.2026</td></tr>
  <tr><td>skorygowana RCEm*</td><td>551,96</td><td>11.02.2026</td></tr>
</table>
"""


def test_parse_takes_correction_over_first_publication():
    rows = {row["price_month"]: row for row in parse_rcem_page(PAGE, "pse_rcem")}

    assert rows[date(2025, 12, 1)]["price_pln_mwh"] == Decimal("466.08")
    assert rows[date(2026, 1, 1)]["price_pln_mwh"] == Decimal("551.96")
    assert rows[date(2026, 1, 1)]["published_at"].date() == date(2026, 2, 11)
    assert {row["source"] for row in rows.values()} == {"pse_rcem"}


def test_page_without_prices_is_an_error():
    with pytest.raises(PriceProviderError):
        parse_rcem_page("<html><body>Strona w przebudowie</body></html>", "pse_rcem")


def test_fetch_reads_pse_page():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=PAGE))

    rows = PseRcemProvider(httpx.Client(transport=transport)).fetch()

    assert len(rows) == 2


def test_fetch_http_error_is_provider_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(503, text="niedostępne"))

    with pytest.raises(PriceProviderError):
        PseRcemProvider(httpx.Client(transport=transport)).fetch()
