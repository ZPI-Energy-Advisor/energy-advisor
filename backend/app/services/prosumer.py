"""Wartość energii oddanej do sieci przez prosumenta: wspólna dla ekranu „Fotowoltaika” (ZP-150), planu na jutro
i raportu z symulacji (ZP-121), żeby kwoty się zgadzały.

- Net-metering: opust (0,8 albo 0,7) × cena zakupu w tej godzinie.
- Net-billing: RCE (albo RCEm) × 1,23 do depozytu (`PVBalancingEngine.get_price_for_pv_energy`), ujemna cena = 0.
  Godzina to średnia z jej 4 kwadransów. Bez opublikowanej ceny: średnia RCE z tych samych godzin z 14 poprzednich
  dni (szacunek). Umowa z RCEm przed publikacją RCEm miesiąca (ok. 10. dnia następnego): RCE z godziny.
"""

from datetime import date, datetime, timedelta

from app.providers.prices.base import MARKET_TIMEZONE
from app.schemas.other import TypeOfMarketEnergyEnum
from app.schemas.user_profile import UserProfile
from app.services.pv_service import NET_BILLING_REFORM_FROM, PVBalancingEngine

QUARTER = timedelta(minutes=15)
PRICE_LOOKBACK_DAYS = 14


def _naive_local(moment: datetime) -> datetime:
    return moment.astimezone(MARKET_TIMEZONE).replace(tzinfo=None)


class ExportValuation:
    def __init__(self, market, profile: UserProfile):
        self.market = market
        self.profile = profile

    @property
    def net_metering(self) -> bool:
        return self.profile.pv_config.mode == "net_metering"

    def rcem_replaced(self, day: date) -> bool:
        """Umowa z RCEm, a RCEm miesiąca tego dnia jeszcze nie ma: oddanie wyceniamy cenami RCE."""
        return (
            not self.net_metering
            and self.profile.pv_config.type_of_price == TypeOfMarketEnergyEnum.RCEm
            and day >= NET_BILLING_REFORM_FROM
            and not self.market.rcem_published(day)
        )

    def hour_price(self, hour: datetime, purchase_price: float) -> tuple[float | None, bool]:
        """Wartość kWh oddanej w godzinie zaczętej o `hour` (UTC) i czy to szacunek; None bez żadnej ceny."""
        if self.net_metering:
            return purchase_price * self.profile.pv_config.effective_k_factor, False
        engine = PVBalancingEngine(self.market)
        price_type = self.profile.pv_config.type_of_price or TypeOfMarketEnergyEnum.RCE
        quarters = [_naive_local(hour + QUARTER * index) for index in range(4)]
        try:
            return sum(engine.get_price_for_pv_energy(q, price_type) for q in quarters) / 4, False
        except ValueError:
            pass
        past = []
        for days_back in range(1, PRICE_LOOKBACK_DAYS + 1):
            for quarter in quarters:
                try:
                    past.append(engine.get_price_for_pv_energy(quarter - timedelta(days=days_back), TypeOfMarketEnergyEnum.RCE))
                except ValueError:
                    continue
        if not past:
            return None, True
        return sum(past) / len(past), True
