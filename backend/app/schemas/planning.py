"""Wymagania na jutro do planu pracy urządzeń (ZP-111): ustawienia użytkownika dla urządzeń z jego plików."""

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.smart_home import HomeDeviceProgram

# Godzina na pełnym kwadransie, bo plan układa pracę w kwadransach.
QUARTER_TIME = r"^([01]\d|2[0-3]):(00|15|30|45)$"
MAX_WINDOWS = 4
MAX_READY_TIMES = 4
MAX_SHIFT_HOURS = 3
# Rodzaj urządzenia w planie: z programem, ładowarka EV albo planowane automatycznie z historii.
DeviceKind = Literal["program", "ev", "heat_pump", "water_heater"]


class TimeWindow(BaseModel):
    """Przedział godzin jutrzejszej doby; koniec nie później niż początek oznacza przejście przez północ.

    `00:00–00:00` to cała doba, a np. `18:00–07:00` kończy się rano następnego dnia (auto podłączone na noc).
    """

    start: str = Field(pattern=QUARTER_TIME)
    end: str = Field(pattern=QUARTER_TIME)


class DevicePreference(BaseModel):
    device_id: str = Field(min_length=1, max_length=100)
    # Czy urządzenie ma jutro pracować; wyłączone urządzenie zachowuje swoje ustawienia.
    enabled: bool = False
    program_id: str | None = None
    windows: list[TimeWindow] = Field(default_factory=list, max_length=MAX_WINDOWS)
    # „Wykonaj po”: urządzenie z programem rusza po końcu programu innego (np. suszarka po pralce),
    # najwyżej godzinę później. Start wyznacza poprzednik, więc zamiast przedziałów jest tylko opcjonalne
    # „skończ najpóźniej o” (wcześniej niż początek przedziałów poprzednika: rano następnego dnia).
    # Przedziały zostają zapisane i wracają po usunięciu „Wykonaj po”.
    after_device_id: str | None = Field(default=None, max_length=100)
    finish_by: str | None = Field(default=None, pattern=QUARTER_TIME)
    # Tylko ładowarka EV: energia wprost (kWh) albo z poziomu baterii (procent i pojemność).
    energy_input: Literal["kwh", "percent"] = "kwh"
    energy_kwh: float | None = Field(default=None, gt=0, le=200, allow_inf_nan=False)
    battery_kwh: float | None = Field(default=None, gt=0, le=200, allow_inf_nan=False)
    current_percent: int | None = Field(default=None, ge=0, le=100)
    target_percent: int | None = Field(default=None, ge=0, le=100)
    # Pompa ciepła: bloki grzania z historii można przesunąć najwyżej o tyle godzin w obie strony.
    shift_hours: int | None = Field(default=None, ge=1, le=MAX_SHIFT_HOURS)
    # Bojler: godziny, na które woda ma być ciepła (pobór ciepłej wody zaczyna się o tych godzinach).
    ready_times: list[str] = Field(default_factory=list, max_length=MAX_READY_TIMES)
    # Bojler: pojemność zbiornika; bez wartości domyślna dla liczby osób z profilu.
    tank_liters: int | None = Field(default=None, ge=30, le=500)

    @field_validator("ready_times")
    @classmethod
    def _quarter_ready_times(cls, value: list[str]) -> list[str]:
        if any(not re.match(QUARTER_TIME, item) for item in value):
            raise ValueError("Godziny ustaw co kwadrans, np. 06:00 albo 17:45.")
        return value


class PlanningPreferences(BaseModel):
    """Treść zapisu ustawień; plan zawsze szuka najtańszego miejsca w przedziałach."""

    devices: list[DevicePreference] = Field(default_factory=list)


class PlanningDevice(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    device_category: str
    flexibility_mode: str
    max_power_kw: float | None = None
    programs: list[HomeDeviceProgram] = []
    # Przedziały z allowed_window pliku urządzeń (bez okna: cała doba).
    default_windows: list[TimeWindow]
    is_ev: bool
    kind: DeviceKind = "program"
    preference: DevicePreference
    # Pompa ciepła: energia doby z historii (ostatni dzień w plikach przed dniem planu).
    # Bojler: średnia energia na dobę z ostatnich 7 dni w plikach, a `history_day` to ostatni z nich.
    history_kwh: float | None = None
    history_day: date | None = None
    # Bojler: pojemność zbiornika z pliku urządzeń (wtedy zastępuje ustawienie użytkownika).
    tank_liters_from_file: int | None = None
    # Bojler: liczba osób z profilu i energia ciepłej wody na dobę, którą z niej liczymy.
    residents: int | None = None
    hot_water_kwh: float | None = None
    # Skąd ciepła woda: z historii bojlera w plikach albo z liczby osób (bez historii).
    hot_water_source: Literal["history", "residents"] | None = None
    # Energia do naładowania wyliczona z procentów (z uwzględnieniem strat ładowania); tylko EV.
    energy_needed_kwh: float | None = None


class PlanningPreferencesOut(BaseModel):
    saved_at: datetime | None = None
    # Taryfa ze stałą ceną (G11 bez ceny dynamicznej): plan prawie nic nie zaoszczędzi.
    flat_tariff: bool = False
    # Sprawność ładowania EV: z sieci trzeba pobrać więcej niż trafia do baterii.
    charging_efficiency: float
    devices: list[PlanningDevice]
