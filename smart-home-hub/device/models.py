from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
