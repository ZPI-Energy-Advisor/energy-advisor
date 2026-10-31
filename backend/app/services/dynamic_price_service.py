from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.Tariff import Tariff
from app.providers.prices.base import MARKET_TIMEZONE, expected_intervals, local_day_bounds_utc
from app.repositories.dynamic_price_repository import DynamicPriceRepository
from app.repositories.tariff_repository import TariffRepository
from app.schemas.dynamic_price import (
    DynamicPriceDayResponse,
    DynamicPriceOut,
    PriceHistoryDaysOut,
    PriceHistoryPointOut,
    PriceHistoryResponse,
    PriceResolution,
)
from app.services.pricing_strategies import consumer_price_pln_kwh, tariff_price_parameters



DEFAULT_HISTORY_DAYS = 7
SOURCE_INTERVAL_MINUTES = 15
STEP_BY_RESOLUTION = {
    PriceResolution.QUARTER_HOUR: timedelta(minutes=SOURCE_INTERVAL_MINUTES),
    PriceResolution.HOUR: timedelta(hours=1),
}


class DynamicTariffNotFoundError(Exception):
    pass


class DynamicPriceService:
    def __init__(self, repository: DynamicPriceRepository, source: str, tariff_repository: TariffRepository):
        self.repository = repository
        self.source = source
        self.tariff_repository = tariff_repository

    def get_day(self, business_date: date) -> DynamicPriceDayResponse:
        observations = self.repository.get_for_business_date(self.source, business_date)
        return DynamicPriceDayResponse(
            source=self.source,
            business_date=business_date,
            timezone="UTC",
            prices=[
                DynamicPriceOut(
                    interval_start=o.interval_start,
                    interval_minutes=o.interval_minutes,
                    price_pln_mwh=o.price_pln_mwh,
                    price_pln_kwh=(Decimal(o.price_pln_mwh) / Decimal(1000)).quantize(Decimal("0.00001")),
                )
                for o in observations
            ],
        )

    def get_history(
        self,
        date_from: date | None,
        date_to: date | None,
        resolution: PriceResolution,
    ) -> PriceHistoryResponse:
        tariff_info, to_price = self._tariff_price_converter()
        available_from, available_to, last_updated_at = self.repository.get_available_range(self.source)

        if date_from is None or date_to is None:
            if available_to is None:
                return self._empty_history(resolution, tariff_info, last_updated_at)
            date_to = available_to
            date_from = max(available_from, date_to - timedelta(days=DEFAULT_HISTORY_DAYS - 1))

        days = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
        counts = self.repository.count_by_business_date(self.source, date_from, date_to)
        average, minimum, maximum = self.repository.get_range_stats(self.source, date_from, date_to)

        if resolution == PriceResolution.DAY:
            points = self._daily_points(days, date_from, date_to, to_price)
        else:
            points = self._intraday_points(days, date_from, date_to, resolution, to_price)

        return PriceHistoryResponse(
            source=self.source,
            **tariff_info,
            unit="PLN/kWh",
            timezone=MARKET_TIMEZONE.key,
            resolution=resolution,
            date_from=date_from,
            date_to=date_to,
            available_from=available_from,
            available_to=available_to,
            last_updated_at=last_updated_at,
            average_price_pln_kwh=to_price(average),
            min_price_pln_kwh=to_price(minimum),
            max_price_pln_kwh=to_price(maximum),
            points=points,
            days=self._days_summary(days, counts),
        )

    def consumer_prices(self, start_utc: datetime, end_utc: datetime) -> dict[datetime, float]:
        """Ceny dla klienta (zł/kWh) według początku kwadransa w UTC."""
        _, to_price = self._tariff_price_converter()
        prices = self.repository.get_prices_between(self.source, start_utc, end_utc)
        return {slot: to_price(price) for slot, price in prices.items()}

    def _tariff_price_converter(self):
        tariff = self.tariff_repository.get_first_by_type(Tariff.TYPE_DYNAMIC)
        if tariff is None:
            raise DynamicTariffNotFoundError("Brak taryfy dynamicznej w bazie - nie można policzyć ceny dla klienta.")
        markup, vat_multiplier = tariff_price_parameters(tariff)

        def to_price(price_pln_mwh):
            return None if price_pln_mwh is None else consumer_price_pln_kwh(price_pln_mwh, markup, vat_multiplier)

        info = {
            "tariff_name": tariff.name,
            "markup_pln_kwh": float(markup),
            "vat_rate": float(vat_multiplier - 1),
        }
        return info, to_price

    def _daily_points(self, days: list[date], date_from: date, date_to: date, to_price) -> list[PriceHistoryPointOut]:
        rows = {day: (price, count) for day, price, count in self.repository.get_daily_averages(self.source, date_from, date_to)}
        points = []
        for day in days:
            price, count = rows.get(day, (None, 0))
            expected = expected_intervals(day, SOURCE_INTERVAL_MINUTES)
            points.append(self._point(local_day_bounds_utc(day)[0], to_price(price), count, expected))
        return points

    def _intraday_points(
        self,
        days: list[date],
        date_from: date,
        date_to: date,
        resolution: PriceResolution,
        to_price,
    ) -> list[PriceHistoryPointOut]:
        if resolution == PriceResolution.HOUR:
            rows_source = self.repository.get_hourly_averages(self.source, date_from, date_to)
        else:
            rows_source = self.repository.get_quarter_hour_prices(self.source, date_from, date_to)
        rows = {start.astimezone(timezone.utc): (price, count) for start, price, count in rows_source}

        step = STEP_BY_RESOLUTION[resolution]
        expected = int(step / timedelta(minutes=SOURCE_INTERVAL_MINUTES))

        points = []
        for day in days:
            start, end = local_day_bounds_utc(day)
            moment = start
            while moment < end:
                price, count = rows.get(moment, (None, 0))
                points.append(self._point(moment, to_price(price), count, expected))
                moment += step
        return points

    @staticmethod
    def _point(start_utc: datetime, price_pln_kwh: float | None, count: int, expected: int) -> PriceHistoryPointOut:
        return PriceHistoryPointOut(
            start=start_utc.astimezone(MARKET_TIMEZONE),
            price_pln_kwh=price_pln_kwh,
            intervals=count,
            expected_intervals=expected,
            complete=count >= expected,
        )

    @staticmethod
    def _days_summary(days: list[date], counts: dict[date, int]) -> PriceHistoryDaysOut:
        incomplete = [day for day in days if 0 < counts.get(day, 0) < expected_intervals(day, SOURCE_INTERVAL_MINUTES)]
        missing = [day for day in days if counts.get(day, 0) == 0]
        return PriceHistoryDaysOut(
            total=len(days),
            complete=len(days) - len(incomplete) - len(missing),
            incomplete=incomplete,
            missing=missing,
        )

    def _empty_history(
        self,
        resolution: PriceResolution,
        tariff_info: dict,
        last_updated_at: datetime | None,
    ) -> PriceHistoryResponse:
        return PriceHistoryResponse(
            source=self.source,
            **tariff_info,
            unit="PLN/kWh",
            timezone=MARKET_TIMEZONE.key,
            resolution=resolution,
            last_updated_at=last_updated_at,
        )
