"""Plan pracy urządzeń na dzień (ZP-112)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.schedule import ScheduledActionOut, SchedulePriceOut


class DayPlanRequest(BaseModel):
    # Bez daty: jutro. Data z przeszłości służy do demo, gdy cen na jutro jeszcze nie ma.
    plan_date: date | None = None


class PlanItemOut(ScheduledActionOut):
    """Przydział akcji: start bazowy (`original_*`, początek przedziału) i start z planu (`start`, `end`)."""

    kind: Literal["program", "ev", "heat_pump", "water_heater"]


class WaterTemperatureOut(BaseModel):
    # Temperatura wody na końcu kwadransu zaczętego o `start`: bez planu (termostat) i według planu.
    start: datetime
    before: float
    after: float


class WaterHeaterPlanOut(BaseModel):
    device_id: str
    device_name: str
    tank_liters: int
    residents: int
    hot_water_kwh: float
    ready_times: list[str]
    min_temp: float
    ready_temp: float
    max_temp: float
    # Stygnięcie przy `ready_temp` (°C na godzinę); rośnie z różnicą do temperatury pomieszczenia.
    loss_per_hour: float
    room_temp: float | None = None
    hot_water_source: Literal["history", "residents"] | None = None
    # Średnie zużycie bojlera na dobę z plików (z termostatem), gdy pobór jest z historii.
    history_kwh: float | None = None
    # Temperatura o północy: termostat trzyma `ready_temp`, a plan zaczyna niżej (w nocy wystarczy mniej).
    # Domyślne None: plany zapisane przed dodaniem tych pól też muszą dać się odczytać.
    start_before: float | None = None
    start_after: float | None = None
    # Największe niedogrzanie (°C), gdy grzałka nie nadąża; 0, gdy wymagania są spełnione.
    shortfall: float
    temperatures: list[WaterTemperatureOut]


class DayPlanOut(BaseModel):
    id: UUID
    plan_date: date
    status: Literal["draft", "approved"]
    created_at: datetime
    approved_at: datetime | None = None
    # Zakres planu: doba planu i noc po niej do 06:00 (np. zmywarka albo auto przez północ).
    horizon_start: datetime
    horizon_end: datetime
    pricing: str
    max_grid_kw: float | None = None
    # Od tej chwili ceny są przybliżone: taryfa dynamiczna nie ma jeszcze cen kolejnej doby,
    # więc kwadranse po północy mają ceny z tych samych godzin doby planu.
    approximate_from: datetime | None = None
    # Koszt energii planowanych urządzeń: start na początku przedziałów (przed) i według planu (po).
    cost_before: float
    cost_after: float
    saving: float
    notes: list[str] = []
    # Ostrzeżenia: plan nie spełni czegoś z ustawień (np. auto nie naładuje się do końca).
    warnings: list[str] = []
    items: list[PlanItemOut]
    prices: list[SchedulePriceOut]
    water_heaters: list[WaterHeaterPlanOut] = []
