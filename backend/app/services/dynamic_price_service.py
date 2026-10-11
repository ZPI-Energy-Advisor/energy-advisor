from datetime import date
from decimal import Decimal

from app.repositories.dynamic_price_repository import DynamicPriceRepository
from app.schemas.dynamic_price import DynamicPriceDayResponse, DynamicPriceOut



class DynamicPriceService:
    def __init__(self, repository: DynamicPriceRepository, source: str):
        self.repository = repository
        self.source = source

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
