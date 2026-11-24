"""Okna cenowe na jutro: wyznaczanie okien (remis, ceny ujemne, płaskie ceny, doba 92/100 kwadransów) i endpoint."""

from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.api.v1.deps import get_authenticated_user, get_price_insights_service
from app.providers.prices.base import local_day_bounds_utc
from app.schemas.dynamic_price import parse_insights_window
from app.services.price_insights import (
    PriceInsightsService,
    difference_percent,
    find_price_windows,
    is_flat,
)
from app.services.schedule_prices import SLOT, NoTariffRatesError, SchedulePrices
from main import app

WARSAW = ZoneInfo("Europe/Warsaw")
DAY = date(2026, 11, 17)
URL = "/api/v1/dynamic-prices/tomorrow/insights"


def _local(hour, minute=0, day=DAY):
    return datetime.combine(day, time(hour, minute), WARSAW)


def _day_prices(price=lambda local: 1.0, day=DAY):
    """Ceny wszystkich kwadransów doby lokalnej; `price` dostaje lokalny początek kwadransa."""
    start, end = local_day_bounds_utc(day)
    prices = {}
    while start < end:
        prices[start] = price(start.astimezone(WARSAW))
        start += SLOT
    return prices


def _between(first_hour, last_hour, inside, outside=1.0):
    return lambda local: inside if first_hour <= local.hour < last_hour else outside


# --- wyznaczanie okien ---


def test_cheapest_and_most_expensive_window_move_in_quarter_hour_steps():
    def price(local):
        if (local.hour, local.minute) >= (12, 15) and (local.hour, local.minute) < (14, 15):
            return 0.2
        return 2.0 if 18 <= local.hour < 20 else 1.0

    cheapest, most_expensive = find_price_windows(_day_prices(price), 8)

    assert (cheapest.start, cheapest.end) == (_local(12, 15), _local(14, 15))
    assert cheapest.average_price == pytest.approx(0.2)
    assert (most_expensive.start, most_expensive.end) == (_local(18), _local(20))
    assert most_expensive.average_price == pytest.approx(2.0)


def test_tie_is_resolved_in_favour_of_the_earlier_window():
    def price(local):
        if local.hour in (3, 4, 13, 14):
            return 0.3
        return 1.5 if local.hour in (7, 8, 19, 20) else 1.0

    cheapest, most_expensive = find_price_windows(_day_prices(price), 8)

    assert cheapest.start == _local(3)
    assert most_expensive.start == _local(7)


def test_tie_ignores_float_rounding_noise():
    # 0.1 + 0.2 != 0.3 we floatach: późniejsze okno nie może wygrać o błąd zaokrąglenia.
    prices = _day_prices(lambda local: 1.0)
    first, second = _local(2).astimezone(timezone.utc), _local(10).astimezone(timezone.utc)
    prices[first], prices[first + SLOT] = 0.1 + 0.2, 0.3
    prices[second], prices[second + SLOT] = 0.3, 0.3 - 1e-12

    cheapest, _ = find_price_windows(prices, 2)

    assert cheapest.start == _local(2)


def test_negative_prices_are_ordered_like_any_other_price():
    def price(local):
        if 12 <= local.hour < 14:
            return -0.25
        return -0.05 if local.hour < 6 else 0.4

    prices = _day_prices(price)
    cheapest, most_expensive = find_price_windows(prices, 8)

    assert cheapest.start == _local(12)
    assert cheapest.average_price == pytest.approx(-0.25)
    assert most_expensive.start == _local(6)
    assert most_expensive.average_price == pytest.approx(0.4)


def test_difference_percent_keeps_its_sign_with_negative_or_zero_daily_average():
    assert difference_percent(0.5, 1.0) == -50.0
    assert difference_percent(1.25, 1.0) == 25.0
    # Średnia ujemna: tańsze okno nadal na minusie, droższe na plusie.
    assert difference_percent(-0.3, -0.2) == -50.0
    assert difference_percent(0.1, -0.2) == 150.0
    assert difference_percent(0.1, 0.0) is None


def test_flat_prices_give_the_first_window_and_are_flagged_below_threshold():
    prices = _day_prices(lambda local: 0.8)
    cheapest, most_expensive = find_price_windows(prices, 8)

    assert cheapest.start == most_expensive.start == _local(0)
    assert is_flat(prices, 0.05)
    assert is_flat(_day_prices(_between(12, 14, 0.76, 0.8)), 0.05)
    assert not is_flat(_day_prices(_between(12, 14, 0.75, 0.8)), 0.05)


def test_window_does_not_span_a_gap_in_prices():
    prices = _day_prices(_between(12, 14, 0.1))
    del prices[_local(13).astimezone(timezone.utc)]

    cheapest, _ = find_price_windows(prices, 8)

    assert cheapest.average_price > 0.1
    assert find_price_windows({_local(0).astimezone(timezone.utc): 1.0}, 8) is None


@pytest.mark.parametrize(("day", "slots"), [(date(2026, 3, 29), 92), (date(2026, 10, 25), 100)])
def test_day_of_time_change_has_windows_of_real_duration(day, slots):
    # Tanio 01:00–04:00 czasu lokalnego: wiosną to 2 h zegarowe (02:00 nie istnieje), jesienią 4 h (02:00 dwa razy).
    prices = _day_prices(_between(1, 4, 0.1), day)
    assert len(prices) == slots

    cheapest, _ = find_price_windows(prices, 8)

    assert cheapest.start == _local(1, day=day)
    assert cheapest.end - cheapest.start == timedelta(hours=2)
    assert cheapest.average_price == pytest.approx(0.1)
    assert cheapest.end.astimezone(WARSAW).hour == (4 if slots == 92 else 2)


# --- serwis ---


class _Prices:
    def __init__(self, prices, profile_dynamic=True, missing_rates=(), error=None):
        self.prices, self.profile_dynamic, self.calls = prices, profile_dynamic, []
        self.missing_rates, self.error = tuple(missing_rates), error

    def for_user(self, user_id, start_utc, end_utc, as_dynamic=False):
        self.calls.append((user_id, start_utc, end_utc, as_dynamic))
        if self.error is not None:
            raise self.error
        return SchedulePrices(
            prices=self.prices, description="TAURON, G11 z ceną dynamiczną", dynamic=True,
            dynamic_instead_of_profile=not self.profile_dynamic, missing_rates=self.missing_rates,
        )


def _service(prices, profile_dynamic=True, today=DAY - timedelta(days=1), **source_options):
    source = _Prices(prices, profile_dynamic, **source_options)
    service = PriceInsightsService(
        source, flat_spread_pln_kwh=0.05, publication_time=time(15, 0), now=lambda: datetime.combine(today, time(9), WARSAW)
    )
    return service, source


def test_insights_use_schedule_prices_of_tomorrow_for_the_user():
    service, source = _service(_day_prices(_between(12, 14, 0.5)))

    result = service.tomorrow("user-id", 120)

    # as_dynamic: ceny oferty dynamicznej także dla klienta ze zwykłą taryfą.
    assert source.calls == [("user-id", *local_day_bounds_utc(DAY), True)]
    assert result.status == "available"
    assert (result.tariff, result.profile_dynamic) == ("TAURON, G11 z ceną dynamiczną", True)
    assert (result.business_date, result.timezone, result.window_minutes) == (DAY, "Europe/Warsaw", 120)
    assert (result.intervals, result.expected_intervals) == (96, 96)
    assert result.average_price_pln_kwh == pytest.approx((88 * 1.0 + 8 * 0.5) / 96, abs=1e-5)
    assert result.flat_prices is False
    assert result.cheapest.start.isoformat() == "2026-11-17T12:00:00+01:00"
    assert result.cheapest.end.isoformat() == "2026-11-17T14:00:00+01:00"
    assert result.cheapest.average_price_pln_kwh == 0.5
    assert result.cheapest.difference_percent == pytest.approx(-47.8)
    assert result.most_expensive.start == _local(0)
    assert result.most_expensive.difference_percent == pytest.approx(4.3)
    assert result.expected_publication_at is None


def test_flat_day_is_flagged_and_still_has_windows():
    service, _ = _service(_day_prices(lambda local: 0.8))

    result = service.tomorrow("user-id", 120)

    assert result.flat_prices is True
    assert result.cheapest.difference_percent == 0
    assert result.cheapest.start == result.most_expensive.start == _local(0)


@pytest.mark.parametrize(("day", "slots"), [(date(2026, 3, 29), 92), (date(2026, 10, 25), 100)])
def test_day_of_time_change_is_complete_with_92_or_100_quarters(day, slots):
    service, _ = _service(_day_prices(_between(12, 14, -0.1), day), today=day - timedelta(days=1))

    result = service.tomorrow("user-id", 120)

    assert result.status == "available"
    assert (result.intervals, result.expected_intervals) == (slots, slots)
    assert result.cheapest.start == _local(12, day=day)
    assert result.cheapest.average_price_pln_kwh == -0.1
    assert result.cheapest.difference_percent < 0


@pytest.mark.parametrize("missing", ["all", "one"])
def test_missing_dynamic_prices_are_unavailable_with_expected_publication(missing):
    prices = _day_prices()
    if missing == "one":
        del prices[_local(23, 45).astimezone(timezone.utc)]
    else:
        prices = {}
    service, _ = _service(prices)

    result = service.tomorrow("user-id", 120)

    assert result.status == "unavailable"
    assert result.expected_publication_at.isoformat() == "2026-11-16T15:00:00+01:00"
    assert result.intervals == len(prices) and result.expected_intervals == 96
    assert result.cheapest is None and result.most_expensive is None and result.flat_prices is None


def test_missing_tariff_rates_are_not_reported_as_unpublished_prices():
    # Brak okresu opłat od 18:00: tych kwadransów nie uzupełni publikacja RCE, więc nie obiecujemy godziny.
    prices = _day_prices()
    lacking = [slot for slot in prices if slot >= _local(18).astimezone(timezone.utc)]
    for slot in lacking:
        del prices[slot]
    service, _ = _service(prices, missing_rates=lacking)

    result = service.tomorrow("user-id", 120)

    assert result.status == "no_tariff_data"
    assert result.tariff == "TAURON, G11 z ceną dynamiczną"
    assert (result.intervals, result.expected_intervals) == (72, 96)
    assert result.expected_publication_at is None
    assert result.cheapest is None and result.most_expensive is None and result.flat_prices is None


def test_missing_rates_outside_tomorrow_do_not_matter():
    service, _ = _service(_day_prices(), missing_rates=[_local(12, day=DAY + timedelta(days=1)).astimezone(timezone.utc)])

    assert service.tomorrow("user-id", 120).status == "available"


@pytest.mark.parametrize("profile_dynamic", [True, False])
def test_operator_without_tariff_definition_for_tomorrow_has_no_tariff_data(profile_dynamic):
    error = NoTariffRatesError(
        description="ENEA, G11 z ceną dynamiczną", detail="Brak stawek…", dynamic_instead_of_profile=not profile_dynamic
    )
    service, _ = _service({}, error=error)

    result = service.tomorrow("user-id", 120)

    assert result.status == "no_tariff_data"
    assert (result.tariff, result.profile_dynamic) == ("ENEA, G11 z ceną dynamiczną", profile_dynamic)
    assert (result.intervals, result.expected_intervals) == (0, 96)
    assert result.expected_publication_at is None


def test_user_with_regular_tariff_gets_dynamic_offer_prices_marked_as_not_own():
    service, _ = _service(_day_prices(_between(12, 14, 0.5)), profile_dynamic=False)

    result = service.tomorrow("user-id", 120)

    assert result.status == "available"
    assert result.profile_dynamic is False
    assert result.cheapest.start == _local(12)


# --- endpoint ---


def test_window_parameter_accepts_hours_and_minutes_in_quarter_hour_steps():
    assert [parse_insights_window(value) for value in ("2h", "90min", "15min", "12h")] == [120, 90, 15, 720]
    for value in ("20min", "13h", "721min"):
        with pytest.raises(ValueError):
            parse_insights_window(value)


def test_insights_require_token():
    assert TestClient(app).get(URL).status_code == 401
    assert TestClient(app).get(URL, headers={"Authorization": "Bearer nie-token"}).status_code == 401


@pytest.fixture
def client():
    service, source = _service(_day_prices(_between(12, 14, 0.5)))
    app.dependency_overrides[get_authenticated_user] = lambda: SimpleNamespace(id="user-id")
    app.dependency_overrides[get_price_insights_service] = lambda: service
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_insights_endpoint_returns_windows_for_default_and_given_window(client):
    body = client.get(URL).json()

    assert body["status"] == "available"
    assert body["window_minutes"] == 120
    assert body["unit"] == "PLN/kWh"
    assert body["flat_prices"] is False
    assert body["cheapest"] == {
        "start": "2026-11-17T12:00:00+01:00", "end": "2026-11-17T14:00:00+01:00",
        "average_price_pln_kwh": 0.5, "difference_percent": -47.8,
    }

    shorter = client.get(URL, params={"window": "30min"}).json()
    assert shorter["window_minutes"] == 30
    assert shorter["cheapest"]["end"] == "2026-11-17T12:30:00+01:00"


@pytest.mark.parametrize("window", ["20min", "13h", "0h", "2", "2 h", "abc", "-2h"])
def test_insights_endpoint_rejects_invalid_window(client, window):
    assert client.get(URL, params={"window": window}).status_code == 422


# --- reszta dzisiejszej doby (zanim są ceny na jutro) ---


def _today_service(prices, hour, minute=0):
    source = _Prices(prices)
    service = PriceInsightsService(
        source, flat_spread_pln_kwh=0.05, publication_time=time(15, 0),
        now=lambda: datetime.combine(DAY, time(hour, minute), WARSAW),
    )
    return service, source


def test_today_windows_skip_the_part_of_the_day_that_has_passed():
    # Najtaniej było 3:00–5:00, ale jest już 9:10: zostaje najtańsze okno do końca doby (12:00–14:00).
    prices = _day_prices(lambda local: 0.1 if 3 <= local.hour < 5 else 0.5 if 12 <= local.hour < 14 else 1.0)
    service, source = _today_service(prices, 9, 10)

    result = service.today("user-id", 120)

    assert source.calls == [("user-id", *local_day_bounds_utc(DAY), True)]
    assert (result.status, result.business_date) == ("available", DAY)
    assert result.cheapest.start == _local(12)
    # Średnia doby (do procentów) z całej doby, także z minionych godzin.
    assert result.average_price_pln_kwh == pytest.approx((8 * 0.1 + 8 * 0.5 + 80 * 1.0) / 96, abs=1e-5)
    assert result.expected_publication_at is None


def test_today_window_starts_at_the_next_full_quarter():
    prices = _day_prices(lambda local: 0.2 if local.hour >= 22 else 1.0)
    service, _ = _today_service(prices, 21, 45)

    result = service.today("user-id", 120)

    assert result.cheapest.start == _local(22)
    assert result.most_expensive.start == _local(21, 45)


def test_today_late_evening_without_a_whole_window_left_is_unavailable():
    service, _ = _today_service(_day_prices(), 22, 50)

    result = service.today("user-id", 120)

    assert result.status == "unavailable"
    assert result.cheapest is None


def test_today_insights_endpoint(client):
    service, _ = _today_service(_day_prices(_between(18, 20, 2.0)), 9)
    app.dependency_overrides[get_price_insights_service] = lambda: service
    try:
        response = client.get("/api/v1/dynamic-prices/today/insights", params={"window": "2h"})
    finally:
        app.dependency_overrides.pop(get_price_insights_service, None)

    assert response.status_code == 200
    assert response.json()["most_expensive"]["start"] == "2026-11-17T18:00:00+01:00"
