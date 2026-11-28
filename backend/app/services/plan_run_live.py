"""Statystyki na żywo w czasie przebiegu planu (ZP-153), liczone przy odczycie z migawki przebiegu i zdarzeń
energii, bez pytania huba i pogody.

- Temperatura w domu z pompą ciepła: model domu z planera (`house_heating.House`, migawka przy starcie) liczony
  kwadrans po kwadransie na energii pompy zmierzonej w symulacji, bez grzania wody z planu. Ręczne wyłączenie
  pompy od razu obniża temperaturę.
- Pogoda w bieżącym kwadransie z pogody zapisanej w planie (prognoza albo archiwum dla planu idealnego).
- Panele od początku planu w bilansie godzinowym (jak `pv_balance.summary`): w każdej godzinie dom zużywa
  min(produkcja, zużycie), a reszta produkcji idzie do sieci. Zużycie to wszystkie urządzenia, także ręczne.
- Oszczędność do teraz: koszt urządzeń z planu bez planu (profil bazowy przycięty do `until`) i z planem
  (energia zmierzona), tym samym rachunkiem co raport (`plan_run_report`). Urządzenia w trakcie pracy też się
  liczą, a urządzenia z odchyleniem wypadają, jak w raporcie. Na końcu planu wynik to raport.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.parsers.devices import LOCAL_TIMEZONE
from app.schemas.plan_run import (
    PlanRunDeviceRefOut,
    PlanRunIndoorOut,
    PlanRunIndoorPointOut,
    PlanRunLiveOut,
    PlanRunPvHourOut,
    PlanRunPvLiveOut,
    PlanRunSavingLiveOut,
    PlanRunWeatherNowOut,
)
from app.services.heat_pump_model import heating_cop
from app.services.house_heating import House
from app.services.plan_run_report import RunEnergy, excluded_devices
from app.services.pv_balance import hour_of

SLOT = timedelta(minutes=15)
WATER_SUFFIX = "#woda"


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _slot_of(moment: datetime) -> datetime:
    moment = moment.astimezone(timezone.utc)
    return moment.replace(minute=moment.minute - moment.minute % 15, second=0, microsecond=0)


def _money(value: float) -> float:
    return round(value, 2) + 0.0


def _kwh(value: float) -> float:
    return round(value, 3) + 0.0


def live(run: RunEnergy, tariff: dict) -> PlanRunLiveOut:
    return PlanRunLiveOut(
        until=run.until.astimezone(LOCAL_TIMEZONE),
        indoor=_indoor(run, tariff.get("heat_pumps") or []),
        weather=_weather(run.until, tariff.get("weather")),
        pv=_pv(run),
        price_now=_now(run.until, run.prices.get),
        export_price_now=_now(run.until, lambda slot: run.balance.sell.get(hour_of(slot))) if run.balance is not None else None,
        saving=_saving(run),
    )


def _indoor(run: RunEnergy, pumps: list[dict]) -> list[PlanRunIndoorOut]:
    water: dict[str, dict[datetime, float]] = defaultdict(lambda: defaultdict(float))
    for action in run.actions:
        if action.action_id.endswith(WATER_SUFFIX) and action.profile_kwh:
            for index, kwh in enumerate(action.profile_kwh):
                water[action.device_id][action.start.astimezone(timezone.utc) + index * SLOT] += kwh
    result = []
    for pump in pumps:
        house = House(
            loss_kw_per_k=pump["loss_kw_per_k"], capacity_kwh_per_k=pump["capacity_kwh_per_k"],
            floor_heating=pump["floor_heating"], indoor_c=pump["indoor_c"],
        )
        measured = run.energy.by_device_slot.get(pump["device_id"], {})
        temp, at, plan_c = house.indoor_c, None, None
        points = []
        for quarter in pump["quarters"]:
            slot = _utc(quarter["start"])
            simulated = None
            if slot + SLOT <= run.until:
                electricity = max(measured.get(slot, 0.0) - water[pump["device_id"]].get(slot, 0.0), 0.0)
                temp = house.step(temp, quarter["outdoor"], electricity * heating_cop(quarter["outdoor"], house.floor_heating))
                at, plan_c, simulated = slot + SLOT, quarter["after"], round(temp, 2)
            points.append(PlanRunIndoorPointOut(
                start=slot.astimezone(LOCAL_TIMEZONE), plan_c=quarter["after"], temp_c=simulated,
            ))
        if at is None:
            continue
        result.append(PlanRunIndoorOut(
            device_id=pump["device_id"], device_name=pump["device_name"], at=at.astimezone(LOCAL_TIMEZONE),
            temp_c=round(temp, 1), plan_c=plan_c, set_c=house.indoor_c, band=pump["band"], points=points,
        ))
    return result


def _now(until: datetime, value_at):
    """Wartość w kwadransie zegara, a na samym końcu planu w ostatnim kwadransie."""
    value = value_at(_slot_of(until))
    return value if value is not None else value_at(_slot_of(until - timedelta(microseconds=1)))


def _weather(until: datetime, weather: dict | None) -> PlanRunWeatherNowOut | None:
    if not weather:
        return None
    by_slot = {_utc(q["start"]): q for q in weather["quarters"]}
    quarter = _now(until, by_slot.get)
    if quarter is None:
        return None
    return PlanRunWeatherNowOut(
        start=_utc(quarter["start"]).astimezone(LOCAL_TIMEZONE), temperature_c=quarter["temperature_c"],
        cloud_cover_pct=quarter["cloud_cover_pct"], past=bool(weather.get("past")),
    )


def _pv(run: RunEnergy) -> PlanRunPvLiveOut | None:
    production: dict[datetime, float] = defaultdict(float)
    consumption: dict[datetime, float] = defaultdict(float)
    for device_id, slots in run.energy.by_device_slot.items():
        for slot, kwh in slots.items():
            if device_id in run.pv_devices:
                production[hour_of(slot)] -= kwh
            elif kwh > 0:
                consumption[hour_of(slot)] += kwh
    if not run.pv_devices:
        return None
    planned: dict[datetime, float] = defaultdict(float)
    if run.balance is not None:
        for slot, kwh in run.balance.production.items():
            planned[hour_of(slot)] += kwh
    produced_total = self_total = export_total = value = 0.0
    for hour, produced in production.items():
        produced = max(produced, 0.0)
        own = min(produced, consumption.get(hour, 0.0))
        produced_total += produced
        self_total += own
        export_total += produced - own
        if run.balance is not None:
            value += (produced - own) * run.balance.sell.get(hour, 0.0)
    hours = [
        PlanRunPvHourOut(
            start=hour.astimezone(LOCAL_TIMEZONE),
            planned_kwh=_kwh(planned[hour]) if run.balance is not None else None,
            actual_kwh=_kwh(max(production.get(hour, 0.0), 0.0)) if hour < run.until else None,
        )
        for hour in sorted(set(planned) | {hour for hour, kwh in production.items() if kwh > 0})
    ]
    return PlanRunPvLiveOut(
        production_kwh=_kwh(produced_total), self_kwh=_kwh(self_total), export_kwh=_kwh(export_total),
        export_pln=_money(value) if run.balance is not None else None,
        planned_kwh=_kwh(sum(planned.values())) if run.balance is not None else None,
        hours=hours,
    )


def _baseline(run: RunEnergy, device_actions: list) -> dict[datetime, float]:
    """Profil bez planu do `until`; kwadrans, w którym jest `until`, w części, która już minęła. Po końcu planu
    cały profil, jak w raporcie (praca bez planu może trwać dłużej niż przebieg, np. zmywarka przez północ)."""
    slots: dict[datetime, float] = defaultdict(float)
    for action in device_actions:
        start = action.original_start.astimezone(timezone.utc)
        for index, kwh in enumerate(action.original_profile_kwh):
            slot = start + index * SLOT
            if not kwh or (slot >= run.until and not run.complete):
                continue
            share = 1.0 if run.complete else min((run.until - slot) / SLOT, 1.0)
            slots[slot] += kwh * share
    return slots


def _saving(run: RunEnergy) -> PlanRunSavingLiveOut | None:
    if any(action.original_profile_kwh is None or action.original_start is None for action in run.actions):
        return None
    by_device: dict[str, list] = defaultdict(list)
    for action in run.actions:
        by_device[action.device_id].append(action)
    excluded = excluded_devices(run)
    before = {device_id: _baseline(run, actions) for device_id, actions in by_device.items()}
    after = {device_id: dict(run.energy.by_device_slot.get(device_id, {})) for device_id in by_device}
    if run.balance is not None:
        before_cost = _allocated(run, before)
        after_cost = _allocated(run, after)
    else:
        before_cost = {device_id: _priced(run, slots) for device_id, slots in before.items()}
        after_cost = {device_id: _priced(run, slots) for device_id, slots in after.items()}
    counted = [device_id for device_id in by_device if device_id not in excluded]
    cost_before = sum(before_cost[device_id] for device_id in counted)
    cost_after = sum(after_cost[device_id] for device_id in counted)
    names = {action.device_id: action.device_name for action in run.actions}
    return PlanRunSavingLiveOut(
        cost_before=_money(cost_before),
        cost_after=_money(cost_after),
        saving=_money(cost_before - cost_after),
        saving_percent=round((cost_before - cost_after) / cost_before * 100, 1) if cost_before > 0 else None,
        excluded=[PlanRunDeviceRefOut(device_id=device_id, device_name=names[device_id])
                  for device_id in by_device if device_id in excluded],
        planned_saving=_money(sum((action.cost_before or 0.0) - (action.planned_cost or 0.0)
                                  for action in run.actions if action.device_id not in excluded)),
    )


def _priced(run: RunEnergy, slots: dict[datetime, float]) -> float:
    return sum(kwh * run.prices.get(slot, 0.0) for slot, kwh in slots.items())


def _allocated(run: RunEnergy, by_device: dict[str, dict[datetime, float]]) -> dict[str, float]:
    """Koszt z rachunku domu z PV, jak w raporcie: urządzenia razem, bo dzielą nadwyżkę w tych samych godzinach."""
    items = []
    for device_id, slots in by_device.items():
        used = {slot: kwh for slot, kwh in slots.items() if kwh}
        if not used:
            continue
        start, last = min(used), max(used)
        items.append((device_id, start, [used.get(start + index * SLOT, 0.0) for index in range(int((last - start) / SLOT) + 1)]))
    costs, _ = run.balance.allocate(items)
    return {device_id: costs.get(device_id) or 0.0 for device_id in by_device}
