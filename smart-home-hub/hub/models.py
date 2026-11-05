from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

from device.models import DeviceConfig



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
        return self
