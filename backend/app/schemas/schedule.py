from datetime import date, datetime

from pydantic import BaseModel


class ChargingPeriodOut(BaseModel):
    start: datetime
    end: datetime


class ScheduledActionOut(BaseModel):
    action_id: str
    device_id: str
    device_name: str
    program_name: str | None = None
    original_start: datetime
    original_end: datetime
    start: datetime
    end: datetime
    energy_kwh: float
    cost_before: float | None = None
    cost_after: float | None = None
    status: str
    reason: str | None = None
    # Ładowanie EV po optymalizacji, gdy ma przerwy: okresy ciągłego ładowania między start a end.
    charging: list[ChargingPeriodOut] | None = None


class SchedulePriceOut(BaseModel):
    start: datetime
    price_pln_kwh: float


class ScheduleResponse(BaseModel):
    date_from: date
    date_to: date
    # Taryfa, według której liczone są ceny kwadransów (operator, grupa, umowa dynamiczna).
    pricing: str = ""
    cost_before: float
    cost_after: float
    # Pełny rachunek taryfy z profilu (do zapłaty brutto) dla okresu: przed = jak w Wynikach kalkulacji,
    # po = to samo zużycie z akcjami przesuniętymi na nowe godziny.
    bill_before: float | None = None
    bill_after: float | None = None
    bill_note: str | None = None
    # Nadwyżka PV w pliku przy profilu bez instalacji PV.
    pv_note: str | None = None
    # Limit poboru z sieci: moc umowna z profilu.
    max_grid_kw: float | None = None
    # Odczyty z pliku już przekraczają limit: moc umowna w profilu jest pewnie za niska.
    grid_limit_note: str | None = None
    missing_price_actions: int = 0
    missing_price_days: list[date] = []
    actions: list[ScheduledActionOut]
    prices: list[SchedulePriceOut]
