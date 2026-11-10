from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator



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
    # Przebieg symulacji: zmienia go ustawienie czasu i restart huba.
    simulation_id: str | None = None


class HubEventType(str, Enum):
    DEVICE_STARTED = "device_started"
    DEVICE_FINISHED = "device_finished"
    ENERGY_REPORT = "energy_report"
    DEVICE_ERROR = "device_error"


# Hub wysyła partie po 500 zdarzeń; limit chroni backend przed jednym ogromnym żądaniem.
MAX_EVENTS_PER_BATCH = 1000


class EnergyReport(BaseModel):
    """`data` zdarzenia energy_report: energia urządzenia w kroku [interval_start, sim_time)."""

    interval_start: AwareDatetime
    energy_kwh: float = Field(allow_inf_nan=False)


class HubEvent(BaseModel):
    """Zdarzenie z webhooka huba. Typ spoza HubEventType jest przyjmowany i zapisywany bez interpretacji,
    żeby nowszy hub nie tracił całej partii, w tym energii."""

    event_id: str = Field(min_length=1, max_length=64)
    simulation_id: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=32)
    device_id: str = Field(min_length=1, max_length=100)
    sim_time: AwareDatetime
    data: dict[str, Any] = {}

    @model_validator(mode="after")
    def validate_energy_report(self):
        report = self.energy_report
        if report is not None and report.interval_start >= self.sim_time:
            raise ValueError("interval_start musi być wcześniejszy niż sim_time")
        return self

    @property
    def energy_report(self) -> EnergyReport | None:
        if self.type != HubEventType.ENERGY_REPORT.value:
            return None
        return EnergyReport.model_validate(self.data)


class HubEventBatch(BaseModel):
    events: list[HubEvent] = Field(max_length=MAX_EVENTS_PER_BATCH)


class HubEventsAccepted(BaseModel):
    accepted: int  # Zapisane teraz.
    duplicates: int  # Zapisane już wcześniej (ponowiona partia), pominięte.


class HomeClockState(BaseModel):
    sim_time: datetime
    running: bool
    speed: float


class HomeDeviceState(BaseModel):
    device_id: str
    device_name: str
    state: DeviceState
    program_id: str | None = None
    program_started_at: datetime | None = None
    program_ends_at: datetime | None = None
    power_kw: float | None = None
    # Z zdarzeń energy_report bieżącej doby symulacji, a nie z licznika huba, który zeruje restart urządzenia.
    energy_today_kwh: float


class HomePower(BaseModel):
    consumption_kw: float
    production_kw: float
    net_kw: float  # Pobór z sieci (dodatni) albo oddawanie do sieci (ujemny).


class HomeEnergyToday(BaseModel):
    day_start: datetime
    until: datetime
    consumption_kwh: float
    production_kwh: float
    net_kwh: float
    # Energia pobrana z sieci (dodatni bilans kwadransu) w cenach kwadransów taryfy z profilu, bez opłat stałych.
    grid_import_kwh: float
    cost_pln: float | None = None
    cost_error: str | None = None


class HomeState(BaseModel):
    hub_available: bool
    simulation_id: str | None = None
    clock: HomeClockState | None = None
    power: HomePower | None = None
    devices: list[HomeDeviceState] = []
    today: HomeEnergyToday | None = None


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
