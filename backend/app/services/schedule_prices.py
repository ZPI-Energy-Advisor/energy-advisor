"""Ceny kwadransów dla optymalizacji harmonogramu z nowego cennika, według taryfy z profilu użytkownika.

Cena kwadransa to wszystko, co na rachunku zależy od zużytej kWh: energia (cena strefy albo cena rynkowa z marżą przy
umowie z ceną dynamiczną), akcyza, dystrybucja zmienna strefy, opłaty jakościowa, OZE i kogeneracyjna, z VAT.
Opłaty miesięczne (stała, abonament, mocowa, handlowa) pomijamy, bo przesunięcie urządzenia ich nie zmienia.
Ceny kwadransów liczy wspólna funkcja `quarter_prices`, tak jak energię i dystrybucję w silniku taryf.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.parsers.devices import LOCAL_TIMEZONE
from app.schemas.other import TariffTypeEnum
from app.schemas.user_profile import UserProfile
from app.services.pv_service import PVBalancingEngine
from app.services.quarter_prices import quarter_prices

SLOT = timedelta(minutes=15)


@dataclass(frozen=True)
class SchedulePrices:
    prices: dict[datetime, float]
    description: str
    # Moc umowna z profilu: limit poboru domu w kwadransie dla harmonogramu.
    max_grid_kw: float | None = None
    # Plik ma nadwyżkę PV, a profil nie ma instalacji: godziny produkcji nie są tańsze.
    pv_note: str | None = None
    # Umowa z ceną dynamiczną: ceny kolejnych dni pojawiają się dopiero po publikacji RCE.
    dynamic: bool = False


class SchedulePriceService:
    def __init__(self, user_repository, tariff_repository, market_prices):
        self.user_repository = user_repository
        self.tariff_repository = tariff_repository
        # DynamicMarketPriceResolver: cena RCE kwadransa (zł/kWh) i wycena energii oddanej w net-billingu.
        self.market_prices = market_prices

    def for_user(
        self, user_id: UUID, start_utc: datetime, end_utc: datetime, exports: dict[datetime, float] | None = None
    ) -> SchedulePrices:
        """`exports`: energia oddana do sieci w kwadransach pliku (początek w UTC -> kWh)."""
        profile = self._profile(user_id)
        operator = profile.base_info.distribution_operator
        group = profile.consumption_and_tariff.tariff_type
        dynamic = profile.consumption_and_tariff.dynamic_price
        prosumer = profile.pv_config.mode != "none"
        first_day = start_utc.astimezone(LOCAL_TIMEZONE).date()
        last_day = (end_utc - SLOT).astimezone(LOCAL_TIMEZONE).date()

        code = TariffTypeEnum.DYNAMIC if dynamic else group
        definitions = [
            definition
            for definition in self.tariff_repository.list_for_period(operator=operator, date_from=first_day, date_to=last_day)
            if definition.tariff_code == code and definition.distribution_group == group
        ]
        label = f"{group.value} z ceną dynamiczną" if dynamic else group.value
        if not definitions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Brak stawek taryfy {label} u operatora {operator.value} dla wybranego okresu.",
            )
        periods = self.tariff_repository.list_regulatory_periods(date_from=first_day, date_to=last_day)
        if dynamic:
            preload = getattr(self.market_prices, "preload_rce", None)
            if preload is not None:
                preload(start_utc, end_utc)
        quarters = quarter_prices(
            definitions, periods, start_utc, end_utc,
            market_price=self.market_prices.rce if dynamic else None, prosumer=prosumer,
        )

        prices: dict[datetime, float] = {}
        for slot, price in quarters.gross().items():
            if prosumer and (exports or {}).get(slot, 0) > 0:
                price = self._surplus_price(slot, price, profile)
            prices[slot] = price
        name = next((definition.name for definition in definitions if definition.name), None)
        description = f"{operator.value}, {label}" + (f" ({name})" if dynamic and name else "")
        pv_note = None
        surplus_kwh = sum(kwh for kwh in (exports or {}).values() if kwh > 0)
        if not prosumer and surplus_kwh > 0:
            surplus_text = f"{surplus_kwh:.2f}".replace(".", ",")
            pv_note = (
                f"Plik ma {surplus_text} kWh nadwyżki z fotowoltaiki oddanej do sieci, ale profil nie ma instalacji PV, "
                "więc godziny produkcji nie są tańsze i nie przenosimy na nie urządzeń. Uzupełnij fotowoltaikę w profilu."
            )
        return SchedulePrices(
            prices=prices, description=description,
            max_grid_kw=profile.base_info.contracted_power_kw, pv_note=pv_note, dynamic=dynamic,
        )

    def _surplus_price(self, slot: datetime, grid_price: float, profile: UserProfile) -> float:
        """Kwadrans z nadwyżką PV: dodatkowe zużycie zmniejsza oddanie do sieci, więc kosztuje utraconą wartość
        oddanej energii, a nie cenę z sieci. Net-billing: cena RCE (ujemna = 0), za którą rośnie depozyt;
        net-metering: (1 − współczynnik) ceny z sieci, bo oddaną energię odbiera się w 80% (70%).
        Przybliżenie: nie sprawdzamy, czy nadwyżka pokrywa całą akcję — dokładny wynik daje rachunek „po”."""
        if profile.pv_config.mode == "net_metering":
            return round(grid_price * (1 - profile.pv_config.effective_k_factor), 5)
        try:
            value = PVBalancingEngine(self.market_prices).get_price_for_pv_energy(
                slot.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None), profile.pv_config.type_of_price
            )
            return round(value, 5)
        except ValueError:
            return grid_price

    def _profile(self, user_id: UUID) -> UserProfile:
        stored = self.user_repository.get_profile(user_id)
        try:
            if stored is None:
                raise ValueError
            return UserProfile.model_validate(stored)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Uzupełnij profil (operator i taryfa), żeby optymalizacja liczyła ceny Twojej taryfy.",
            ) from exc
