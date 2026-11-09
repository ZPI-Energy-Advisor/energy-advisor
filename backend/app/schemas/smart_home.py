from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator



# Modele kontraktu backend ↔ hub z docs/smart-home-api.md. Nieznane pola są ignorowane
# (domyślne zachowanie Pydantic), więc hub może rozszerzać odpowiedzi bez psucia backendu.


class AllowedWindow(BaseModel):
    # "from" jest słowem kluczowym Pythona; w JSON pole nazywa się jak w pliku urządzeń.
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str


class HubFlexibility(BaseModel):
    mode: str
    allowed_window: AllowedWindow | None = None
    max_shift_min: int | None = None


class HubProgram(BaseModel):
    program_id: str
    program_name: str
    duration_min: int
    profile_kwh: list[float]


class HubDevice(BaseModel):
    """Element rejestru w PUT /home/devices – ten sam kształt co urządzenie w pliku urządzeń."""

    device_id: str
    device_name: str
    device_type: str
    device_category: str
    max_power_kw: float | None = None
    flexibility: HubFlexibility
    programs: list[HubProgram] = []


class DeviceState(str, Enum):
    OFF = "off"
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    UNREACHABLE = "unreachable"


class RegisteredDevice(BaseModel):
    device_id: str
    port: int
    state: DeviceState


class HubDeviceStatus(BaseModel):
    device_id: str
    device_name: str
    port: int
    state: DeviceState
    program_id: str | None = None
    program_started_at: datetime | None = None
    program_ends_at: datetime | None = None
    # Brak wartości przy stanie unreachable: hub nie dostał odpowiedzi od urządzenia.
    power_kw: float | None = None
    energy_kwh: float | None = None


class HubDevicesStatus(BaseModel):
    sim_time: datetime | None = None
    devices: list[HubDeviceStatus]


class CommandType(str, Enum):
    ON = "on"
    OFF = "off"
    START_PROGRAM = "start_program"


class DeviceCommand(BaseModel):
    command: CommandType
    program_id: str | None = None
    start_at: datetime | None = None

    @model_validator(mode="after")
    def validate_program(self):
        if self.command == CommandType.START_PROGRAM:
            if not self.program_id:
                raise ValueError("start_program wymaga program_id")
        elif self.program_id is not None or self.start_at is not None:
            raise ValueError("program_id i start_at są dozwolone tylko przy start_program")
        if self.start_at is not None and self.start_at.tzinfo is None:
            raise ValueError("start_at musi zawierać strefę czasową")
        return self


class CommandResult(BaseModel):
    command_id: str
    device_id: str
    status: str
    state: DeviceState


class HubClock(BaseModel):
    sim_time: datetime
    running: bool
    speed: float


class HubEventType(str, Enum):
    DEVICE_STARTED = "device_started"
    DEVICE_FINISHED = "device_finished"
    ENERGY_REPORT = "energy_report"
    DEVICE_ERROR = "device_error"


class HubEvent(BaseModel):
    event_id: str
    type: HubEventType
    device_id: str
    sim_time: datetime
    data: dict[str, Any] = {}


class HubEventBatch(BaseModel):
    events: list[HubEvent]


class HomeSyncStatus(str, Enum):
    SYNCED = "synced"  # Hub ma rejestr zgodny z urządzeniami w bazie.
    PENDING = "pending"  # Rejestr czeka na wysyłkę; ponowi ją kolejna operacja właściciela.


class HomeSync(BaseModel):
    status: HomeSyncStatus
    synced_at: datetime | None = None
    error: str | None = None


class HomeStatus(BaseModel):
    connected: bool
    connected_at: datetime | None = None
    devices_count: int
    sync: HomeSync
