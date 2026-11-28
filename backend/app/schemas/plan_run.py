"""Przebieg planu dnia w symulacji Smart Home"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.smart_home import HubCommandStatus


class PlanRunRequest(BaseModel):
    plan_id: UUID


class PlanRunReplay(BaseModel):
    """Przebiegi z historii wysłane do huba razem z planem: produkcja PV oraz pompa ciepła i bojler spoza planu."""

    actions: int
    devices: int
    # Urządzenia spoza rejestru huba (device_not_found, np. zaległa wysyłka); ich historia się nie odtworzy.
    skipped_devices: list[str] = []
    # Pojedyncze przebiegi odrzucone przez hub z innego powodu (np. zajęte urządzenie).
    rejected_actions: int = 0


class PlanRunHistoryDeviceOut(BaseModel):
    """Urządzenie pracujące samo: energia wysłana do huba i zużyta w symulacji (ujemna dla PV)."""

    device_id: str
    device_name: str
    # Dzień referencyjny tego urządzenia, jak w planie: liczony osobno dla każdego urządzenia. None dla PV
    # z prognozy bez historii w plikach.
    history_day: date | None = None
    # Energia wysłana do huba: z prognozy pogody (`source = forecast`) albo z dnia referencyjnego.
    history_kwh: float
    actual_kwh: float
    source: Literal["forecast", "history"] = "history"
    # Energia dnia referencyjnego, gdy doba jest z prognozy; None w przebiegach sprzed ZP-120.
    reference_kwh: float | None = None


class PlanRunActionOut(BaseModel):
    """Pozycja planu wysłana do huba i wynik jej komendy (`rejected` z powodem w `code` i `detail`)."""

    action_id: str
    device_id: str
    device_name: str
    kind: str
    label: str | None = None
    start: datetime
    end: datetime
    energy_kwh: float
    status: HubCommandStatus
    code: str | None = None
    detail: str | None = None
    # Do rachunku przed i po (ZP-114); None w przebiegach sprzed niego. `command_id` z wyniku huba łączy
    # akcję z jej device_started: start urządzenia z innym command_id to ręczne włączenie.
    command_id: str | None = None
    # Energia i koszt bez planu (start bazowy z planu) i koszt według planu, cenami kwadransów planu.
    energy_before_kwh: float | None = None
    cost_before: float | None = None
    planned_cost: float | None = None
    # Profile bez planu i według planu (ZP-153): oszczędność do teraz kwadrans po kwadransie. None w przebiegach
    # sprzed tej zmiany.
    original_start: datetime | None = None
    original_profile_kwh: list[float] | None = None
    profile_kwh: list[float] | None = None


class PlanRunDeviceOut(BaseModel):
    """Urządzenie z planu: energia według planu i zużyta w symulacji od początku planu do `sim_time`."""

    device_id: str
    device_name: str
    kind: str
    planned_kwh: float
    actual_kwh: float
    actions: list[PlanRunActionOut]


class PlanRunPriceOut(BaseModel):
    """Cena kwadransu planu (zł/kWh brutto) do paska czasu na ekranie „Mój dom”."""

    start: datetime
    price_pln_kwh: float


class PlanRunWaterTemperatureOut(BaseModel):
    # Temperatura wody według planu na końcu kwadransu zaczętego o `start`.
    start: datetime
    temp_c: float


class PlanRunWaterHeaterOut(BaseModel):
    """Bojler z planu: przebieg temperatury wody według planu (z migawki przy starcie przebiegu)."""

    device_id: str
    device_name: str
    temperatures: list[PlanRunWaterTemperatureOut]


class PlanRunErrorOut(BaseModel):
    """Awaria urządzenia w trakcie przebiegu, np. komenda, której urządzenie nie wykonało o `start_at`."""

    device_id: str
    device_name: str
    sim_time: datetime
    code: str
    message: str


class PlanRunCostDeviceOut(BaseModel):
    """Urządzenie z planu w porównaniu: bez planu (start bazowy) i z planem (zmierzone w symulacji)."""

    device_id: str
    device_name: str
    kind: str
    energy_before_kwh: float
    energy_after_kwh: float
    cost_before: float
    # Koszt według planu i koszt zmierzony; różnią się, gdy urządzenie zużyło inaczej niż w planie.
    planned_cost: float
    cost_after: float
    saving: float


class PlanRunDeviceRefOut(BaseModel):
    device_id: str
    device_name: str


class PlanRunManualDeviceOut(BaseModel):
    """Urządzenie włączane ręcznie z „Mój dom” (urządzenia stałe): poza porównaniem."""

    device_id: str
    device_name: str
    energy_kwh: float
    cost: float


class PlanRunPvOut(BaseModel):
    """Produkcja PV przebiegu, poza porównaniem: ile zużył dom w tym samym kwadransie i ile z tego plan."""

    production_kwh: float
    self_consumption_kwh: float
    # Część autokonsumpcji przypadająca na urządzenia z planu (w proporcji do ich zużycia w kwadransie).
    plan_from_pv_kwh: float
    plan_kwh: float


DeviationKind = Literal["rejected", "device_error", "interrupted", "manual_start", "energy_mismatch", "grid_limit"]


class PlanRunDeviationOut(BaseModel):
    """Odchylenie od planu; `excluded` – urządzenie z tego powodu wypada z porównania."""

    kind: DeviationKind
    device_id: str | None = None
    device_name: str | None = None
    sim_time: datetime | None = None
    end: datetime | None = None
    message: str
    excluded: bool = False


class PlanRunCostOut(BaseModel):
    """Rachunek przed i po planie (ZP-114).

    Porównujemy tylko urządzenia z planu, tak jak oszczędność na ekranie planu, i tylko te, których wszystkie
    akcje skończyły się do `until` bez ingerencji (ręczne włączenie lub wyłączenie, awaria, odrzucona komenda).
    Urządzenia stałe i PV są osobno. `complete` – przebieg doszedł do końca planu; inaczej raport jest niepełny
    i urządzenia z akcjami po `until` są w `pending`.
    """

    complete: bool
    until: datetime
    cost_before: float
    cost_after: float
    planned_cost: float
    saving: float
    # Oszczędność w procentach kosztu bez planu; None, gdy nie ma czego porównać.
    saving_percent: float | None = None
    devices: list[PlanRunCostDeviceOut]
    excluded: list[PlanRunDeviceRefOut] = []
    pending: list[PlanRunDeviceRefOut] = []
    manual: list[PlanRunManualDeviceOut] = []
    manual_cost: float = 0.0
    pv: PlanRunPvOut | None = None
    deviations: list[PlanRunDeviationOut] = []


class PlanRunSummaryOut(BaseModel):
    """Przebieg na liście historii: rachunek z zapisanego raportu (None w trakcie i sprzed ZP-114)."""

    id: UUID
    plan_date: date
    # `past_day`: plan idealny dnia z przeszłości (ZP-152); `tomorrow`: plan na jutro.
    plan_kind: Literal["tomorrow", "past_day"] = "tomorrow"
    status: Literal["running", "completed", "ended", "superseded"]
    started_at: datetime
    ended_at: datetime | None = None
    complete: bool | None = None
    cost_before: float | None = None
    cost_after: float | None = None
    saving: float | None = None
    saving_percent: float | None = None
    deviations: int | None = None


class PlanRunIndoorPointOut(BaseModel):
    # Temperatura w domu na końcu kwadransu zaczętego o `start`: według planu i z symulacji (None po `until`).
    start: datetime
    plan_c: float
    temp_c: float | None = None


class PlanRunIndoorOut(BaseModel):
    """Temperatura w domu z pompą ciepła na końcu ostatniego pełnego kwadransa (`at`): z modelu domu z planu
    na energii pompy zmierzonej w symulacji, obok temperatury według planu i zakresu komfortu."""

    device_id: str
    device_name: str
    at: datetime
    temp_c: float
    plan_c: float | None = None
    set_c: float
    band: list[float]
    points: list[PlanRunIndoorPointOut] = []


class PlanRunWeatherNowOut(BaseModel):
    start: datetime
    temperature_c: float | None = None
    cloud_cover_pct: int | None = None
    # Prognoza (plan na jutro) albo archiwum (plan idealny).
    past: bool = False


class PlanRunPvHourOut(BaseModel):
    # Godzina doby: produkcja, na którą liczy plan, i produkcja zmierzona w symulacji (None po `until`).
    start: datetime
    planned_kwh: float | None = None
    actual_kwh: float | None = None


class PlanRunPvLiveOut(BaseModel):
    """Panele od początku planu w bilansie godzinowym: zużyte w domu i oddane do sieci sumują się do produkcji."""

    production_kwh: float
    self_kwh: float
    export_kwh: float
    # Wartość oddania (z migawki planu); None, gdy plan nie ma wyceny oddania.
    export_pln: float | None = None
    # Produkcja, na którą plan liczy w całej dobie (None w planie bez PV), i godziny doby.
    planned_kwh: float | None = None
    hours: list[PlanRunPvHourOut] = []


class PlanRunSavingLiveOut(BaseModel):
    """Oszczędność do teraz: urządzenia z planu od początku planu do `until`, bez planu (profil bazowy przycięty)
    i z planem (energia zmierzona), tym samym rachunkiem co raport. Bez urządzeń z odchyleniem."""

    cost_before: float
    cost_after: float
    saving: float
    saving_percent: float | None = None
    excluded: list[PlanRunDeviceRefOut] = []
    # Oszczędność, którą plan daje w całej dobie: w trakcie doby „do teraz” może być większa albo mniejsza,
    # bo plan przesuwa pracę w czasie.
    planned_saving: float | None = None


class PlanRunLiveOut(BaseModel):
    """Statystyki na żywo w czasie symulacji (ZP-153), liczone przy odczycie z migawki przebiegu i zdarzeń."""

    until: datetime
    indoor: list[PlanRunIndoorOut] = []
    weather: PlanRunWeatherNowOut | None = None
    pv: PlanRunPvLiveOut | None = None
    # Cena kWh z sieci w bieżącym kwadransie i wartość kWh oddanej w tej godzinie (None bez PV w planie).
    price_now: float | None = None
    export_price_now: float | None = None
    saving: PlanRunSavingLiveOut | None = None


class PlanRunOut(BaseModel):
    id: UUID
    plan_id: UUID
    plan_date: date
    plan_kind: Literal["tomorrow", "past_day"] = "tomorrow"
    status: Literal["running", "completed", "ended", "superseded"]
    simulation_id: str
    started_at: datetime
    ended_at: datetime | None = None
    # Bieżący czas symulacji przebiegu, a po jego końcu chwila, w której się skończył.
    sim_time: datetime | None = None
    horizon_start: datetime
    horizon_end: datetime
    # Najnowszy z dni referencyjnych w `replayed_devices` (zwykle wszystkie urządzenia mają ten sam);
    # None, gdy nie ma czego odtwarzać.
    history_day: date | None = None
    replay: PlanRunReplay
    replayed_devices: list[PlanRunHistoryDeviceOut] = []
    planned_kwh: float
    actual_kwh: float
    devices: list[PlanRunDeviceOut]
    # Najnowsze najpierw, najwyżej kilkadziesiąt.
    errors: list[PlanRunErrorOut] = []
    # Rachunek przed i po (ZP-114); None w przebiegach sprzed niego.
    cost: PlanRunCostOut | None = None
    # Z migawki planu przy starcie (ZP-110): ceny kwadransów do paska czasu i temperatura wody bojlerów
    # według planu. Puste w przebiegach sprzed tej zmiany.
    prices: list[PlanRunPriceOut] = []
    # Od tej chwili ceny w `prices` są przybliżone: ceny nocy po dniu planu nie były jeszcze znane, więc plan
    # przyjął ceny z tych samych godzin dnia planu. None, gdy wszystkie ceny są prawdziwe.
    prices_approximate_from: datetime | None = None
    water_heaters: list[PlanRunWaterHeaterOut] = []
    live: PlanRunLiveOut | None = None
