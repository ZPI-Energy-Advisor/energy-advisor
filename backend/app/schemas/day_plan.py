"""Plan pracy urządzeń na dzień (ZP-112)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.schedule import ScheduledActionOut, SchedulePriceOut


class DayPlanRequest(BaseModel):
    # Bez daty: jutro. Data z przeszłości to plan idealny tamtej doby (ZP-152) albo plan demo, gdy cen na jutro
    # jeszcze nie ma.
    plan_date: date | None = None


class PlanFilePeriodOut(BaseModel):
    first_day: date
    last_day: date


class PastDaysOut(BaseModel):
    """Dni, na które da się ułożyć plan idealny: od pierwszego dnia z cenami taryfy do wczoraj, i okresy plików
    urządzeń (w nich „bez planu” to to, co dom naprawdę robił)."""

    first_day: date | None
    last_day: date
    file_periods: list[PlanFilePeriodOut]


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
    # Prąd z paneli, który pozycja bierze według planu (kWh); None w planie bez prognozy PV.
    pv_kwh: float | None = None


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


class HeatPumpWaterOut(BaseModel):
    """Ciepła woda z pompy planowana osobno (godziny „ciepła woda gotowa na” w ustawieniach)."""

    ready_times: list[str]
    tank_liters: int
    kwh: float
    cop: float
    shortfall: float


class HeatPumpIndoorPointOut(BaseModel):
    """Kwadrans doby planu: temperatura w domu na końcu kwadransu według planu i bez planu (termostat)."""

    start: datetime
    before: float
    after: float
    outdoor: float


class HeatPumpPlanOut(BaseModel):
    device_id: str
    device_name: str
    # "indoor": plan pilnuje temperatury w domu (model domu i pogoda co kwadrans); "history": bez pogody albo modelu
    # domu, bloki grzania dnia referencyjnego przeskalowane do temperatury doby (jak przed modelem domu).
    mode: Literal["indoor", "history"] = "history"
    plan_temperature: HeatPumpTemperatureOut
    reference_day: date | None = None
    reference_temperature: HeatPumpTemperatureOut | None = None
    reference_kwh: float | None = None
    target_kwh: float
    kwh: float
    heat_kwh: float
    hot_water_heat_kwh: float
    hdd: float
    cop: float
    # Temperatura w domu z ustawień pompy (domyślnie 21 °C).
    indoor_c: float = 21
    # Tylko "indoor": zakres temperatury w domu, niedogrzanie poniżej zakresu, prąd na ogrzewanie bez planu
    # (termostat na ustawionej temperaturze), o ile °C na godzinę dom stygnie bez grzania przy średniej doby,
    # stała czasowa domu i temperatura kwadrans po kwadransie.
    band: list[float] | None = None
    shortfall: float = 0.0
    # Dlaczego zabraknie ciepła: "power" (pompa za słaba), "grid" (limit przyłącza), None (wystarczy).
    shortfall_reason: Literal["power", "grid"] | None = None
    thermostat_kwh: float | None = None
    # Koszt ogrzewania domu (bez wody) według planu i bez planu, w cenach taryfy z planu.
    cost_pln: float | None = None
    thermostat_cost_pln: float | None = None
    cooling_per_hour: float | None = None
    time_constant_h: float | None = None
    # Model domu z planera (house_heating.House): temperatura w domu na żywo w symulacji (ZP-153).
    loss_kw_per_k: float | None = None
    capacity_kwh_per_k: float | None = None
    floor_heating: bool | None = None
    temperatures: list[HeatPumpIndoorPointOut] = []
    water: HeatPumpWaterOut | None = None
    model: HeatPumpModelOut


class PlanPvSummaryOut(BaseModel):
    # Prąd z paneli w dobie przy prognozie z planu: autokonsumpcja, oddanie i pobór (bilans godzinowy), część
    # paneli zużyta przez urządzenia z planu i wartość oddania.
    self_kwh: float
    export_kwh: float
    import_kwh: float
    plan_from_pv_kwh: float
    export_pln: float


class PlanPvHourOut(BaseModel):
    # Godzina z produkcją: prognoza, na ile plan liczy, reszta domu, nadwyżka nad nią, urządzenia z planu i oddanie.
    start: datetime
    forecast_kwh: float
    planned_kwh: float
    rest_kwh: float
    surplus_kwh: float
    plan_kwh: float
    export_kwh: float


class PlanWeatherQuarterOut(BaseModel):
    start: datetime
    temperature_c: float | None
    cloud_cover_pct: int | None


class PlanWeatherOut(BaseModel):
    """Pogoda doby planu zapisana razem z planem: prognoza albo archiwum (`past`) dla komórki domu."""

    fetched_at: datetime | None = None
    approximate_location: bool = False
    past: bool = False
    quarters: list[PlanWeatherQuarterOut] = []


class PlanPvOut(BaseModel):
    """Prąd z paneli w planie (ZP-121): prognoza, ile z niej plan bierze i bilans przed planem i po nim."""

    forecast_kwh: float
    # Prognoza pomniejszona o jej średni błąd (`uncertainty`): na tyle plan liczy.
    planned_kwh: float
    uncertainty: float
    uncertainty_source: Literal["history", "default", "archive"]
    basis: str | None = None
    weather_fetched_at: datetime | None = None
    coefficient: float | None = None
    settlement: str
    # Zwykłe zużycie reszty domu: urządzenia stałe z plików albo licznik minus urządzenia.
    rest_source: Literal["devices", "meter"] = "devices"
    export_estimated: bool = False
    export_unpriced: bool = False
    before: PlanPvSummaryOut | None = None
    after: PlanPvSummaryOut | None = None
    estimated_installation: bool = False
    # W godzinach ze słońcem oddanie do sieci jest warte więcej niż prąd z sieci: plan nie przesuwa pod słońce.
    export_beats_grid: bool = False
    hours: list[PlanPvHourOut] = []


class DayPlanOut(BaseModel):
    id: UUID
    plan_date: date
    status: Literal["draft", "approved"]
    # `tomorrow`: plan na jutro (także plan demo na ostatni dzień z cenami); `past_day`: plan idealny dnia
    # z przeszłości (ZP-152), z pogodą z archiwum.
    kind: Literal["tomorrow", "past_day"] = "tomorrow"
    # Tylko plan idealny: `files`, gdy dzień jest w plikach urządzeń (bez planu to, co dom naprawdę robił),
    # a `settings`, gdy nie (urządzenia i godziny z ustawień, jak w planie na jutro).
    day_source: Literal["files", "settings"] | None = None
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
    pv: PlanPvOut | None = None
    weather: PlanWeatherOut | None = None
    # Dlaczego plan liczy się bez paneli: no_installation, no_weather, no_profile albo no_forecast.
    pv_reason: str | None = None
