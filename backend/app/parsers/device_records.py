from dataclasses import dataclass, field
from datetime import datetime, time


@dataclass
class ProgramRecord:
    program_id: str
    name: str
    duration_min: int
    profile_kwh: list[float]


@dataclass
class ActionRecord:
    action_id: str
    start: datetime
    end: datetime
    energy_kwh: float
    slots_kwh: list[float]
    program_id: str | None = None
    plugged_in: datetime | None = None
    deadline: datetime | None = None


@dataclass
class DeviceRecord:
    device_id: str
    name: str
    device_type: str
    device_category: str
    flexibility_mode: str
    max_power_kw: float | None = None
    allowed_window_from: time | None = None
    allowed_window_to: time | None = None
    max_shift_min: int | None = None
    programs: list[ProgramRecord] = field(default_factory=list)
    actions: list[ActionRecord] = field(default_factory=list)
