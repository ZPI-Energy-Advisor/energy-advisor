import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Protocol

from app.models.Tariff import Tariff
from app.providers.prices.base import MARKET_TIMEZONE
from app.providers.prices.pse_provider import PseRcePriceProvider
from app.repositories.dynamic_price_repository import DynamicPriceRepository
from app.repositories.tariff_repository import TariffRepository



SLOTS_PER_DAY = 96
SLOT_MINUTES = 15

logger = logging.getLogger(__name__)


def slot_start_time(slot: int) -> time:
    return time(slot * SLOT_MINUTES // 60, slot * SLOT_MINUTES % 60)


def tariff_price_parameters(tariff) -> tuple[Decimal, Decimal]:
    """Narzut netto (PLN/kWh) i mnożnik VAT taryfy dynamicznej."""
    if tariff.markup_pln_kwh is None or tariff.vat_rate is None:
        logger.warning(
            "Taryfa %s nie ma ustawionego narzutu lub VAT - liczę samą cenę rynkową netto", tariff.name
        )
    markup = Decimal(tariff.markup_pln_kwh or 0)
    vat_multiplier = Decimal(1) + Decimal(tariff.vat_rate or 0)
    return markup, vat_multiplier


def consumer_price_pln_kwh(price_pln_mwh, markup: Decimal, vat_multiplier: Decimal) -> float:
    """Cena dla klienta = (cena rynkowa netto + narzut) * (1 + VAT)."""
    energy_pln_kwh = Decimal(price_pln_mwh) / Decimal(1000)
    return float(round((energy_pln_kwh + markup) * vat_multiplier, 5))


class TariffPricingStrategy(Protocol):
    def slot_prices(self, tariff, days: list[date]) -> dict:
        """Zwraca cennik taryfy zapisywany razem z wynikami symulacji.

        Format:
          {"type": ..., "prices": [96 cen PLN/kWh]}                      - ceny zależne tylko od pory dnia
          {"type": ..., "prices_by_day": {"RRRR-MM-DD": [96 cen | None]}} - ceny zmienne w czasie
        """
        ...


class FixedRatePricing:
    """Taryfy o stałych strefach czasowych (G11, G12) - ceny z tabeli tariff_rates."""

    def __init__(self, tariff_repository: TariffRepository):
        self.tariff_repository = tariff_repository

    def slot_prices(self, tariff, days: list[date]) -> dict:
        rates = self.tariff_repository.get_rates_for_tariff(tariff.id)

        def get_price(slot_time):
            for rate in rates:
                if rate.time_start <= slot_time <= rate.time_end:
                    return float(rate.price_per_kwh)
            return 0.0

        return {
            "type": tariff.type,
            "prices": [get_price(slot_start_time(slot)) for slot in range(SLOTS_PER_DAY)],
        }


class DynamicMarketPricing:
    """Taryfa dynamiczna - cena rynkowa z zapisanych obserwacji + narzut netto i VAT z definicji taryfy.

    Nie odpytuje dostawcy: ceny dostarcza worker synchronizacji. Brak ceny = None.
    """

    def __init__(self, price_repository: DynamicPriceRepository, source: str):
        self.price_repository = price_repository
        self.source = source

    def slot_prices(self, tariff, days: list[date]) -> dict:
        if not days:
            return {"type": tariff.type, "prices_by_day": {}}

        markup, vat_multiplier = tariff_price_parameters(tariff)

        start_utc = self._slot_start_utc(min(days), 0)
        end_utc = self._slot_start_utc(max(days) + timedelta(days=1), 0)
        stored = self.price_repository.get_prices_between(self.source, start_utc, end_utc)
        price_mwh_by_start = {start.astimezone(timezone.utc): price for start, price in stored.items()}

        prices_by_day = {}
        for day in sorted(set(days)):
            day_prices = []
            for slot in range(SLOTS_PER_DAY):
                price_mwh = price_mwh_by_start.get(self._slot_start_utc(day, slot))
                day_prices.append(
                    None if price_mwh is None else consumer_price_pln_kwh(price_mwh, markup, vat_multiplier)
                )
            prices_by_day[day.isoformat()] = day_prices

        return {"type": tariff.type, "prices_by_day": prices_by_day}

    @staticmethod
    def _slot_start_utc(day: date, slot: int) -> datetime:
        # Plik operatora ma 96 slotów na dobę - powtórzoną godzinę przy zmianie czasu
        # przypisujemy do pierwszego wystąpienia (fold=0, czas letni).
        local = datetime.combine(day, slot_start_time(slot), MARKET_TIMEZONE)
        return local.astimezone(timezone.utc)


def build_pricing_strategies(
    tariff_repository: TariffRepository,
    dynamic_price_repository: DynamicPriceRepository,
) -> dict[str, TariffPricingStrategy]:
    """Rejestr strategii wg Tariff.type - nowy typ taryfy = nowy wpis, bez zmian w CalculationService."""
    fixed = FixedRatePricing(tariff_repository)
    return {
        Tariff.TYPE_FIXED: fixed,
        Tariff.TYPE_ZONED: fixed,
        Tariff.TYPE_DYNAMIC: DynamicMarketPricing(dynamic_price_repository, source=PseRcePriceProvider.source),
    }
