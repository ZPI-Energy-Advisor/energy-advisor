"""Ceny RCEm (rynkowa miesięczna cena energii) ze strony PSE — nie ma ich w API raportów.

Strona ma jedną tabelę: wiersz z rokiem, wiersz z nazwą miesiąca, wiersz „RCEm” (cena, data publikacji)
i wiersze „skorygowana RCEm” z późniejszymi korektami. Dla miesiąca bierzemy ostatnią podaną wartość.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

import httpx

from app.providers.prices.base import MARKET_TIMEZONE, PriceProviderError

RCEM_URL = "https://www.pse.pl/oire/rcem-rynkowa-miesieczna-cena-energii-elektrycznej"
MONTHS = {
    "styczeń": 1, "luty": 2, "marzec": 3, "kwiecień": 4, "maj": 5, "czerwiec": 6,
    "lipiec": 7, "sierpień": 8, "wrzesień": 9, "październik": 10, "listopad": 11, "grudzień": 12,
}


class _TableRows(HTMLParser):
    """Teksty komórek każdego wiersza tabel na stronie."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _price(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


def _published(text: str) -> datetime | None:
    try:
        day = datetime.strptime(text.strip(), "%d.%m.%Y")
    except ValueError:
        return None
    return day.replace(tzinfo=MARKET_TIMEZONE)


def parse_rcem_page(html: str, source: str) -> list[dict]:
    parser = _TableRows()
    parser.feed(html)
    year = month = None
    values: dict[date, tuple[Decimal, datetime | None]] = {}
    for cells in parser.rows:
        first = cells[0].replace("*", "").strip().lower() if cells else ""
        if len(cells) == 1 and first.isdigit() and len(first) == 4:
            year, month = int(first), None
        elif len(cells) == 1 and first in MONTHS:
            month = MONTHS[first]
        elif year and month and len(cells) >= 3 and first in ("rcem", "skorygowana rcem"):
            price = _price(cells[1])
            if price is not None:
                # Korekta jest w wierszu pod ceną pierwotną, więc nadpisuje ją.
                values[date(year, month, 1)] = (price, _published(cells[2]))
    if not values:
        raise PriceProviderError("Na stronie PSE nie ma tabeli z cenami RCEm", retryable=False)
    return [
        {"source": source, "price_month": month_start, "price_pln_mwh": price, "published_at": published}
        for month_start, (price, published) in sorted(values.items())
    ]


class PseRcemProvider:
    source = "pse_rcem"

    def __init__(self, http_client: httpx.Client):
        self.http_client = http_client

    def fetch(self) -> list[dict]:
        try:
            response = self.http_client.get(RCEM_URL, headers={"Accept": "text/html"})
        except httpx.HTTPError as error:
            raise PriceProviderError(f"Brak odpowiedzi strony PSE z RCEm: {error}") from error
        if response.status_code != 200:
            raise PriceProviderError(f"Strona PSE z RCEm zwróciła HTTP {response.status_code}")
        return parse_rcem_page(response.text, self.source)
