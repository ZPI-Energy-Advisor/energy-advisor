from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from device.models import DeviceConfig, Program



QUARTER_SECONDS = 900
QUARTER_HOURS = 0.25
PV_DEVICE_TYPE = "pv_inverter"
# Pola, które nie wpływają na pracę urządzenia; reszta zmienia się przez restart 
EDITABLE_FIELDS = {"device_name", "device_category"}

OFF = "off"
IDLE = "idle"
RUNNING = "running"


class DeviceError(Exception):
    """Błąd kontraktu: status HTTP, kod maszynowy i opis dla człowieka."""

    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


@dataclass
class Action:
    program: Program | None
    # None: akcja rozpoczęta przed pierwszym tickiem, zacznie się w czasie pierwszego ticka.
    started_at: datetime | None
    energy_kwh: float = 0.0


class DeviceDriver:
    """Stan jednego urządzenia. Czas płynie wyłącznie przez tick()

    Czas jest trzymany w UTC.
    Przesunięcie strefy z ostatniego ticka służy tylko do formatowania odpowiedzi.
    """

    def __init__(self, config: DeviceConfig):
        self.config = config
        self.state = OFF
        self.total_kwh = 0.0
        self.last_action: dict | None = None
        self._sim_time: datetime | None = None
        self._display_tz = timezone.utc
        self._action: Action | None = None
        self._events: list[dict] = []

    def turn_on(self) -> None:
        if self._program_running():
            raise DeviceError(409, "invalid_state", "Trwa program urządzenia")
        if self.state == RUNNING:
            return
        if self.config.programs:
            self.state = IDLE
        else:
            self.state = RUNNING
            self._begin_action(None)

    def turn_off(self) -> None:
        if self._action is not None:
            ended_at = self._sim_time
            self._finish_action(ended_at, interrupted=self._program_running())
        self.state = OFF

    def start_program(self, program_id: str) -> None:
        program = next((p for p in self.config.programs if p.program_id == program_id), None)
        if program is None:
            raise DeviceError(404, "program_not_found", f"Urządzenie nie ma programu {program_id!r}")
        if self._program_running():
            raise DeviceError(409, "invalid_state", "Trwa inny program urządzenia")
        self.state = RUNNING
        self._begin_action(program)

    def tick(self, sim_time: datetime) -> dict:
        if sim_time.tzinfo is None:
            raise DeviceError(422, "validation_error", "sim_time musi zawierać strefę czasową")
        now = sim_time.astimezone(timezone.utc)
        if self._sim_time is not None and now < self._sim_time:
            raise DeviceError(409, "stale_tick", "sim_time jest wcześniejszy niż ostatni tick")
        if now == self._sim_time:
            # Ponowiony tick. Zdarzenia z komend czekają na następny krok czasu.
            return self._tick_result(0.0, [])

        self._display_tz = sim_time.tzinfo
        energy_kwh = 0.0
        if self._sim_time is None:
            self._sim_time = now
            if self._action is not None:
                self._action.started_at = now
                self._emit_started(self._action)
        else:
            energy_kwh = self._advance(now)
            self._sim_time = now

        events, self._events = self._events, []
        return self._tick_result(energy_kwh, events)

    def status(self) -> dict:
        action = self._action
        program = action.program if action else None
        started_at = action.started_at if action else None
        ends_at = self._program_end(action) if program and started_at else None
        return {
            "device_id": self.config.device_id,
            "state": self.state,
            "program_id": program.program_id if program else None,
            "program_started_at": self._format(started_at) if program else None,
            "program_ends_at": self._format(ends_at),
            "power_kw": self._rounded(self._power_kw()),
            "energy_kwh": self._rounded(self.total_kwh),
            "sim_time": self._format(self._sim_time),
        }

    def energy(self) -> dict:
        return {
            "device_id": self.config.device_id,
            "total_kwh": self._rounded(self.total_kwh),
            "last_action": self.last_action,
        }

    def update_config(self, changes: dict) -> None:
        current = self.config.model_dump(by_alias=True)
        try:
            updated = DeviceConfig.model_validate({**current, **changes})
        except ValidationError as e:
            raise DeviceError(422, "validation_error", str(e)) from e
        if updated.model_dump(exclude=EDITABLE_FIELDS) != self.config.model_dump(exclude=EDITABLE_FIELDS):
            raise DeviceError(409, "config_requires_restart", "Zmiana tych pól wymaga restartu urządzenia")
        self.config = updated

    def _program_running(self) -> bool:
        return self._action is not None and self._action.program is not None

    def _begin_action(self, program: Program | None) -> None:
        self._action = Action(program=program, started_at=self._sim_time)
        if self._sim_time is not None:
            self._emit_started(self._action)

    def _advance(self, now: datetime) -> float:
        action = self._action
        if action is None:
            return 0.0

        if action.program is None:
            hours = (now - self._sim_time).total_seconds() / 3600
            energy_kwh = self._signed_power(self.config.max_power_kw) * hours
            self._add_energy(action, energy_kwh)
            return energy_kwh

        ends_at = self._program_end(action)
        end = min(now, ends_at)
        energy_kwh = (
            self._profile_energy(action.program, end - action.started_at)
            - self._profile_energy(action.program, self._sim_time - action.started_at)
        )
        self._add_energy(action, energy_kwh)
        if now >= ends_at:
            self._finish_action(ends_at, interrupted=False)
            self.state = IDLE
        return energy_kwh

    def _add_energy(self, action: Action, energy_kwh: float) -> None:
        action.energy_kwh += energy_kwh
        self.total_kwh += energy_kwh

    def _finish_action(self, ended_at: datetime | None, interrupted: bool) -> None:
        action, self._action = self._action, None
        if action.started_at is None:
            return  # Przed pierwszym tickiem czas nie płynął, więc akcji de facto nie było.

        program_id = action.program.program_id if action.program else None
        started_at = self._format(action.started_at)
        energy_kwh = self._rounded(action.energy_kwh)
        self.last_action = {
            "program_id": program_id,
            "started_at": started_at,
            "ended_at": self._format(ended_at),
            "energy_kwh": energy_kwh,
            "interrupted": interrupted,
        }
        self._emit("device_finished", ended_at, {
            "program_id": program_id,
            "started_at": started_at,
            "energy_kwh": energy_kwh,
            "interrupted": interrupted,
        })

    def _emit_started(self, action: Action) -> None:
        program_id = action.program.program_id if action.program else None
        self._emit("device_started", action.started_at, {"program_id": program_id})

    def _emit(self, event_type: str, sim_time: datetime, data: dict) -> None:
        self._events.append({"type": event_type, "sim_time": self._format(sim_time), "data": data})

    def _tick_result(self, energy_kwh: float, events: list[dict]) -> dict:
        return {
            "device_id": self.config.device_id,
            "state": self.state,
            "power_kw": self._rounded(self._power_kw()),
            "energy_kwh": self._rounded(energy_kwh),
            "events": events,
        }

    def _power_kw(self) -> float:
        action = self._action
        if action is None:
            return 0.0
        if action.program is None:
            return self._signed_power(self.config.max_power_kw)

        elapsed = self._sim_time - action.started_at if action.started_at else timedelta(0)
        quarter = int(elapsed.total_seconds() // QUARTER_SECONDS)
        return action.program.profile_kwh[quarter] / QUARTER_HOURS

    def _signed_power(self, power_kw: float) -> float:
        return -power_kw if self.config.device_type == PV_DEVICE_TYPE else power_kw

    def _format(self, value: datetime | None) -> str | None:
        return value.astimezone(self._display_tz).isoformat() if value else None

    @staticmethod
    def _program_end(action: Action) -> datetime:
        return action.started_at + timedelta(minutes=action.program.duration_min)

    @staticmethod
    def _profile_energy(program: Program, elapsed: timedelta) -> float:
        """Energia programu od startu do `elapsed`; w kwadransie energia rośnie liniowo."""
        quarter, seconds = divmod(elapsed.total_seconds(), QUARTER_SECONDS)
        quarter = int(quarter)
        if quarter >= len(program.profile_kwh):
            return sum(program.profile_kwh)
        return sum(program.profile_kwh[:quarter]) + program.profile_kwh[quarter] * seconds / QUARTER_SECONDS

    @staticmethod
    def _rounded(value: float) -> float:
        return round(value, 6) + 0.0  # + 0.0 zamienia -0.0 na 0.0
