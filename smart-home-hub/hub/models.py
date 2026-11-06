import math
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, model_validator

from device.models import DeviceConfig


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


class DeviceCommand(BaseModel):
    command: Literal["on", "off", "start_program"]
    program_id: str | None = None
    start_at: datetime | None = None

    @model_validator(mode="after")
    def validate_program(self):
        if self.command == "start_program":
            if not self.program_id:
                raise ValueError("start_program wymaga program_id")
        elif self.program_id is not None or self.start_at is not None:
            raise ValueError("program_id i start_at są dozwolone tylko przy start_program")
        if self.start_at is not None:
            _validate_sim_moment(self.start_at, "start_at")
        return self


class ClockUpdate(BaseModel):
    sim_time: datetime | None = None
    running: bool | None = None
    speed: float | None = None

    @model_validator(mode="after")
    def validate_clock(self):
        if self.sim_time is not None:
            _validate_sim_moment(self.sim_time, "sim_time")
        if self.speed is not None and not (math.isfinite(self.speed) and self.speed > 0):
            raise ValueError("speed musi być dodatnie")
        return self
