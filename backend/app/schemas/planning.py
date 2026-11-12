"""Wymagania na jutro do planu pracy urządzeń (ZP-111): ustawienia użytkownika dla urządzeń z jego plików."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.smart_home import HomeDeviceProgram

# Godzina na pełnym kwadransie, bo plan układa pracę w kwadransach.
QUARTER_TIME = r"^([01]\d|2[0-3]):(00|15|30|45)$"
MAX_WINDOWS = 4


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
    preference: DevicePreference
    # Energia do naładowania wyliczona z procentów (z uwzględnieniem strat ładowania); tylko EV.
    energy_needed_kwh: float | None = None


class PlanningPreferencesOut(BaseModel):
    saved_at: datetime | None = None
    # Sprawność ładowania EV: z sieci trzeba pobrać więcej niż trafia do baterii.
    charging_efficiency: float
    devices: list[PlanningDevice]
