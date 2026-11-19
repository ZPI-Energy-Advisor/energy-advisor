"""Rachunek przed i po planie w przebiegu symulacji (ZP-114).

Drugiej symulacji „bez planu” nie robimy: plan (ZP-112) ma dla każdej akcji start bazowy, czyli to, co dom
robi bez planu (zwykła godzina z historii, ładowanie od podłączenia auta, termostat bojlera, bloki pompy
z historii). Przy starcie przebiegu wyceniamy go cenami kwadransów planu (`PlanRunActionOut.cost_before`).
Wariant z planem to energia urządzenia zmierzona w symulacji (energy_report), kwadrans po kwadransie,
wyceniona tymi samymi cenami.

Porównanie obejmuje tylko urządzenia z planu, tak jak oszczędność na ekranie planu, i liczymy je per
urządzenie. Urządzenie wypada z porównania, gdy którakolwiek jego akcja ma odchylenie, które zmienia jego
pracę: hub odrzucił komendę, urządzenie zgłosiło awarię, ktoś je ręcznie wyłączył w trakcie (`interrupted`)
albo włączył poza planem (device_started z obcym `command_id`). Urządzenie z akcjami po `until` (raport
w trakcie albo po „Zakończ”) czeka w `pending`. Inne zużycie niż w planie i przekroczenie limitu przyłącza
są na liście odchyleń, ale nie wykluczają: to jest właśnie wynik wykonania planu.

Urządzenia stałe, włączane ręcznie z „Mój dom”, i produkcja PV są w osobnych sekcjach i nie zmieniają
oszczędności. Koszty to energia razy cena kwadransu, bez bilansowania z PV: tak samo liczy plan.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.parsers.devices import LOCAL_TIMEZONE
from app.repositories.home_event_repository import DeviceActionEvent, DeviceErrorEvent
from app.schemas.plan_run import (
    PlanRunActionOut,
    PlanRunCostDeviceOut,
    PlanRunCostOut,
    PlanRunDeviationOut,
    PlanRunDeviceRefOut,
    PlanRunManualDeviceOut,
    PlanRunPvOut,
)
from app.schemas.smart_home import HubCommandStatus
from app.services.home_state_service import DayEnergy


SLOT = timedelta(minutes=15)
SLOT_HOURS = SLOT.total_seconds() / 3600
# Zużycie inne niż w planie: o ponad 1% (jak tolerancja testów wykonania planu), a dla małych akcji
# ponad zaokrąglenie energii pozycji planu do 0,01 kWh.
ENERGY_TOLERANCE = 0.01
ENERGY_TOLERANCE_KWH = 0.01
# Pobór w kwadransie liczony z energii: drobne nadwyżki to zaokrąglenia mocy w hubie.
GRID_TOLERANCE_KW = 0.01
# Odchylenia, po których urządzenie nie pracowało według planu, więc jego koszt nic nie mówi o planie.
EXCLUDING = ("rejected", "device_error", "interrupted", "manual_start")
STARTED = "device_started"
FINISHED = "device_finished"


@dataclass(frozen=True)
class RunEnergy:
    """Wejście rachunku: to, co wysłaliśmy (akcje z kosztami bez planu), i to, co zaszło w symulacji."""

    actions: list[PlanRunActionOut]
    # Cena kwadransu planu (zł/kWh) po początku kwadransu w UTC.
    prices: dict[datetime, float]
    max_grid_kw: float | None
    energy: DayEnergy
    events: list[DeviceActionEvent]
    errors: list[DeviceErrorEvent]
    names: dict[str, str]
    # Urządzenia pracujące same, poza porównaniem i poza „ręcznie włączonymi”: przebiegi z historii
    # (PV, odznaczone pompa ciepła i bojler) oraz każde PV.
    background: set[str]
    pv_devices: set[str]
    until: datetime
    complete: bool


def profile_cost(profile_kwh: list[float], start: datetime, prices: dict[datetime, float]) -> float | None:
    """Koszt profilu po kwadransach od `start`; None, gdy brak ceny któregoś kwadransu z energią."""
    total = 0.0
    for index, kwh in enumerate(profile_kwh):
        if not kwh:
            continue
        price = prices.get(start + index * SLOT)
        if price is None:
            return None
        total += kwh * price
    return total


def _slots_cost(slots: dict[datetime, float], prices: dict[datetime, float]) -> float:
    # Pomiar jest w zakresie planu, a plan ma ceny wszystkich jego kwadransów.
    return sum(kwh * prices.get(slot, 0.0) for slot, kwh in slots.items())


def _money(value: float) -> float:
    return round(value, 2) + 0.0  # + 0.0 zamienia -0.0 na 0.0


def _kwh(value: float) -> float:
    return round(value, 3) + 0.0


def _local(moment: datetime | None) -> datetime | None:
    return moment.astimezone(LOCAL_TIMEZONE) if moment else None


def _number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def cost_report(run: RunEnergy) -> PlanRunCostOut:
    by_device: dict[str, list[PlanRunActionOut]] = defaultdict(list)
    for action in run.actions:
        by_device[action.device_id].append(action)
    names = {**run.names, **{action.device_id: action.device_name for action in run.actions}}
    deviations = [
        *_command_deviations(run.actions),
        *_error_deviations(run.errors, set(by_device), names, run.until),
        *_event_deviations(run.events, run.actions, names),
    ]
    excluded = {deviation.device_id for deviation in deviations if deviation.excluded}

    devices: list[PlanRunCostDeviceOut] = []
    pending: list[PlanRunDeviceRefOut] = []
    for device_id, actions in by_device.items():
        if device_id in excluded:
            continue
        if max(action.end for action in actions) > run.until:
            pending.append(PlanRunDeviceRefOut(device_id=device_id, device_name=names[device_id]))
            continue
        slots = run.energy.by_device_slot.get(device_id, {})
        planned_kwh = sum(action.energy_kwh for action in actions)
        after_kwh = sum(slots.values())
        if abs(after_kwh - planned_kwh) > max(planned_kwh * ENERGY_TOLERANCE, ENERGY_TOLERANCE_KWH):
            deviations.append(PlanRunDeviationOut(
                kind="energy_mismatch", device_id=device_id, device_name=names[device_id],
                message=f"Zużyło {_number(after_kwh)} kWh, a według planu {_number(planned_kwh)} kWh.",
            ))
        cost_before = sum(action.cost_before or 0.0 for action in actions)
        cost_after = _slots_cost(slots, run.prices)
        devices.append(PlanRunCostDeviceOut(
            device_id=device_id,
            device_name=names[device_id],
            kind=actions[0].kind,
            energy_before_kwh=_kwh(sum(action.energy_before_kwh or 0.0 for action in actions)),
            energy_after_kwh=_kwh(after_kwh),
            cost_before=_money(cost_before),
            planned_cost=_money(sum(action.planned_cost or 0.0 for action in actions)),
            cost_after=_money(cost_after),
            saving=_money(cost_before - cost_after),
        ))

    deviations.extend(_grid_deviations(run.energy, run.max_grid_kw))
    manual = _manual(run, set(by_device), names)
    cost_before = sum(device.cost_before for device in devices)
    cost_after = sum(device.cost_after for device in devices)
    saving = cost_before - cost_after
    return PlanRunCostOut(
        complete=run.complete,
        until=_local(run.until),
        cost_before=_money(cost_before),
        cost_after=_money(cost_after),
        planned_cost=_money(sum(device.planned_cost for device in devices)),
        saving=_money(saving),
        saving_percent=round(saving / cost_before * 100, 1) if cost_before > 0 else None,
        devices=devices,
        excluded=[
            PlanRunDeviceRefOut(device_id=device_id, device_name=names[device_id])
            for device_id in by_device if device_id in excluded
        ],
        pending=pending,
        manual=manual,
        manual_cost=_money(sum(device.cost for device in manual)),
        pv=_pv(run, set(by_device)),
        deviations=sorted(deviations, key=lambda deviation: (deviation.sim_time is None, deviation.sim_time)),
    )


def _command_deviations(actions: list[PlanRunActionOut]) -> list[PlanRunDeviationOut]:
    return [
        PlanRunDeviationOut(
            kind="rejected", device_id=action.device_id, device_name=action.device_name,
            sim_time=_local(action.start), excluded=True,
            message=f"Hub nie przyjął komendy: {action.detail or action.code}.",
        )
        for action in actions
        if action.status == HubCommandStatus.REJECTED
    ]


def _error_deviations(
    errors: list[DeviceErrorEvent], planned: set[str], names: dict[str, str], until: datetime,
) -> list[PlanRunDeviationOut]:
    """Awarie wszystkich urządzeń; z porównania wypada tylko urządzenie z planu."""
    return [
        PlanRunDeviationOut(
            kind="device_error", device_id=error.device_id, device_name=names.get(error.device_id, error.device_id),
            sim_time=_local(error.sim_time), excluded=error.device_id in planned,
            message=error.message or error.code,
        )
        for error in errors
        if error.sim_time <= until
    ]


def _event_deviations(
    events: list[DeviceActionEvent], actions: list[PlanRunActionOut], names: dict[str, str],
) -> list[PlanRunDeviationOut]:
    """Ręczne przełączenia urządzeń z planu: wyłączenie w trakcie pracy i włączenie spoza komend planu."""
    planned_commands = {action.command_id for action in actions if action.command_id}
    deviations = []
    for event in events:
        if event.type == STARTED and event.data.get("command_id") not in planned_commands:
            deviations.append(PlanRunDeviationOut(
                kind="manual_start", device_id=event.device_id, device_name=names[event.device_id],
                sim_time=_local(event.sim_time), excluded=True, message="Włączone ręcznie poza planem.",
            ))
        elif event.type == FINISHED and event.data.get("interrupted"):
            deviations.append(PlanRunDeviationOut(
                kind="interrupted", device_id=event.device_id, device_name=names[event.device_id],
                sim_time=_local(event.sim_time), excluded=True, message="Wyłączone ręcznie w trakcie pracy.",
            ))
    return deviations


def _grid_deviations(energy: DayEnergy, max_grid_kw: float | None) -> list[PlanRunDeviationOut]:
    """Kwadranse z poborem z sieci ponad limit przyłącza (plan razem z ręcznymi włączeniami), sąsiednie razem."""
    if not max_grid_kw:
        return []
    periods: list[list] = []  # [początek, koniec, moc szczytowa]
    for slot in sorted(energy.by_slot):
        power = energy.by_slot[slot] / SLOT_HOURS
        if power <= max_grid_kw + GRID_TOLERANCE_KW:
            continue
        if periods and periods[-1][1] == slot:
            periods[-1][1] = slot + SLOT
            periods[-1][2] = max(periods[-1][2], power)
        else:
            periods.append([slot, slot + SLOT, power])
    return [
        PlanRunDeviationOut(
            kind="grid_limit", sim_time=_local(start), end=_local(end),
            message=f"Pobór z sieci do {_number(peak)} kW, a limit przyłącza to {_number(max_grid_kw)} kW.",
        )
        for start, end, peak in periods
    ]


def _manual(run: RunEnergy, planned: set[str], names: dict[str, str]) -> list[PlanRunManualDeviceOut]:
    manual = []
    for device_id, slots in sorted(run.energy.by_device_slot.items()):
        if device_id in planned or device_id in run.background:
            continue
        energy_kwh = sum(slots.values())
        if energy_kwh <= 0:
            continue
        manual.append(PlanRunManualDeviceOut(
            device_id=device_id,
            device_name=names.get(device_id, device_id),
            energy_kwh=_kwh(energy_kwh),
            cost=_money(_slots_cost(slots, run.prices)),
        ))
    return manual


def _pv(run: RunEnergy, planned: set[str]) -> PlanRunPvOut | None:
    """Produkcja PV i jej autokonsumpcja w kwadransie; część przypada na plan w proporcji do jego zużycia."""
    production: dict[datetime, float] = defaultdict(float)
    consumption: dict[datetime, float] = defaultdict(float)
    plan_consumption: dict[datetime, float] = defaultdict(float)
    for device_id, slots in run.energy.by_device_slot.items():
        for slot, kwh in slots.items():
            if device_id in run.pv_devices:
                production[slot] -= kwh
            elif kwh > 0:
                consumption[slot] += kwh
                if device_id in planned:
                    plan_consumption[slot] += kwh
    total = sum(max(kwh, 0.0) for kwh in production.values())
    if total <= 0:
        return None
    self_consumption = plan_from_pv = 0.0
    for slot, produced in production.items():
        used = min(max(produced, 0.0), consumption.get(slot, 0.0))
        self_consumption += used
        if used:
            plan_from_pv += used * plan_consumption.get(slot, 0.0) / consumption[slot]
    return PlanRunPvOut(
        production_kwh=_kwh(total),
        self_consumption_kwh=_kwh(self_consumption),
        plan_from_pv_kwh=_kwh(plan_from_pv),
        plan_kwh=_kwh(sum(sum(run.energy.by_device_slot.get(device_id, {}).values()) for device_id in planned)),
    )
