import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, model_validator

from device.models import ActionRef, DeviceConfig, RunProfile


MIN_SIM_YEAR = 1970
MAX_SIM_YEAR = 2100


def _validate_sim_moment(value: datetime, name: str) -> None:
    """Zegar tyka co kwadrans, więc inny czas nigdy nie wypadłby w ticku."""
    if value.tzinfo is None:
        raise ValueError(f"{name} musi zawierać strefę czasową")
    if not MIN_SIM_YEAR <= value.year <= MAX_SIM_YEAR:
        raise ValueError(f"{name} musi być z lat {MIN_SIM_YEAR}-{MAX_SIM_YEAR}")
    moment = value.astimezone(timezone.utc)
    if moment.minute % 15 or moment.second or moment.microsecond:
        raise ValueError(f"{name} musi być pełnym kwadransem")


class RegistryRequest(BaseModel):
    devices: list[DeviceConfig]

    @model_validator(mode="after")
    def validate_unique_ids(self):
        device_ids = [device.device_id for device in self.devices]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("device_id musi być unikalny w rejestrze")
        return self


# Komendy, które zaczynają akcję i dlatego mogą mieć start_at.
SCHEDULABLE_COMMANDS = ("start_program", "run_profile")


class DeviceCommand(BaseModel):
    command: Literal["on", "off", "start_program", "run_profile"]
    program_id: str | None = None
    # run_profile: energia w kolejnych kwadransach (ujemna dla PV) i identyfikator akcji z historii.
    # Długość, skończone liczby i długość ref sprawdzają typy wspólne z POST /run urządzenia.
    profile_kwh: RunProfile | None = None
    ref: ActionRef | None = None
    start_at: datetime | None = None

    @model_validator(mode="after")
    def validate_command(self):
        if self.command == "start_program":
            if not self.program_id:
                raise ValueError("start_program wymaga program_id")
        elif self.program_id is not None:
            raise ValueError("program_id jest dozwolone tylko przy start_program")
        if self.command == "run_profile":
            if self.profile_kwh is None:
                raise ValueError("run_profile wymaga profile_kwh")
        elif self.profile_kwh is not None or self.ref is not None:
            raise ValueError("profile_kwh i ref są dozwolone tylko przy run_profile")
        if self.start_at is not None:
            if self.command not in SCHEDULABLE_COMMANDS:
                raise ValueError("start_at jest dozwolone tylko przy start_program i run_profile")
            _validate_sim_moment(self.start_at, "start_at")
        return self


# Najwięcej komend w POST /home/commands. Doba z historii to kilkadziesiąt akcji, a plan dnia kilkanaście,
# więc limit tylko chroni hub przed żądaniem, które trzymałoby blokadę zegara bardzo długo.
MAX_BATCH_COMMANDS = 1000


class BatchCommand(DeviceCommand):
    """Komenda w POST /home/commands: jak w POST /home/devices/{device_id}/commands, z device_id w treści."""

    device_id: str


class BatchRequest(BaseModel):
    commands: list[BatchCommand]

    @model_validator(mode="after")
    def validate_size(self):
        # Walidator, a nie Field(min_length…): złamanie reguły kontraktu to 422 validation_error, a nie 400.
        if not 1 <= len(self.commands) <= MAX_BATCH_COMMANDS:
            raise ValueError(f"commands musi mieć od 1 do {MAX_BATCH_COMMANDS} komend")
        return self


class ClockUpdate(BaseModel):
    sim_time: datetime | None = None
    # Nowa symulacja także przy sim_time równym bieżącemu (reset urządzeń i kolejki komend).
    restart: bool = False
    running: bool | None = None
    speed: float | None = None
    # Zegar sam stanie, gdy dojdzie do tej chwili (koniec planu dnia). `null` kasuje zatrzymanie,
    # a brak pola zostawia je bez zmian; nowa doba (`sim_time`) zawsze je kasuje.
    stop_at: datetime | None = None

    @model_validator(mode="after")
    def validate_clock(self):
        if self.restart and self.sim_time is None:
            raise ValueError("restart wymaga sim_time")
        if self.sim_time is not None:
            _validate_sim_moment(self.sim_time, "sim_time")
        if self.stop_at is not None:
            _validate_sim_moment(self.stop_at, "stop_at")
        if self.speed is not None and not (math.isfinite(self.speed) and self.speed > 0):
            raise ValueError("speed musi być dodatnie")
        return self
