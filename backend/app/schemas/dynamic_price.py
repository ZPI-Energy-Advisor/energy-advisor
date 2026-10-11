from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, model_validator



# Ręczna synchronizacja działa synchronicznie (request czeka na wynik), więc ograniczamy zakres.
# Większe zakresy: `python -m app.workers.price_sync_worker backfill OD DO`.
MANUAL_SYNC_MAX_DAYS = 31


class PriceSyncRequest(BaseModel):
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("Podaj oba pola date_from i date_to albo żadne")
        if self.date_from and self.date_to:
            if self.date_from > self.date_to:
                raise ValueError("date_from nie może być późniejsza niż date_to")
            if (self.date_to - self.date_from).days + 1 > MANUAL_SYNC_MAX_DAYS:
                raise ValueError(f"Zakres może obejmować maksymalnie {MANUAL_SYNC_MAX_DAYS} dni")
        return self


class PriceSyncRunOut(BaseModel):
    id: int
    source: str
    trigger: str
    status: str
    date_from: date
    date_to: date
    days_requested: int
    days_synced: int
    records_upserted: int
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PriceSyncStatusResponse(BaseModel):
    source: str
    last_run: PriceSyncRunOut | None = None
    last_successful_run: PriceSyncRunOut | None = None


class DynamicPriceOut(BaseModel):
    interval_start: datetime
    interval_minutes: int
    price_pln_mwh: Decimal
    price_pln_kwh: Decimal


class DynamicPriceDayResponse(BaseModel):
    source: str
    business_date: date
    timezone: str
    prices: list[DynamicPriceOut]
