"""Urządzenia, które w dobie planu pracują same (ZP-120): produkcja PV oraz pompa ciepła i bojler spoza planu.

Planer liczy je raz, przy układaniu planu, i zapisuje w planie (`background`). Wykonanie planu w symulacji
(ZP-113) wysyła do huba dokładnie te przebiegi, więc plan i symulacja mają tę samą energię, nawet gdy prognoza
pogody zmieni się między ułożeniem a uruchomieniem planu.

- PV: produkcja z prognozy pogody na dobę planu (ZP-118; dla doby z przeszłości z archiwum). Bez prognozy albo
  bez paneli w profilu: doba dnia referencyjnego, jak przed ZP-120.
- Pompa ciepła spoza planu: przebiegi dnia referencyjnego przeskalowane do temperatury doby planu, tą samą
  funkcją co pompa w planie (ZP-119).
- Bojler spoza planu: doba dnia referencyjnego (zależy od zwyczajów, nie od pogody).

Dzień referencyjny liczymy dla każdego urządzenia osobno: dzień startu jego ostatniej akcji przed dobą planu,
a bez takiej (plan demo sprzed całej historii) ostatniej w ogóle. Tylko doba 00:00–24:00, bez nocy po niej.
"""

import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from app.repositories.home_repository import HomeRepository
from app.schemas.user_profile import UserProfile
from app.services.heat_pump import HEAT_PUMP_TYPE, WATER_HEATER_TYPE, HeatPumpService, Home
from app.services.home_control_service import day_midnight
from app.services.home_replay import ReplayRun, moved_runs, replay_runs
from app.services.plan_history import local_day
from app.services.pv_forecast import NoPvInstallationError, PvForecastService, PvForecastUnavailableError

logger = logging.getLogger(__name__)

PV_TYPE = "pv_inverter"
THERMOSTAT_TYPES = (HEAT_PUMP_TYPE, WATER_HEATER_TYPE)
SLOT = timedelta(minutes=15)
FORECAST = "forecast"
HISTORY = "history"


@dataclass
class BackgroundDevice:
    """Urządzenie pracujące samo: skąd jest jego doba (`source`), dzień referencyjny i energia (ujemna dla PV)."""

    device_id: str
    device_type: str
    source: str
    history_day: date | None
    reference_kwh: float
    kwh: float
    reason: str | None = None
    # PV z prognozy przy panelach szacunkowych: True, a `effective_kwp` to moc dopasowana do produkcji z plików.
    estimated_panels: bool = False
    effective_kwp: float | None = None


@dataclass
class DayBackground:
    runs: list[ReplayRun] = field(default_factory=list)
    devices: list[BackgroundDevice] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # O ile pompa spoza planu pobierze w kwadransie więcej niż w dniu referencyjnym (kWh): zapas w limicie przyłącza.
    extra_load: dict[datetime, float] = field(default_factory=dict)
    # Doba planu jest już miniona (plan demo), więc pogoda jest z archiwum, a nie z prognozy.
    past: bool = False

    def history_days(self) -> dict[str, date]:
        return {device.device_id: device.history_day for device in self.devices if device.history_day}

    def to_json(self) -> dict:
        return {
            "runs": [
                {"device_id": run.device_id, "start": run.start.isoformat(), "ref": run.ref,
                 "profile_kwh": [round(kwh, 4) + 0.0 for kwh in run.profile_kwh]}
                for run in self.runs
            ],
            "devices": [
                {"device_id": device.device_id, "device_type": device.device_type, "source": device.source,
                 "history_day": device.history_day.isoformat() if device.history_day else None,
                 "reference_kwh": round(device.reference_kwh, 2) + 0.0, "kwh": round(device.kwh, 2) + 0.0,
                 "reason": device.reason, "estimated_panels": device.estimated_panels,
                 "effective_kwp": device.effective_kwp}
                for device in self.devices
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> "DayBackground":
        return cls(
            runs=[
                ReplayRun(device_id=run["device_id"], start=datetime.fromisoformat(run["start"]), ref=run["ref"],
                          profile_kwh=list(run["profile_kwh"]))
                for run in data.get("runs", [])
            ],
            devices=[
                BackgroundDevice(
                    device_id=device["device_id"], device_type=device["device_type"], source=device["source"],
                    history_day=date.fromisoformat(device["history_day"]) if device.get("history_day") else None,
                    reference_kwh=device["reference_kwh"], kwh=device["kwh"], reason=device.get("reason"),
                    estimated_panels=device.get("estimated_panels", False), effective_kwp=device.get("effective_kwp"),
                )
                for device in data.get("devices", [])
            ],
        )


def history_runs(home: HomeRepository, user_id, plan_date: date, device_ids: list[str]) -> tuple[dict[str, date], dict[str, list[ReplayRun]]]:
    """Doba dnia referencyjnego każdego urządzenia przeniesiona na dobę planu: dni i przebiegi po urządzeniu."""
    plan_start = day_midnight(plan_date).astimezone(timezone.utc)
    starts = home.last_action_starts(user_id, device_ids, plan_start)
    starts |= home.last_action_starts(user_id, [d for d in device_ids if d not in starts])
    days = {device_id: local_day(start) for device_id, start in starts.items()}
    runs: dict[str, list[ReplayRun]] = {}
    for device_id, source in days.items():
        slots = home.action_slots(
            user_id, [device_id],
            day_midnight(source).astimezone(timezone.utc),
            day_midnight(source + timedelta(days=1)).astimezone(timezone.utc),
        )
        runs[device_id] = moved_runs(replay_runs(slots), source, plan_date)
    return days, runs


def _energy(runs: list[ReplayRun]) -> float:
    return sum(sum(run.profile_kwh) for run in runs)


def _capped(values: list[float], cap: float) -> tuple[list[float], float]:
    """Wartości do mocy `cap`; nadmiar trafia najpierw w wolne miejsce tych samych kwadransów."""
    spill = sum(max(value - cap, 0.0) for value in values)
    values = [min(value, cap) for value in values]
    for index, value in enumerate(values):
        if spill <= 1e-9:
            break
        added = min(cap - value, spill)
        values[index] += added
        spill -= added
    return values, spill


def scale_runs(runs: list[ReplayRun], target_kwh: float, cap_kwh: float | None, day_end: datetime) -> list[ReplayRun]:
    """Przebiegi przeskalowane do `target_kwh` z zachowaniem kształtu. Przy mocy `cap_kwh` na kwadrans nadmiar
    wypełnia wolne miejsce przebiegu, a potem wydłuża go do następnego przebiegu albo końca doby; czego się nie da,
    przepada (pompa pracuje bez przerwy)."""
    total = _energy(runs)
    if total <= 0:
        return runs
    factor = max(target_kwh, 0.0) / total
    ordered = sorted(runs, key=lambda run: run.start)
    result = []
    for index, run in enumerate(ordered):
        values = [kwh * factor for kwh in run.profile_kwh]
        if cap_kwh:
            values, spill = _capped(values, cap_kwh)
            limit = ordered[index + 1].start if index + 1 < len(ordered) else day_end
            free = max(int((limit - run.end) / SLOT), 0)
            while spill > 1e-9 and free > 0:
                values.append(min(cap_kwh, spill))
                spill -= values[-1]
                free -= 1
        result.append(replace(run, profile_kwh=values))
    return result


def _pv_runs(quarters, devices: list[str], shares: dict[str, float], plan_date: date) -> list[ReplayRun]:
    runs = []
    for device_id in devices:
        values = [-q.kwh * shares[device_id] for q in quarters]
        first = next((index for index, value in enumerate(values) if value < 0), None)
        if first is None:
            continue
        last = max(index for index, value in enumerate(values) if value < 0)
        runs.append(ReplayRun(
            device_id=device_id, start=quarters[first].start, ref=f"pv_forecast_{plan_date.isoformat()}",
            profile_kwh=values[first:last + 1],
        ))
    return runs


class DayBackgroundService:
    def __init__(
        self,
        home: HomeRepository,
        profile_of: Callable[[object], UserProfile | None],
        pv_forecasts: PvForecastService | None = None,
        heat_pumps: HeatPumpService | None = None,
    ):
        self.home = home
        self.profile_of = profile_of
        self.pv_forecasts = pv_forecasts
        self.heat_pumps = heat_pumps

    def build(self, user_id, plan_date: date, planned_devices: set[str], base_info: dict | None = None) -> DayBackground:
        devices = [
            device_id for device_id in self.home.device_ids_of_types(user_id, (PV_TYPE, *THERMOSTAT_TYPES))
            if device_id not in planned_devices
        ]
        if not devices:
            return DayBackground()
        info = self.home.device_info(user_id, devices)
        types = {device_id: device_type for device_id, (device_type, _) in info.items()}
        days, history = history_runs(self.home, user_id, plan_date, devices)
        background = DayBackground(past=self.pv_forecasts is not None and plan_date < self.pv_forecasts.weather.today())
        day_end = day_midnight(plan_date + timedelta(days=1)).astimezone(timezone.utc)

        pv = [device_id for device_id in devices if types.get(device_id) == PV_TYPE]
        if pv:
            self._pv(background, user_id, plan_date, pv, days, history)
        for device_id in devices:
            if device_id in pv or device_id not in days:
                continue
            runs = history.get(device_id, [])
            reference = _energy(runs)
            reason = None
            if types.get(device_id) == HEAT_PUMP_TYPE and self.heat_pumps is not None and runs:
                scaled = self._heat_pump(user_id, plan_date, days[device_id], runs, reference, info[device_id][1],
                                         day_end, base_info)
                if scaled is not None:
                    background.runs.extend(scaled)
                    background.devices.append(BackgroundDevice(device_id, HEAT_PUMP_TYPE, FORECAST, days[device_id],
                                                               reference, _energy(scaled)))
                    self._add_extra(background, runs, scaled)
                    continue
                reason = "no_weather"
            background.runs.extend(runs)
            background.devices.append(BackgroundDevice(device_id, types.get(device_id, ""), HISTORY,
                                                       days[device_id], reference, reference, reason))
        background.runs.sort(key=lambda run: (run.start, run.device_id))
        return background

    def _pv(self, background: DayBackground, user_id, plan_date: date, devices: list[str],
            days: dict[str, date], history: dict[str, list[ReplayRun]]) -> None:
        reference = {device_id: _energy(history.get(device_id, [])) for device_id in devices}
        forecast, reason = None, None
        profile = self.profile_of(user_id)
        if self.pv_forecasts is None:
            reason = "no_forecast"
        elif profile is None:
            reason = "no_profile"
        else:
            try:
                forecast = self.pv_forecasts.forecast(user_id, profile, plan_date)
            except NoPvInstallationError:
                reason = "no_installation"
            except PvForecastUnavailableError:
                reason = "no_weather"
        if forecast is None:
            for device_id in devices:
                runs = history.get(device_id, [])
                background.runs.extend(runs)
                if device_id in days:
                    background.devices.append(BackgroundDevice(device_id, PV_TYPE, HISTORY, days[device_id],
                                                               reference[device_id], reference[device_id], reason))
            return
        produced = -sum(reference.values())
        shares = {
            device_id: (-reference[device_id] / produced) if produced > 0 else 1 / len(devices)
            for device_id in devices
        }
        runs = _pv_runs(forecast.quarters, devices, shares, plan_date)
        background.runs.extend(runs)
        for device_id in devices:
            energy = _energy([run for run in runs if run.device_id == device_id])
            background.devices.append(BackgroundDevice(
                device_id, PV_TYPE, FORECAST, days.get(device_id), reference[device_id], energy, forecast.basis,
                estimated_panels=forecast.estimated_installation, effective_kwp=forecast.calibration.effective_kwp,
            ))

    def _heat_pump(self, user_id, plan_date: date, source: date, runs: list[ReplayRun], reference: float,
                   power_kw: float | None, day_end: datetime, base_info: dict | None) -> list[ReplayRun] | None:
        heating = self.heat_pumps.plan_day(user_id, Home.of(base_info or {}), source, reference, plan_date)
        if heating is None or heating.plan is None:
            return None
        return scale_runs(runs, heating.kwh, power_kw * 0.25 if power_kw else None, day_end)

    @staticmethod
    def _add_extra(background: DayBackground, before: list[ReplayRun], after: list[ReplayRun]) -> None:
        def per_slot(runs):
            slots: dict[datetime, float] = {}
            for run in runs:
                for index, kwh in enumerate(run.profile_kwh):
                    moment = run.start + index * SLOT
                    slots[moment] = slots.get(moment, 0.0) + kwh
            return slots

        old, new = per_slot(before), per_slot(after)
        for moment, kwh in new.items():
            extra = kwh - old.get(moment, 0.0)
            if extra > 1e-9:
                background.extra_load[moment] = background.extra_load.get(moment, 0.0) + extra
