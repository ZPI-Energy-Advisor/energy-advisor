from datetime import date, datetime
from decimal import Decimal
from enum import Enum

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


class PriceResolution(str, Enum):
    QUARTER_HOUR = "15min"
    HOUR = "hour"
    DAY = "day"


# Limity długości zakresu dla rozdzielczości
MAX_HISTORY_DAYS = {
    PriceResolution.QUARTER_HOUR: 31,
    PriceResolution.HOUR: 92,
    PriceResolution.DAY: None,
}


class PriceHistoryQuery(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    resolution: PriceResolution = PriceResolution.HOUR

    @model_validator(mode="after")
    def validate_range(self):
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("Podaj obie daty zakresu albo żadną")
        if self.date_from and self.date_to:
            if self.date_from > self.date_to:
                raise ValueError("Data początkowa nie może być późniejsza niż data końcowa")
            max_days = MAX_HISTORY_DAYS[self.resolution]
            if max_days and (self.date_to - self.date_from).days + 1 > max_days:
                raise ValueError(
                    f"Dla rozdzielczości {self.resolution.value} zakres może obejmować maksymalnie {max_days} dni"
                )
        return self


class PriceHistoryPointOut(BaseModel):
    start: datetime 
    price_pln_kwh: float | None
    intervals: int
    expected_intervals: int
    complete: bool


class PriceHistoryDaysOut(BaseModel):
    total: int = 0
    complete: int = 0
    incomplete: list[date] = []
    missing: list[date] = []


class PriceHistoryResponse(BaseModel):
    source: str
    tariff_name: str
    markup_pln_kwh: float
    vat_rate: float
    unit: str
    timezone: str
    resolution: PriceResolution
    date_from: date | None = None
    date_to: date | None = None
    available_from: date | None = None
    available_to: date | None = None
    last_updated_at: datetime | None = None
    average_price_pln_kwh: float | None = None
    min_price_pln_kwh: float | None = None
    max_price_pln_kwh: float | None = None
    points: list[PriceHistoryPointOut] = []
    days: PriceHistoryDaysOut = PriceHistoryDaysOut()
