"""Plan pracy urządzeń na dzień (ZP-112): ustawienia z ZP-111 jako akcje rdzenia harmonogramowania.

Zakres planu to doba planu i noc po niej do 06:00, żeby zmywarka albo auto mogły pracować przez
północ. Każda akcja dostaje dozwolone starty (albo kwadranse) wyliczone z przedziałów użytkownika,
a start bazowy („bez planu”) to to, co dom robi bez planu: zwykła godzina z historii, ładowanie od
podłączenia auta, termostat bojlera, bloki pompy z historii.

- urządzenie z programem: cały program w jednym przedziale; bez planu startuje o godzinie, o której zwykle
  jest włączane (mediana startów z historii, najbliższy dozwolony start), a bez historii na początku przedziału;
- „Wykonaj po”: start zaraz po końcu poprzednika (łańcuch przesuwa się razem), koniec przed `finish_by`;
- auto: energia rozłożona na najtańsze kwadranse przedziałów podłączenia;
- bojler: magazyn ciepła z temperaturą wody (water_heater.py): pobór z liczby osób, woda ciepła na godziny
  „woda gotowa na” i nigdy zimna, grzanie na zapas w tanich godzinach; bez planu zwykły termostat;
- pompa ciepła: bloki grzania z historii dopasowane do prognozowanej temperatury (ZP-119, heat_pump.py),
  każdy przesuwany najwyżej o `shift_hours`.

Urządzenia stałe i produkcja PV nie wchodzą do kosztu planu, więc oszczędność dotyczy tylko planowanych urządzeń.
To, co w dobie planu pracuje samo (PV z prognozy pogody, pompa ciepła i bojler spoza planu), plan zapisuje
w `background` (ZP-120, day_background.py), a symulacja wysyła do huba dokładnie to.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status

from app.models.DayPlan import DayPlan
from app.models.User import User
from app.parsers.devices import LOCAL_TIMEZONE
from app.providers.prices.pse_provider import PseRcePriceProvider
from app.repositories.day_plan_repository import DayPlanRepository
from app.repositories.planning_repository import PlanningRepository
from app.schemas.day_plan import DayPlanOut, PlanItemOut
from app.schemas.planning import PlanningDevice
from app.schemas.schedule import ChargingPeriodOut, SchedulePriceOut
from app.services.day_background import FORECAST, PV_TYPE, DayBackground, DayBackgroundService
from app.services.heat_pump import Block, HeatPumpDay, HeatPumpService, Home, scale_blocks
from app.services.plan_history import clock_minute, day_actions, moved_to, peak_by_clock, reference_day
from app.services.planning_service import (
    DAY_MINUTES,
    HEAT_PUMP_TYPE,
    WATER_HEATER_TYPE,
    PlanningService,
    tomorrow,
    window_span,
)
from app.services.schedule_prices import SchedulePriceService
from app.services.scheduling import (
    INTERRUPTIBLE,
    MOVED,
    SHIFTABLE,
    SLOT,
    SLOT_HOURS,
    SLOT_MINUTES,
    UNCHANGED,
    ScheduleAction,
    ScheduledAction,
    ev_min_slot_kwh,
    schedule,
)
from app.services.water_heater import (
    LOSS_C_PER_HOUR_AT_READY,
    ROOM_TEMP,
    MAX_TEMP,
    MIN_TEMP,
    READY_TEMP,
    Tank,
    draws,
    optimize,
    thermostat,
)

# Plan kończy się o 06:00 dnia po dniu planu: dalej taryfa dynamiczna nie ma nawet przybliżonych cen.
PLAN_END_MINUTES = DAY_MINUTES + 6 * 60
# Rezerwa w limicie przyłącza na resztę domu: największy pobór urządzeń stałych z tylu ostatnich dni.
RESERVE_DAYS = 7
# Bez mocy w pliku: typowa ładowarka 1-fazowa 16 A i bojler 2 kW.
DEFAULT_EV_POWER_KW = 3.7
DEFAULT_WATER_HEATER_POWER_KW = 2.0
PRICE_PUBLICATION = "PSE publikuje ceny na kolejny dzień ok. 14:00, u nas są najpóźniej o 15:00."
PV_HISTORY_REASONS = {
    "no_weather": "nie ma pogody na ten dzień",
    "no_installation": "profil nie ma paneli (dodaj je w profilu, żeby liczyć produkcję z pogody)",
    "no_profile": "profil nie jest uzupełniony",
}
# „w poniedziałek 6 października”: dzień tygodnia i data słowami, bez skrótów.
WEEKDAYS = ["w poniedziałek", "we wtorek", "w środę", "w czwartek", "w piątek", "w sobotę", "w niedzielę"]
MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
          "października", "listopada", "grudnia"]


def _at(day: date, minutes: int) -> datetime:
    """Chwila `minutes` od północy dnia `day` (czas lokalny zegarowy) w UTC."""
    local = datetime.combine(day, time()) + timedelta(minutes=minutes)
    return local.replace(tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc)


def _local(moment: datetime) -> datetime:
    return moment.astimezone(LOCAL_TIMEZONE)


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def _day_text(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"


def _slot_ranges(starts: list[datetime]) -> str:
    """Kwadranse jako godziny lokalne, sąsiednie połączone: „o 17:00–17:30 i 21:00–21:15”."""
    ranges: list[list[datetime]] = []
    for slot in sorted(starts):
        if ranges and ranges[-1][1] == slot:
            ranges[-1][1] = slot + SLOT
        else:
            ranges.append([slot, slot + SLOT])
    return "o " + _list([f"{_local(start):%H:%M}–{_local(end):%H:%M}" for start, end in ranges])


def _clock(clock: str) -> str:
    """06:00 -> 6:00, jak w mowie."""
    return clock[1:] if clock.startswith("0") else clock


def _part_of_day(moment: datetime) -> str:
    hour = _local(moment).hour
    if hour < 6:
        return "w nocy"
    if hour < 12:
        return "rano"
    if hour < 18:
        return "po południu"
    return "wieczorem"


def _degrees(value: float) -> str:
    return f"{round(value) + 0}°C"


def _hours(hours: int) -> str:
    return "godzinę" if hours == 1 else f"{hours} godziny"


def _list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} i {items[-1]}"


def _kwh(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _spans(device: PlanningDevice) -> list[tuple[int, int]]:
    """Przedziały urządzenia w minutach od północy dnia planu, przycięte do końca planu."""
    spans = []
    for window in device.preference.windows:
        start, end = window_span(window)
        if start < PLAN_END_MINUTES:
            spans.append((start, min(end, PLAN_END_MINUTES)))
    return spans


def _heat_pump_note(device: PlanningDevice, source: date, plan_date: date, heating: HeatPumpDay | None,
                    reference_kwh: float, planned: float, hours: int) -> str:
    shift = f"Grzanie przesuwamy najwyżej o {_hours(hours)}."
    if heating is None or heating.plan is None:
        text = f"{device.device_name}: grzeje tyle co {_day_text(source)} ({_kwh(reference_kwh)} kWh)."
        if heating is not None:
            missing = plan_date if heating.plan_temperature is None else source
            text += f" Nie mamy pogody na {_day_text(missing)}, więc nie dopasowujemy grzania do temperatury."
        return f"{text} {shift}"
    plan_t, reference_t = heating.plan_temperature, heating.reference_temperature
    return (
        f"{device.device_name}: {_day_text(plan_date)} średnio {_degrees(plan_t.mean_c)} "
        f"(od {_degrees(plan_t.min_c)} do {_degrees(plan_t.max_c)}), a {_day_text(source)} było średnio "
        f"{_degrees(reference_t.mean_c)}. Dom potrzebuje ok. {_kwh(heating.plan.heat_kwh)} kWh ciepła, więc pompa "
        f"zużyje ok. {_kwh(planned)} kWh prądu (wtedy {_kwh(reference_kwh)} kWh). {shift}"
    )


def _heat_pump_out(device: PlanningDevice, heating: HeatPumpDay, planned: float) -> dict:
    def temperature(value) -> dict:
        return {"mean_c": round(value.mean_c, 1), "min_c": round(value.min_c, 1), "max_c": round(value.max_c, 1),
                "source": value.source}

    model = heating.model
    return {
        "device_id": device.device_id,
        "device_name": device.device_name,
        "plan_temperature": temperature(heating.plan_temperature),
        "reference_day": heating.reference_day.isoformat(),
        "reference_temperature": temperature(heating.reference_temperature),
        "reference_kwh": round(heating.reference_kwh, 2),
        "target_kwh": round(heating.kwh, 2),
        "kwh": round(planned, 2),
        "heat_kwh": round(heating.plan.heat_kwh, 1),
        "hot_water_heat_kwh": round(heating.plan.hot_water_heat_kwh, 1),
        "hdd": round(heating.plan.hdd, 1),
        "cop": round(heating.plan.cop, 2),
        "model": {
            "source": model.source,
            "heat_per_hdd": round(model.heat_per_hdd, 2),
            "hot_water_kwh": round(model.hot_water_kwh, 1),
            "floor_heating": model.floor_heating,
            "days": model.days,
            "heating_days": model.heating_days,
            "mape": model.mape,
        },
    }


@dataclass
class _Build:
    """Akcje planu z opisami do wyniku i uwagami dla użytkownika."""

    plan_date: date
    actions: list[ScheduleAction] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # To, co poszło inaczej, niż chciał użytkownik (np. auto nie naładuje się do końca): ekran pokazuje wyraźniej.
    warnings: list[str] = field(default_factory=list)
    # Wyniki ułożone poza rdzeniem (bojler), dopisywane do wyniku planu.
    extra: list[ScheduledAction] = field(default_factory=list)
    # Pozycje z przerwami w pracy (okresy pracy w tabeli i na osi): auto i bojler.
    split: set[str] = field(default_factory=set)
    heaters: list[dict] = field(default_factory=list)
    heat_pumps: list[dict] = field(default_factory=list)
    # Historia urządzeń z programem (device_id -> akcje): zwykła godzina startu bez planu.
    program_history: dict[str, list] = field(default_factory=dict)
    usual_start: list[str] = field(default_factory=list)
    window_start: list[str] = field(default_factory=list)

    def at(self, minutes: int) -> datetime:
        return _at(self.plan_date, minutes)

    def add(self, action: ScheduleAction, device: PlanningDevice, label: str | None) -> None:
        self.actions.append(action)
        self.kinds[action.action_id] = device.kind
        self.names[action.action_id] = device.device_name
        if label:
            self.labels[action.action_id] = label


class PlanService:
    def __init__(
        self,
        planning_repository: PlanningRepository,
        plan_repository: DayPlanRepository,
        price_service: SchedulePriceService,
        dynamic_price_repository,
        today=tomorrow,
        heat_pumps: HeatPumpService | None = None,
        background: DayBackgroundService | None = None,
    ):
        self.planning_repository = planning_repository
        self.plan_repository = plan_repository
        self.price_service = price_service
        self.dynamic_price_repository = dynamic_price_repository
        self.heat_pumps = heat_pumps
        self.background = background
        # Domyślny dzień planu: jutro (w testach stały).
        self.default_date = today

    def create(self, user: User, plan_date: date | None = None) -> DayPlanOut:
        plan_date = plan_date or self.default_date()
        preferences = PlanningService(self.planning_repository, lambda: plan_date).get(user)
        enabled = [device for device in preferences.devices if device.preference.enabled]
        if not enabled:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Zaznacz w ustawieniach co najmniej jedno urządzenie, które ma jutro pracować.",
            )

        start, day_end, end = _at(plan_date, 0), _at(plan_date, DAY_MINUTES), _at(plan_date, PLAN_END_MINUTES)
        pricing = self.price_service.for_user(user.id, start, end)
        prices = dict(pricing.prices)
        self._require_day_prices(prices, plan_date, start, day_end, pricing.dynamic)
        approximate_from = self._approximate_night(prices, plan_date, day_end, end)

        build = _Build(plan_date)
        base_info = self.planning_repository.base_info(user.id)
        background = (
            self.background.build(user.id, plan_date, {device.device_id for device in enabled}, base_info)
            if self.background is not None else None
        )
        raw = {device.source_device_id: (device, programs) for device, programs in self.planning_repository.flexible_devices(user.id)}
        history = self.planning_repository.device_actions(
            [raw[device.device_id][0].id for device in enabled if device.kind in (HEAT_PUMP_TYPE, "program")]
        )
        build.program_history = {
            device.device_id: history.get(raw[device.device_id][0].id, []) for device in enabled if device.kind == "program"
        }
        slots = []
        slot = start
        while slot < end:
            slots.append(slot)
            slot += SLOT
        by_id = {device.device_id: device for device in enabled}
        built: dict[str, ScheduleAction | None] = {}
        # Obciążenie, którego plan nie przesuwa (kWh w każdym kwadransie): rezerwa na resztę domu, a potem
        # grzanie bojlera. Liczymy je przed urządzeniami, bo bojler układamy poza rdzeniem i musi sam
        # zmieścić się w limicie przyłącza obok reszty domu.
        load = None
        if pricing.max_grid_kw:
            # Odznaczona pompa ciepła albo bojler nie są w planie, ale dalej pracują na termostacie,
            # więc ich zwykły pobór też musi zmieścić się w limicie (w przeciwieństwie do pralki, która jutro nie pierze).
            unplanned = [
                device for device in preferences.devices
                if not device.preference.enabled and device.kind in (HEAT_PUMP_TYPE, WATER_HEATER_TYPE)
            ]
            load = self._reserve_for_rest_of_home(
                build, user, slots, pricing.max_grid_kw, unplanned, raw, background.extra_load if background else {},
            )
        for device in enabled:
            instance, programs = raw[device.device_id]
            if device.kind == "program":
                self._program(build, device, by_id, raw, built)
            elif device.kind == "ev":
                self._ev(build, device)
            elif device.kind == WATER_HEATER_TYPE:
                self._water_heater(build, device, slots, prices, load, pricing.max_grid_kw)
            elif device.kind == HEAT_PUMP_TYPE:
                self._heat_pump(build, device, history.get(instance.id, []), user.id)

        if build.usual_start:
            build.notes.append(
                f"Bez planu: {_list(build.usual_start)} startuje o godzinie, o której zwykle jest włączane (z historii)."
            )
        if build.window_start:
            build.notes.append(
                f"Bez planu: {_list(build.window_start)} startuje na początku podanych godzin, bo nie ma w historii."
            )
        if background is not None:
            build.notes.extend(self._background_notes(user, plan_date, background))
        result = schedule(build.actions, prices, pricing.max_grid_kw)
        result.actions.extend(build.extra)
        result.cost_before += sum(item.cost_before for item in build.extra)
        result.cost_after += sum(item.cost_after for item in build.extra)
        if approximate_from:
            build.notes.insert(0, (
                "Ceny na noc po tym dniu nie są jeszcze znane, więc przyjęliśmy ceny z tych samych godzin. "
                "Koszt nocy jest przybliżony."
            ))
        body = self._result(build, result, prices, pricing, start, end, approximate_from)
        if background is not None:
            body["background"] = background.to_json()
        plan = self.plan_repository.save(user.id, plan_date, body)
        return self._out(plan)

    def current(self, user: User) -> DayPlanOut | None:
        plan = self.plan_repository.latest(user.id)
        return self._out(plan) if plan else None

    def approve(self, user: User, plan_id: UUID) -> DayPlanOut:
        plan = self.plan_repository.get(user.id, plan_id)
        if plan is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nie ma takiego planu.")
        return self._out(self.plan_repository.approve(plan))

    def _reserve_for_rest_of_home(
        self, build: _Build, user: User, slots: list[datetime], max_grid_kw: float,
        unplanned: list[PlanningDevice], raw: dict, extra_load: dict[datetime, float],
    ) -> list[float]:
        """Pozostałe urządzenia jako obciążenie domu w limicie przyłącza: o każdej porze dnia największy ich
        pobór z ostatnich dni w plikach. To urządzenia stałe oraz odznaczone pompa ciepła i bojler (`unplanned`),
        które pracują same na termostacie. Plan ich nie przesuwa, ale nie może ich wypchnąć ponad limit.

        `extra_load`: o ile pompa spoza planu pobierze więcej niż w dniu referencyjnym (zimniejszy dzień, ZP-120).

        Zwraca rezerwę w kWh na każdy kwadrans `slots` (same zera, gdy nie znamy reszty domu)."""
        usage = self.planning_repository.fixed_slot_usage(
            user.id, RESERVE_DAYS, [raw[device.device_id][0].id for device in unplanned],
        )
        peaks, days = peak_by_clock(usage, RESERVE_DAYS)
        if not peaks:
            build.notes.append(
                "Nie znamy zużycia pozostałych urządzeń w domu, więc moc przyłącza sprawdzamy tylko dla urządzeń z planu."
            )
            return [0.0] * len(slots)
        profile = [peaks.get(clock_minute(slot), 0.0) + extra_load.get(slot, 0.0) for slot in slots]
        build.actions.append(ScheduleAction(
            action_id="rest_of_home", device_id="rest_of_home", start=slots[0], profile_kwh=profile, load_only=True,
        ))
        build.notes.append(
            "Zostawiamy zapas na pozostałe urządzenia w domu, np. kuchenkę przy obiedzie, "
            "żeby razem nie przekroczyć mocy przyłącza."
        )
        if unplanned:
            build.notes.append(
                f"Zapas obejmuje też: {_list([device.device_name for device in unplanned])}. "
                "Nie układamy ich w planie, ale pracują same na termostacie, tak jak zwykle."
            )
        # Kopia: bojler dopisuje do niej swoje grzanie, a akcja `rest_of_home` ma zostać samą rezerwą.
        return list(profile)

    # --- ceny ---

    def _require_day_prices(self, prices: dict, plan_date: date, start: datetime, day_end: datetime, dynamic: bool) -> None:
        slot = start
        while slot < day_end:
            if slot not in prices:
                break
            slot += SLOT
        else:
            return
        if not dynamic:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Brak stawek Twojej taryfy na {plan_date:%d.%m.%Y}.",
            )
        _, latest, _ = self.dynamic_price_repository.get_available_range(PseRcePriceProvider.source)
        if latest is not None and latest >= plan_date:
            latest = plan_date - timedelta(days=1)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "no_prices",
                "message": f"Nie ma jeszcze cen dynamicznych na {plan_date:%d.%m.%Y}. {PRICE_PUBLICATION}",
                "latest_price_date": latest.isoformat() if latest else None,
            },
        )

    @staticmethod
    def _approximate_night(prices: dict, plan_date: date, day_end: datetime, end: datetime) -> datetime | None:
        """Kwadranse po północy bez cen dostają cenę z tej samej godziny dnia planu. Zwraca pierwszy taki kwadrans."""
        first = None
        slot = day_end
        while slot < end:
            if slot not in prices:
                same_hour = moved_to(slot, plan_date + timedelta(days=1), plan_date).astimezone(timezone.utc)
                if same_hour in prices:
                    prices[slot] = prices[same_hour]
                    first = first or slot
            slot += SLOT
        return first

    # --- akcje ---

    def _program(self, build: _Build, device: PlanningDevice, by_id: dict, raw: dict, built: dict) -> ScheduleAction | None:
        """Urządzenie z programem; poprzednika „Wykonaj po” układamy najpierw (rekurencja po łańcuchu)."""
        if device.device_id in built:
            return built[device.device_id]
        built[device.device_id] = None
        programs = raw[device.device_id][1]
        program = next((p for p in programs if p.source_program_id == device.preference.program_id), None)
        if program is None:
            build.warnings.append(f"{device.device_name}: wybierz program w ustawieniach.")
            return None
        profile = list(program.profile_kwh)
        duration = len(profile) * SLOT_MINUTES
        label = program.name
        after = device.preference.after_device_id
        if after is None:
            starts = sorted({
                minute
                for span_start, span_end in _spans(device)
                for minute in range(span_start, span_end - duration + 1, SLOT_MINUTES)
            })
            original = build.at(self._usual_start(build, device, starts)) if starts else None
            after_id = None
        else:
            predecessor_device = by_id.get(after)
            predecessor = self._program(build, predecessor_device, by_id, raw, built) if predecessor_device else None
            if predecessor is None:
                build.warnings.append(f"{device.device_name}: pominięte, bo urządzenie, na które czeka, nie jest w planie.")
                return None
            latest_end = PLAN_END_MINUTES
            if device.preference.finish_by:
                deadline = _minutes(device.preference.finish_by)
                root = self._root_start(predecessor_device, by_id)
                latest_end = min(latest_end, deadline if deadline > root else deadline + DAY_MINUTES)
            starts = list(range(0, latest_end - duration + 1, SLOT_MINUTES))
            original = predecessor.start + len(predecessor.profile_kwh) * SLOT
            after_id = predecessor.action_id
            label = f"{program.name}, po: {predecessor_device.device_name}"
        if not starts:
            build.warnings.append(
                f"{device.device_name}: program {program.name} nie mieści się w podanych godzinach."
            )
            return None
        action = ScheduleAction(
            action_id=device.device_id,
            device_id=device.device_id,
            start=original,
            profile_kwh=profile,
            mode=SHIFTABLE,
            program_id=program.source_program_id,
            after_action_id=after_id,
            allowed_starts=frozenset(build.at(minute) for minute in starts),
        )
        build.add(action, device, label)
        built[device.device_id] = action
        return action

    @staticmethod
    def _usual_start(build: _Build, device: PlanningDevice, starts: list[int]) -> int:
        """Start bez planu: mediana godzin startu z historii (w minutach od północy dnia planu), dopasowana
        do najbliższego dozwolonego startu. Bez historii: początek przedziału.

        Start wcześniejszy niż początek przedziałów przenosimy na noc po dniu planu tylko wtedy, gdy tam
        trafia do przedziału przechodzącego przez północ (zmywarka 19:00–07:00 włączana o 00:30). Przy
        przedziale w ciągu dnia (pralka 12:00–22:00 włączana zwykle o 09:00) zostaje rano tego dnia,
        więc najbliższy dozwolony start to początek przedziału, a nie jego koniec."""
        actions = build.program_history.get(device.device_id, [])
        if not actions:
            build.window_start.append(device.device_name)
            return starts[0]
        first = starts[0]
        last_end = max(end for _, end in _spans(device))

        def placed(minute: int) -> int:
            next_night = minute + DAY_MINUTES
            return next_night if minute < first and next_night < last_end else minute

        minutes = sorted(placed(clock_minute(action.action_start)) for action in actions)
        usual = round(minutes[len(minutes) // 2] / SLOT_MINUTES) * SLOT_MINUTES
        build.usual_start.append(device.device_name)
        return min(starts, key=lambda minute: (abs(minute - usual), minute))

    @staticmethod
    def _root_start(device: PlanningDevice, by_id: dict) -> int:
        while device.preference.after_device_id in by_id:
            device = by_id[device.preference.after_device_id]
        return min(window_span(window)[0] for window in device.preference.windows)

    def _session(self, build: _Build, device: PlanningDevice, action_id: str, energy: float, slots: list[int],
                 power_kw: float, min_slot_kwh: float, label: str) -> float:
        """Sesja rozkładana na najtańsze kwadranse: bazowo pobór pełną mocą od początku przedziałów.
        Zwraca energię, której nie da się zmieścić w kwadransach (przy mocy urządzenia)."""
        slot_kwh = power_kw * SLOT_HOURS
        moments = [build.at(minute) for minute in sorted(set(slots))]
        fits = min(energy, slot_kwh * len(moments))
        if fits <= 0:
            return energy
        plan, remaining = {}, fits
        for moment in moments:
            if remaining <= 1e-9:
                break
            plan[moment] = min(slot_kwh, remaining)
            remaining -= plan[moment]
        first, last = min(plan), max(plan)
        profile = [plan.get(first + index * SLOT, 0.0) for index in range(int((last - first) / SLOT) + 1)]
        build.add(ScheduleAction(
            action_id=action_id,
            device_id=device.device_id,
            start=first,
            profile_kwh=profile,
            mode=INTERRUPTIBLE,
            window_start=moments[0],
            window_end=moments[-1] + SLOT,
            max_slot_kwh=slot_kwh,
            min_slot_kwh=min_slot_kwh,
            allowed_slots=frozenset(moments),
        ), device, label)
        return energy - fits

    def _ev(self, build: _Build, device: PlanningDevice) -> None:
        energy = device.energy_needed_kwh if device.preference.energy_input == "percent" else device.preference.energy_kwh
        if not energy:
            build.warnings.append(f"{device.device_name}: podaj w ustawieniach, ile energii potrzebuje auto.")
            return
        power = device.max_power_kw or DEFAULT_EV_POWER_KW
        slots = [minute for start, end in _spans(device) for minute in range(start, end, SLOT_MINUTES)]
        missing = self._session(
            build, device, device.device_id, energy, slots, power, ev_min_slot_kwh(power), f"{_kwh(energy)} kWh",
        )
        if missing > 1e-6:
            build.warnings.append(
                f"{device.device_name}: do 6:00 auto nie naładuje się do końca, zabraknie ok. {_kwh(missing)} kWh."
            )

    def _water_heater(
        self, build: _Build, device: PlanningDevice, slots: list[datetime], prices: dict,
        load: list[float] | None = None, max_grid_kw: float | None = None,
    ) -> None:
        """Bojler jako magazyn ciepła (water_heater.py): najtańsze kwadranse grzania, przy których woda jest
        ciepła na godziny „woda gotowa na” i nigdy zimna. Bez planu: zwykły termostat.

        Liczymy dobę planu (00:00–24:00), a nie noc po niej: grzanie na poranek kolejnego dnia należy do planu
        na kolejny dzień, który zaczyna od tej samej temperatury, z jaką ten dzień kończymy."""
        tank = Tank(liters=device.preference.tank_liters, power_kw=device.max_power_kw or DEFAULT_WATER_HEATER_POWER_KW)
        day_end = build.at(DAY_MINUTES)
        slots = [slot for slot in slots if slot < day_end]
        index = {slot: position for position, slot in enumerate(slots)}
        index[day_end] = len(slots)
        ready = sorted({
            index[build.at(_minutes(clock) or DAY_MINUTES)] for clock in device.preference.ready_times
        })
        known = [price for price in prices.values()]
        slot_prices = [prices.get(slot, max(known)) for slot in slots]
        daily = device.hot_water_kwh
        draw = draws(len(slots), ready, daily)
        before = thermostat(tank, draw, slot_prices, ready)
        # Limit przyłącza: grzałka pracuje pełną mocą, więc plan grzeje w kwadransach, w których zmieści się
        # obok reszty domu (i wcześniej ułożonego bojlera). Limit jest miękki (optimize): ponad nim plan grzeje
        # tylko wtedy, gdy inaczej woda byłaby za zimna. Termostat bez planu zostaje bez zmian: to, co dom robi dziś.
        allowed = None
        if load is not None and max_grid_kw:
            limit_kwh = max_grid_kw * SLOT_HOURS
            allowed = [load[position] + tank.slot_kwh <= limit_kwh + 1e-9 for position in range(len(slots))]
        after = optimize(tank, draw, slot_prices, ready, allowed=allowed)
        if load is not None:
            for position, active in enumerate(after.on):
                if active:
                    load[position] += tank.slot_kwh
        over_limit = [
            slot for position, slot in enumerate(slots) if allowed is not None and after.on[position] and not allowed[position]
        ]

        action_id = device.device_id
        original_start, original = self._heating_profile(before.on, slots, tank.slot_kwh)
        start, profile = self._heating_profile(after.on, slots, tank.slot_kwh)
        if profile:
            # Grzanie obciąża dom w limicie przyłącza, zanim plan ułoży pozostałe urządzenia.
            build.actions.append(ScheduleAction(
                action_id=f"{action_id}#load", device_id=device.device_id, start=start, profile_kwh=profile, load_only=True,
            ))
        build.extra.append(ScheduledAction(
            action_id=action_id,
            device_id=device.device_id,
            program_id=None,
            original_start=original_start,
            start=start,
            end=start + len(profile) * SLOT,
            profile_kwh=profile,
            original_profile_kwh=original,
            cost_before=before.cost,
            cost_after=after.cost,
            status=MOVED if before.on != after.on else UNCHANGED,
        ))
        build.kinds[action_id] = device.kind
        build.names[action_id] = device.device_name
        build.labels[action_id] = f"woda gotowa na {', '.join(device.preference.ready_times)}"
        build.split.add(action_id)
        build.heaters.append({
            "device_id": device.device_id,
            "device_name": device.device_name,
            "tank_liters": device.preference.tank_liters,
            "residents": device.residents,
            "hot_water_kwh": round(daily, 2),
            "ready_times": sorted(device.preference.ready_times, key=lambda clock: _minutes(clock) or DAY_MINUTES),
            "min_temp": MIN_TEMP,
            "ready_temp": READY_TEMP,
            "max_temp": MAX_TEMP,
            "loss_per_hour": LOSS_C_PER_HOUR_AT_READY,
            "room_temp": ROOM_TEMP,
            "hot_water_source": device.hot_water_source,
            "history_kwh": device.history_kwh,
            "start_before": before.start_temp,
            "start_after": after.start_temp,
            "shortfall": round(after.shortfall, 1),
            "temperatures": [
                {"start": _local(slot).isoformat(), "before": before.temps[position], "after": after.temps[position]}
                for position, slot in enumerate(slots)
            ],
        })
        ready = _list([_clock(clock) for clock in build.heaters[-1]["ready_times"]])
        build.notes.append(
            f"{device.device_name}: woda będzie gorąca na {ready}. Plan nagrzewa ją na zapas, kiedy prąd jest tani, "
            "a w nocy pozwala jej trochę ostygnąć."
        )
        if over_limit:
            build.warnings.append(
                f"{device.device_name}: grzeje {_slot_ranges(over_limit)} mimo ryzyka przekroczenia mocy przyłącza "
                f"({_kwh(max_grid_kw)} kW) razem z resztą domu, bo inaczej woda nie byłaby ciepła na czas. "
                "Nie włączaj wtedy dużych urządzeń, np. piekarnika czy czajnika."
            )
        if after.shortfall > 0.5:
            # Limit nie powoduje już niedogrzania (jest miękki), więc to ograniczenie fizyczne bojlera.
            build.warnings.append(
                f"{device.device_name}: nie zdąży nagrzać tyle wody, ile zwykle zużywacie. Pomoże większy zbiornik."
            )

    @staticmethod
    def _heating_profile(on: list[bool], slots: list[datetime], slot_kwh: float) -> tuple[datetime, list[float]]:
        """Kwadranse grzania jako start i profil z zerami w przerwach (pełna moc w kwadransie grzania)."""
        heated = [position for position, active in enumerate(on) if active]
        if not heated:
            return slots[0], []
        first, last = heated[0], heated[-1]
        return slots[first], [slot_kwh if on[position] else 0.0 for position in range(first, last + 1)]

    def _heat_pump(self, build: _Build, device: PlanningDevice, actions: list, user_id) -> None:
        """Bloki grzania z dnia historii przeniesione na dzień planu i przeskalowane do prognozowanej temperatury;
        każdy przesuwany o `shift_hours`."""
        source = reference_day(actions, build.plan_date)
        if source is None:
            build.warnings.append(f"{device.device_name}: nie ma jej w historii zużycia, więc nie wiemy, kiedy grzać.")
            return
        horizon_start, horizon_end = build.at(0), build.at(PLAN_END_MINUTES)
        history_blocks = sorted(day_actions(actions, source), key=lambda block: block.action_start)
        blocks = [
            Block(
                moved_to(block.action_start, source, build.plan_date).astimezone(timezone.utc),
                max(1, round((block.action_end - block.action_start) / SLOT)),
                block.energy_kwh,
            )
            for block in history_blocks
        ]
        reference_kwh = sum(block.kwh for block in blocks)
        heating = self._heating(user_id, source, reference_kwh, build.plan_date)
        scaled = heating is not None and heating.plan is not None
        if scaled:
            cap = device.max_power_kw * SLOT_HOURS if device.max_power_kw else None
            blocks = scale_blocks(blocks, heating.kwh, cap, horizon_end)
        planned = sum(block.kwh for block in blocks)
        hours = device.preference.shift_hours or 1
        build.notes.append(_heat_pump_note(device, source, build.plan_date, heating, reference_kwh, planned, hours))
        if scaled:
            build.heat_pumps.append(_heat_pump_out(device, heating, planned))
            if planned < heating.kwh - 0.05:
                build.warnings.append(
                    f"{device.device_name}: przy tej pogodzie potrzebuje ok. {_kwh(heating.kwh)} kWh, a w godzinach "
                    f"grzania z {_day_text(source)} zmieści najwyżej {_kwh(planned)} kWh przy mocy "
                    f"{_kwh(device.max_power_kw)} kW. W domu może być trochę chłodniej."
                )
        shift = hours * 60
        for index, (block, history_block) in enumerate(zip(blocks, history_blocks)):
            starts = {
                block.start + offset * SLOT
                for offset in range(-shift // SLOT_MINUTES, shift // SLOT_MINUTES + 1)
                if horizon_start <= block.start + offset * SLOT
                and block.start + (offset + block.slots) * SLOT <= horizon_end
            }
            build.add(ScheduleAction(
                action_id=f"{device.device_id}#{index + 1}",
                device_id=device.device_id,
                start=block.start,
                profile_kwh=[block.kwh / block.slots] * block.slots,
                mode=SHIFTABLE,
                allowed_starts=frozenset(starts),
            ), device, f"grzanie {_part_of_day(history_block.action_start)}")

    def _background_notes(self, user: User, plan_date: date, background: DayBackground) -> list[str]:
        names = self.background.home.device_names(user.id)
        weather = "pogody z archiwum" if background.past else "prognozy pogody"
        notes = []
        for device in background.devices:
            name = names.get(device.device_id, device.device_id)
            since = f"{_day_text(device.history_day)}: {_kwh(abs(device.reference_kwh))} kWh" if device.history_day else ""
            if device.device_type == PV_TYPE and device.source == FORECAST:
                estimate = " (część pogody to średnia z ostatnich dni)" if device.reason in ("recent_days", "mixed") else ""
                notes.append(
                    f"{name} w symulacji: produkcja z {weather}{estimate}, ok. {_kwh(abs(device.kwh))} kWh"
                    + (f" ({since})." if since else ".")
                )
            elif device.device_type == PV_TYPE:
                reason = PV_HISTORY_REASONS.get(device.reason)
                if reason:
                    notes.append(f"{name} w symulacji: produkcja jak {_day_text(device.history_day)}, bo {reason}.")
            elif device.source == FORECAST:
                notes.append(
                    f"{name} pracuje sama, poza planem: przy pogodzie {_day_text(plan_date)} zużyje ok. "
                    f"{_kwh(device.kwh)} kWh ({since})."
                )
            elif device.reason == "no_weather":
                notes.append(
                    f"{name} pracuje sama, poza planem: grzeje jak {_day_text(device.history_day)}, bo nie mamy "
                    "pogody albo danych domu z profilu, żeby dopasować grzanie do temperatury."
                )
        return notes

    def _heating(self, user_id, source: date, reference_kwh: float, plan_date: date) -> HeatPumpDay | None:
        if self.heat_pumps is None:
            return None
        home = Home.of(self.planning_repository.base_info(user_id))
        return self.heat_pumps.plan_day(user_id, home, source, reference_kwh, plan_date)

    # --- wynik ---

    @staticmethod
    def _result(build: _Build, result, prices: dict, pricing, start: datetime, end: datetime,
                approximate_from: datetime | None) -> dict:
        sessions = {action.action_id for action in build.actions if action.mode == INTERRUPTIBLE} | build.split

        def charging(item, start: datetime, profile: list[float]) -> list[ChargingPeriodOut] | None:
            """Okresy pracy z przerwami (auto, bojler); None dla innych akcji i pracy bez przerw."""
            if item.action_id not in sessions or all(profile):
                return None
            periods, period_start = [], None
            for index, kwh in enumerate([*profile, 0.0]):
                slot = start + index * SLOT
                if kwh and period_start is None:
                    period_start = slot
                elif not kwh and period_start is not None:
                    periods.append(ChargingPeriodOut(start=_local(period_start), end=_local(slot)))
                    period_start = None
            return periods or None

        def money(value: float | None) -> float | None:
            return None if value is None else round(value, 2)

        items = [
            PlanItemOut(
                action_id=item.action_id,
                device_id=item.device_id,
                device_name=build.names[item.action_id],
                program_name=build.labels.get(item.action_id),
                kind=build.kinds[item.action_id],
                program_id=item.program_id,
                profile_kwh=[round(kwh, 6) for kwh in item.profile_kwh],
                original_profile_kwh=[round(kwh, 6) for kwh in item.original_profile_kwh],
                original_start=_local(item.original_start),
                original_end=_local(item.original_start + len(item.original_profile_kwh) * SLOT),
                start=_local(item.start),
                end=_local(item.end),
                energy_kwh=round(sum(item.profile_kwh), 2),
                cost_before=money(item.cost_before),
                cost_after=money(item.cost_after),
                status=item.status,
                reason=item.reason,
                charging=charging(item, item.start, item.profile_kwh),
                original_charging=charging(item, item.original_start, item.original_profile_kwh),
            )
            for item in sorted(result.actions, key=lambda action: (action.start, action.action_id))
        ]
        return {
            "horizon_start": _local(start).isoformat(),
            "horizon_end": _local(end).isoformat(),
            "pricing": pricing.description,
            "max_grid_kw": pricing.max_grid_kw,
            "approximate_from": _local(approximate_from).isoformat() if approximate_from else None,
            "cost_before": round(result.cost_before, 2),
            "cost_after": round(result.cost_after, 2),
            "saving": round(result.cost_before - result.cost_after, 2),
            "notes": build.notes,
            "warnings": build.warnings,
            "items": [item.model_dump(mode="json") for item in items],
            "prices": [
                SchedulePriceOut(start=_local(slot), price_pln_kwh=price).model_dump(mode="json")
                for slot, price in sorted(prices.items())
                if start <= slot < end
            ],
            "water_heaters": build.heaters,
            "heat_pumps": build.heat_pumps,
        }

    @staticmethod
    def _out(plan: DayPlan) -> DayPlanOut:
        return DayPlanOut(
            id=plan.id,
            plan_date=plan.plan_date,
            status=plan.status,
            # Czas lokalny z przesunięciem strefy, jak godziny planu: ekran czyta godzinę wprost z tekstu.
            created_at=_local(plan.created_at),
            approved_at=_local(plan.approved_at) if plan.approved_at else None,
            **plan.result,
        )
