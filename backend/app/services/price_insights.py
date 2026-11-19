"""Najtańsze i najdroższe okno cenowe jutra — dane do prostych komunikatów („najtaniej jutro 12:00–14:00”).

Ceny kwadransów liczy `SchedulePriceService`, czyli dla klienta z ceną dynamiczną dokładnie te same, co
w optymalizacji (`GET /energy-files/{id}/schedule`): RCE z marżą, opłaty za kWh, VAT. Klient ze zwykłą taryfą
dostaje ceny oferty dynamicznej swojego operatora (`profile_dynamic=false`), bo to o niej są komunikaty.
Okna wyznaczamy na kwadransach w UTC, więc doba 92 i 100 kwadransów (zmiana czasu) nie wymaga osobnej obsługi.
Brak cen RCE to `unavailable` (minie po publikacji), a brak stawek w cenniku to `no_tariff_data` (nie minie sam).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Callable
from uuid import UUID

from fastapi import HTTPException, status

from app.providers.prices.base import MARKET_TIMEZONE, local_day_bounds_utc
from app.schemas.dynamic_price import PriceInsightsResponse, PriceInsightsStatus, PriceWindowOut
from app.services.schedule_prices import SLOT, NoTariffRatesError, SchedulePriceService

SLOT_MINUTES = int(SLOT.total_seconds() // 60)
# Sumy cen różniące się mniej niż o tyle traktujemy jak remis (błędy zaokrągleń float).
TIE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class PriceWindow:
    start: datetime
    end: datetime
    average_price: float


def find_price_windows(prices: dict[datetime, float], window_slots: int) -> tuple[PriceWindow, PriceWindow] | None:
    """Najtańsze i najdroższe okno z `window_slots` kolejnych kwadransów; None, gdy żadne okno się nie mieści.

    Przy remisie wygrywa wcześniejsze okno. Okno nie może obejmować luki w cenach.
    """
    if window_slots < 1:
        raise ValueError("Okno musi mieć co najmniej jeden kwadrans")
    starts = sorted(prices)
    span = SLOT * (window_slots - 1)
    cheapest: tuple[float, datetime] | None = None
    most_expensive: tuple[float, datetime] | None = None
    for index in range(len(starts) - window_slots + 1):
        start = starts[index]
        if starts[index + window_slots - 1] - start != span:
            continue
        total = math.fsum(prices[slot] for slot in starts[index : index + window_slots])
        if cheapest is None or total < cheapest[0] - TIE_TOLERANCE:
            cheapest = (total, start)
        if most_expensive is None or total > most_expensive[0] + TIE_TOLERANCE:
            most_expensive = (total, start)
    if cheapest is None or most_expensive is None:
        return None

    def window(found: tuple[float, datetime]) -> PriceWindow:
        total, start = found
        return PriceWindow(start=start, end=start + SLOT * window_slots, average_price=total / window_slots)

    return window(cheapest), window(most_expensive)


def difference_percent(price: float, daily_average: float) -> float | None:
    """O ile procent cena odbiega od średniej dobowej. Dzielimy przez moduł średniej, żeby przy ujemnej średniej
    „taniej” nadal było na minusie; przy średniej równej zero procentu nie da się policzyć (None)."""
    if abs(daily_average) < TIE_TOLERANCE:
        return None
    return round((price - daily_average) / abs(daily_average) * 100, 1)


def is_flat(prices: dict[datetime, float], threshold: float) -> bool:
    """Płaskie ceny: różnica między najdroższym a najtańszym kwadransem poniżej progu (zł/kWh)."""
    return max(prices.values()) - min(prices.values()) < threshold


class PriceInsightsService:
    def __init__(
        self,
        price_service: SchedulePriceService,
        flat_spread_pln_kwh: float,
        publication_time: time,
        now: Callable[[], datetime] = lambda: datetime.now(MARKET_TIMEZONE),
    ):
        self.price_service = price_service
        self.flat_spread_pln_kwh = flat_spread_pln_kwh
        self.publication_time = publication_time
        self.now = now

    def tomorrow(self, user_id: UUID, window_minutes: int) -> PriceInsightsResponse:
        today = self.now().astimezone(MARKET_TIMEZONE).date()
        day = today + timedelta(days=1)
        start, end = local_day_bounds_utc(day)
        expected = int((end - start) / SLOT)
        common = dict(
            business_date=day, timezone=MARKET_TIMEZONE.key, window_minutes=window_minutes, expected_intervals=expected
        )
        try:
            pricing = self.price_service.for_user(user_id, start, end, as_dynamic=True)
        except NoTariffRatesError as e:
            # Cennik operatora nie obejmuje jutra: publikacja RCE tego nie zmieni, więc to nie „unavailable”.
            return PriceInsightsResponse(
                status=PriceInsightsStatus.NO_TARIFF_DATA,
                tariff=e.description,
                profile_dynamic=not e.dynamic_instead_of_profile,
                intervals=0,
                **common,
            )
        prices = {slot: price for slot, price in pricing.prices.items() if start <= slot < end}
        common.update(
            tariff=pricing.description,
            profile_dynamic=not pricing.dynamic_instead_of_profile,
            intervals=len(prices),
        )

        if any(start <= slot < end for slot in pricing.missing_rates):
            return PriceInsightsResponse(status=PriceInsightsStatus.NO_TARIFF_DATA, **common)
        if len(prices) < expected:
            return PriceInsightsResponse(
                status=PriceInsightsStatus.UNAVAILABLE,
                expected_publication_at=datetime.combine(today, self.publication_time, MARKET_TIMEZONE),
                **common,
            )

        windows = find_price_windows(prices, window_minutes // SLOT_MINUTES)
        if windows is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Okno jest dłuższe niż doba.",
            )
        daily_average = math.fsum(prices.values()) / len(prices)

        def out(window: PriceWindow) -> PriceWindowOut:
            return PriceWindowOut(
                start=window.start.astimezone(MARKET_TIMEZONE),
                end=window.end.astimezone(MARKET_TIMEZONE),
                average_price_pln_kwh=round(window.average_price, 5),
                difference_percent=difference_percent(window.average_price, daily_average),
            )

        return PriceInsightsResponse(
            status=PriceInsightsStatus.AVAILABLE,
            average_price_pln_kwh=round(daily_average, 5),
            flat_prices=is_flat(prices, self.flat_spread_pln_kwh),
            cheapest=out(windows[0]),
            most_expensive=out(windows[1]),
            **common,
        )
