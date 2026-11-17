import math
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


# Najdłuższy przebieg z własnym profilem: tydzień kwadransów (akcje planu trwają zwykle od kwadransa do doby).
# Ten sam limit ma backend (app/schemas/smart_home.py); oba wynikają z kontraktu w docs/smart-home-api.md.
MAX_RUN_QUARTERS = 7 * 96


MAX_REF_LENGTH = 100  # Jak action_id z pliku urządzeń (source_action_id w backendzie).


def _valid_profile(profile: list[float]) -> list[float]:
    if not 1 <= len(profile) <= MAX_RUN_QUARTERS or not all(math.isfinite(value) for value in profile):
        raise ValueError(f"profile_kwh musi mieć od 1 do {MAX_RUN_QUARTERS} skończonych liczb")
    return profile


def _valid_ref(ref: str) -> str:
    if not 1 <= len(ref) <= MAX_REF_LENGTH:
        raise ValueError(f"ref musi mieć od 1 do {MAX_REF_LENGTH} znaków")
    return ref


# Reguły przebiegu z własnym profilem, wspólne dla POST /run urządzenia i komendy run_profile huba.
# Walidatory (a nie Field(min_length…)), bo hub odpowiada na złamanie reguł kontraktu 422 validation_error,
# a ograniczenia Field dałyby 400 invalid_request jak przy złym typie.
RunProfile = Annotated[list[float], AfterValidator(_valid_profile)]
ActionRef = Annotated[str, AfterValidator(_valid_ref)]

class AllowedWindow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str


class Flexibility(BaseModel):
    mode: str
    allowed_window: AllowedWindow | None = None
    max_shift_min: int | None = None


class Program(BaseModel):
    program_id: str
    program_name: str
    duration_min: int
    profile_kwh: list[float]

    @model_validator(mode="after")
    def validate_profile(self):
        if self.duration_min <= 0 or len(self.profile_kwh) * 15 != self.duration_min:
            raise ValueError("profile_kwh musi mieć jedną wartość na kwadrans duration_min")
        return self


class DeviceConfig(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    device_category: str
    # Pomieszczenie z rejestru backendu (ZP-109), dla widoku budynku; na pracę urządzenia nie wpływa.
    room: str | None = None
    max_power_kw: float | None = None
    flexibility: Flexibility
    programs: list[Program] = []

    @model_validator(mode="after")
    def validate_power(self):
        if not self.programs and self.max_power_kw is None:
            raise ValueError("Urządzenie bez programów wymaga max_power_kw")
        return self


class StartupConfig(BaseModel):
    """pola pliku startowego, które nie należą do konfiguracji urządzenia."""

    port: int
    bind_host: str = "127.0.0.1"


class TickRequest(BaseModel):
    sim_time: datetime


class CommandContext(BaseModel):
    """Opcjonalna treść poleceń startu: hub podaje command_id, które wraca w zdarzeniu device_started."""

    command_id: str | None = None


class RunRequest(BaseModel):
    """POST /run: praca według profilu (kWh na kwadrans), np. akcja planu albo produkcja PV.

    Ujemne wartości to produkcja (PV). `ref` wskazuje akcję (np. z planu) i wraca w zdarzeniach.
    """

    profile_kwh: RunProfile
    command_id: str | None = None
    ref: ActionRef | None = None
