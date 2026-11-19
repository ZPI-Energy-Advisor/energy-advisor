from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.providers.prices.base import MARKET_TIMEZONE, expected_intervals, local_day_bounds_utc
from app.repositories.dynamic_price_repository import DynamicPriceRepository
from app.schemas.dynamic_price import (
    DynamicPriceDayResponse,
    DynamicPriceOut,
    PriceBreakdownOut,
    PriceHistoryDaysOut,
    PriceHistoryPointOut,
    PriceHistoryResponse,
    PriceResolution,
)
from app.services.quarter_prices import KwhPrice
from app.services.tariff_costs import (
    PART_NAMES,
    PricingProfile,
    TariffCostService,
    local_midnight_utc,
    polish_date,
    price_parts,
)


DEFAULT_HISTORY_DAYS = 7
SOURCE_INTERVAL_MINUTES = 15
STEP_BY_RESOLUTION = {
    PriceResolution.QUARTER_HOUR: timedelta(minutes=SOURCE_INTERVAL_MINUTES),
    PriceResolution.HOUR: timedelta(hours=1),
}


class DynamicTariffNotFoundError(Exception):
    pass


class DynamicPriceService:
    """Ceny RCE i pełna cena brutto kWh w ofercie z ceną dynamiczną operatora z profilu (bez profilu PGE, G11):
    energia (RCE + marża), dystrybucja, opłaty za kWh i VAT z nowego cennika."""

    def __init__(self, repository: DynamicPriceRepository, source: str, tariff_costs: TariffCostService | None = None):
        self.repository = repository
        self.source = source
        self.tariff_costs = tariff_costs

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
        user_id=None,
    ) -> PriceHistoryResponse:
        profile = self.tariff_costs.profile(user_id) if self.tariff_costs else PricingProfile()
        available_from, available_to, last_updated_at = self.repository.get_available_range(self.source)

        if date_from is None or date_to is None:
            if available_to is None:
                return self._response(profile, None, None, resolution, last_updated_at=last_updated_at)
            date_to = available_to
            date_from = max(available_from, date_to - timedelta(days=DEFAULT_HISTORY_DAYS - 1))

        option, note = self.tariff_costs.dynamic_offer(profile, date_from, date_to) if self.tariff_costs else (None, None)
        if option is None:
            raise DynamicTariffNotFoundError(note or "Brak oferty z ceną dynamiczną w cenniku.")
        offer_start = option.definitions[0].valid_from
        if date_from < offer_start:
            cut_off = (
                f"Pełną cenę kWh tej oferty liczymy od {polish_date(offer_start)}, "
                f"więc wcześniejsze dni nie mają ceny na wykresie."
            )
            note = f"{note} {cut_off}" if note else cut_off

        prices = self._quarter_prices(option, profile, date_from, date_to)
        days = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
        counts = self.repository.count_by_business_date(self.source, date_from, date_to)

        if resolution == PriceResolution.DAY:
            points = self._daily_points(days, date_from, date_to, prices)
        else:
            points = self._intraday_points(days, date_from, date_to, resolution, prices)

        gross = [float(price.gross) for price in prices.values()]
        return self._response(
            profile, option, note, resolution,
            date_from=date_from,
            date_to=date_to,
            available_from=available_from,
            available_to=available_to,
            last_updated_at=last_updated_at,
            average_price_pln_kwh=self._round(sum(gross) / len(gross)) if gross else None,
            min_price_pln_kwh=self._round(min(gross)) if gross else None,
            max_price_pln_kwh=self._round(max(gross)) if gross else None,
            price_breakdown=self._breakdown(prices.values()),
            points=points,
            days=self._days_summary(days, counts),
        )

    def _quarter_prices(self, option, profile, date_from: date, date_to: date) -> dict[datetime, KwhPrice]:
        start, end = local_midnight_utc(date_from), local_midnight_utc(date_to + timedelta(days=1))
        market = {
            moment.astimezone(timezone.utc): float(price) / 1000.0
            for moment, price in self.repository.get_prices_between(self.source, start, end).items()
        }

        def market_price(slot: datetime) -> float:
            if slot not in market:
                raise ValueError(f"Brak ceny RCE dla interwału {slot.isoformat()}.")
            return market[slot]

        try:
            return self.tariff_costs.prices(option, start, end, profile, market_price=market_price).prices
        except (ValueError, LookupError) as error:
            raise DynamicTariffNotFoundError(str(error)) from error

    def _response(self, profile, option, note, resolution, **values) -> PriceHistoryResponse:
        return PriceHistoryResponse(
            source=self.source,
            operator=profile.operator.value,
            tariff_name=(option.name or option.label) if option else None,
            distribution_group=option.group.value if option else None,
            from_profile=profile.from_profile,
            note=note,
            unit="PLN/kWh",
            timezone=MARKET_TIMEZONE.key,
            resolution=resolution,
            **values,
        )

    @staticmethod
    def _round(value: float | None) -> float | None:
        return None if value is None else round(value, 5)

    @classmethod
    def _average(cls, prices: list[KwhPrice]) -> float | None:
        return cls._round(sum(float(price.gross) for price in prices) / len(prices)) if prices else None

    @staticmethod
    def _breakdown(prices) -> PriceBreakdownOut | None:
        prices = list(prices)
        if not prices:
            return None
        totals = dict.fromkeys(PART_NAMES, Decimal("0"))
        for price in prices:
            for name, value in price_parts(price).items():
                totals[name] += value
        return PriceBreakdownOut(**{name: round(float(value) / len(prices), 5) for name, value in totals.items()})

    def _daily_points(self, days, date_from, date_to, prices) -> list[PriceHistoryPointOut]:
        counts = {day: count for day, _, count in self.repository.get_daily_averages(self.source, date_from, date_to)}
        by_day = defaultdict(list)
        for moment, price in prices.items():
            by_day[moment.astimezone(MARKET_TIMEZONE).date()].append(price)
        return [
            self._point(
                local_day_bounds_utc(day)[0], self._average(by_day.get(day, [])), counts.get(day, 0),
                expected_intervals(day, SOURCE_INTERVAL_MINUTES),
            )
            for day in days
        ]

    def _intraday_points(self, days, date_from, date_to, resolution, prices) -> list[PriceHistoryPointOut]:
        if resolution == PriceResolution.HOUR:
            rows_source = self.repository.get_hourly_averages(self.source, date_from, date_to)
        else:
            rows_source = self.repository.get_quarter_hour_prices(self.source, date_from, date_to)
        counts = {start.astimezone(timezone.utc): count for start, _, count in rows_source}

        step = STEP_BY_RESOLUTION[resolution]
        expected = int(step / timedelta(minutes=SOURCE_INTERVAL_MINUTES))
        quarter = timedelta(minutes=SOURCE_INTERVAL_MINUTES)

        points = []
        for day in days:
            start, end = local_day_bounds_utc(day)
            moment = start
            while moment < end:
                in_step = [prices[slot] for slot in (moment + quarter * i for i in range(expected)) if slot in prices]
                points.append(self._point(moment, self._average(in_step), counts.get(moment, 0), expected))
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
