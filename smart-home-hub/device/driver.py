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
    """Akcja urządzenia: praca stałą mocą (`profile_kwh` None), program albo przebieg z własnym profilem."""

    program: Program | None
    # None: akcja rozpoczęta przed pierwszym tickiem, zacznie się w czasie pierwszego ticka.
    started_at: datetime | None
    energy_kwh: float = 0.0
    # Polecenie huba, które zaczęło akcję; wraca w zdarzeniu device_started.
    command_id: str | None = None
    # Energia w kolejnych kwadransach: z programu albo z POST /run (np. akcja planu, profil PV).
    profile_kwh: list[float] | None = None
    # Identyfikator akcji przebiegu (np. z planu); wraca w zdarzeniach, żeby odróżnić ją od poleceń ręcznych.
    ref: str | None = None

    @property
    def is_run(self) -> bool:
        return self.program is None and self.profile_kwh is not None


class DeviceDriver:
    """Stan jednego urządzenia. Czas płynie wyłącznie przez tick()

    Czas jest trzymany w UTC.
    Przesunięcie strefy z ostatniego ticka służy tylko do formatowania odpowiedzi.
    """

    def __init__(self, config: DeviceConfig):
        self.config = config
        self.reset()

    def reset(self) -> None:
        """Stan jak po uruchomieniu: nowa symulacja może zacząć się przed ostatnim tickiem."""
        self.state = OFF
        self.total_kwh = 0.0
        self.last_action: dict | None = None
        self._sim_time: datetime | None = None
        self._display_tz = timezone.utc
        self._action: Action | None = None
        self._events: list[dict] = []

    def turn_on(self, command_id: str | None = None) -> None:
        if self._profile_running():
            raise DeviceError(409, "invalid_state", self._busy_message())
        if self.state == RUNNING:
            return
        if self.config.programs:
            self.state = IDLE
        else:
            self.state = RUNNING
            self._begin_action(None, command_id)

    def turn_off(self) -> None:
        if self._action is not None:
            ended_at = self._sim_time
            self._finish_action(ended_at, interrupted=self._profile_running())
        self.state = OFF

    def start_program(self, program_id: str, command_id: str | None = None) -> None:
        program = next((p for p in self.config.programs if p.program_id == program_id), None)
        if program is None:
            raise DeviceError(404, "program_not_found", f"Urządzenie nie ma programu {program_id!r}")
        if self._profile_running():
            raise DeviceError(409, "invalid_state", self._busy_message())
        self.state = RUNNING
        self._begin_action(program, command_id, profile_kwh=program.profile_kwh)

    def run_profile(self, profile_kwh: list[float], command_id: str | None = None, ref: str | None = None) -> None:
        """Praca według podanego profilu (kWh na kwadrans) i koniec po ostatnim kwadransie.

        Tak wykonujemy akcje bez programu: ładowanie EV z przerwami, grzanie bojlera i pompy ciepła
        w wybranych kwadransach, produkcję PV. Praca stałą mocą po ręcznym włączeniu ustępuje przebiegowi,
        bo plan ma pierwszeństwo; program albo inny przebieg go blokują.
        """
        if not profile_kwh:
            raise DeviceError(422, "validation_error", "profile_kwh musi mieć co najmniej jeden kwadrans")
        if self._profile_running():
            raise DeviceError(409, "invalid_state", self._busy_message())
        if self._action is not None:
            self._finish_action(self._sim_time, interrupted=False)
        self.state = RUNNING
        self._begin_action(None, command_id, profile_kwh=list(profile_kwh), ref=ref)

    def tick(self, sim_time: datetime) -> dict:
        if sim_time.tzinfo is None:
            raise DeviceError(422, "validation_error", "sim_time musi zawierać strefę czasową")
        now = sim_time.astimezone(timezone.utc)
        if self._sim_time is not None and now < self._sim_time:
            raise DeviceError(409, "stale_tick", "sim_time jest wcześniejszy niż ostatni tick")
        if now == self._sim_time:
            # Ponowiony tick. Zdarzenia z komend czekają na następny krok czasu.
            return self._tick_result(0.0, [], interval_start=now)

        self._display_tz = sim_time.tzinfo
        energy_kwh = 0.0
        previous = self._sim_time
        if previous is None:
            self._sim_time = now
            if self._action is not None:
                self._action.started_at = now
                self._emit_started(self._action)
        else:
            energy_kwh = self._advance(now)
            self._sim_time = now

        events, self._events = self._events, []
        return self._tick_result(energy_kwh, events, interval_start=previous)

    def status(self) -> dict:
        action = self._action
        program = action.program if action else None
        started_at = action.started_at if action else None
        ends_at = self._profile_end(action) if action and action.profile_kwh is not None and started_at else None
        run = None
        if action is not None and action.is_run:
            run = {"ref": action.ref, "started_at": self._format(started_at), "ends_at": self._format(ends_at)}
        return {
            "device_id": self.config.device_id,
            "state": self.state,
            "program_id": program.program_id if program else None,
            "program_started_at": self._format(started_at) if program else None,
            "program_ends_at": self._format(ends_at) if program else None,
            "run": run,
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

    def _profile_running(self) -> bool:
        """Trwa program albo przebieg: akcja z profilem, której nie przerywa kolejne polecenie startu."""
        return self._action is not None and self._action.profile_kwh is not None

    def _busy_message(self) -> str:
        return "Trwa przebieg urządzenia" if self._action.is_run else "Trwa program urządzenia"

    def _begin_action(
        self, program: Program | None, command_id: str | None,
        profile_kwh: list[float] | None = None, ref: str | None = None,
    ) -> None:
        self._action = Action(
            program=program, started_at=self._sim_time, command_id=command_id, profile_kwh=profile_kwh, ref=ref,
        )
        if self._sim_time is not None:
            self._emit_started(self._action)

    def _advance(self, now: datetime) -> float:
        action = self._action
        if action is None:
            return 0.0

        if action.profile_kwh is None:
            hours = (now - self._sim_time).total_seconds() / 3600
            energy_kwh = self._signed_power(self.config.max_power_kw) * hours
            self._add_energy(action, energy_kwh)
            return energy_kwh

        ends_at = self._profile_end(action)
        end = min(now, ends_at)
        energy_kwh = (
            self._profile_energy(action.profile_kwh, end - action.started_at)
            - self._profile_energy(action.profile_kwh, self._sim_time - action.started_at)
        )
        self._add_energy(action, energy_kwh)
        if now >= ends_at:
            self._finish_action(ends_at, interrupted=False)
            # Po programie urządzenie czeka włączone; po przebiegu bez programu wraca do stanu wyłączonego.
            self.state = IDLE if self.config.programs else OFF
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
            "ref": action.ref,
        })

    def _emit_started(self, action: Action) -> None:
        program_id = action.program.program_id if action.program else None
        self._emit("device_started", action.started_at, {
            "program_id": program_id,
            "command_id": action.command_id,
            "ref": action.ref,
        })

    def _emit(self, event_type: str, sim_time: datetime, data: dict) -> None:
        self._events.append({"type": event_type, "sim_time": self._format(sim_time), "data": data})

    def _tick_result(self, energy_kwh: float, events: list[dict], interval_start: datetime | None) -> dict:
        """`interval_start`: początek kroku, za który jest `energy_kwh`; None przy pierwszym ticku."""
        return {
            "device_id": self.config.device_id,
            "state": self.state,
            "power_kw": self._rounded(self._power_kw()),
            "energy_kwh": self._rounded(energy_kwh),
            "interval_start": self._format(interval_start),
            "events": events,
        }

    def _power_kw(self) -> float:
        action = self._action
        if action is None:
            return 0.0
        if action.profile_kwh is None:
            return self._signed_power(self.config.max_power_kw)

        elapsed = self._sim_time - action.started_at if action.started_at else timedelta(0)
        quarter = int(elapsed.total_seconds() // QUARTER_SECONDS)
        # Znak z profilu: przebieg PV ma ujemną energię, a program zawsze dodatnią.
        return action.profile_kwh[min(quarter, len(action.profile_kwh) - 1)] / QUARTER_HOURS

    def _signed_power(self, power_kw: float) -> float:
        return -power_kw if self.config.device_type == PV_DEVICE_TYPE else power_kw

    def _format(self, value: datetime | None) -> str | None:
        return value.astimezone(self._display_tz).isoformat() if value else None

    @staticmethod
    def _profile_end(action: Action) -> datetime:
        return action.started_at + timedelta(seconds=QUARTER_SECONDS * len(action.profile_kwh))

    @staticmethod
    def _profile_energy(profile_kwh: list[float], elapsed: timedelta) -> float:
        """Energia profilu od startu do `elapsed`; w kwadransie energia rośnie liniowo."""
        quarter, seconds = divmod(elapsed.total_seconds(), QUARTER_SECONDS)
        quarter = int(quarter)
        if quarter >= len(profile_kwh):
            return sum(profile_kwh)
        return sum(profile_kwh[:quarter]) + profile_kwh[quarter] * seconds / QUARTER_SECONDS

    @staticmethod
    def _rounded(value: float) -> float:
        return round(value, 6) + 0.0  # + 0.0 zamienia -0.0 na 0.0
