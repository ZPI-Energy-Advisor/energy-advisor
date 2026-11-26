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
    # Do wykonania planu w symulacji (ZP-113): program urządzenia (`kind == "program"`) i energia w kolejnych
    # kwadransach od `start`, z zerami w przerwach. None w planach ułożonych przed ZP-113: taki plan trzeba
    # ułożyć ponownie, żeby uruchomić go w symulacji.
    program_id: str | None = None
    profile_kwh: list[float] | None = None
    # To samo bez planu, od `original_start`: podstawa porównania rachunku przed i po planie. Różni się od
    # `profile_kwh` nie tylko startem: bojler na termostacie i auto od podłączenia zużywają energię inaczej.
    original_profile_kwh: list[float] | None = None


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


class HeatPumpTemperatureOut(BaseModel):
    mean_c: float
    min_c: float
    max_c: float
    source: str


class HeatPumpModelOut(BaseModel):
    # "history": dopasowany do zużycia pompy z plików, "building": z profilu, "mixed": ogrzewanie z profilu, woda z plików.
    source: Literal["history", "building", "mixed"]
    heat_per_hdd: float
    hot_water_kwh: float
    floor_heating: bool
    days: int
    heating_days: int
    mape: float | None = None


class HeatPumpPlanOut(BaseModel):
    device_id: str
    device_name: str
    plan_temperature: HeatPumpTemperatureOut
    reference_day: date
    reference_temperature: HeatPumpTemperatureOut
    reference_kwh: float
    target_kwh: float
    kwh: float
    heat_kwh: float
    hot_water_heat_kwh: float
    hdd: float
    cop: float
    model: HeatPumpModelOut


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
    heat_pumps: list[HeatPumpPlanOut] = []
