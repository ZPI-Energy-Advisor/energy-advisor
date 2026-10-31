"""Harmonogramowanie akcji urządzeń: najtańsze rozmieszczenie przy cenach kwadransów (docs/scheduling.md).

Czysta funkcja bez bazy i bez wiedzy o taryfach. Ta sama służy do poprawy historycznego okresu
i do planu na przyszłość: różni je tylko to, skąd pochodzą akcje i ceny.
"""

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone

from app.parsers.device_records import DeviceRecord
from app.providers.prices.base import MARKET_TIMEZONE


SLOT = timedelta(minutes=15)
SLOT_HOURS = 0.25
SLOT_MINUTES = 15
# Doba ma najwyżej 100 kwadransów, a start musi zostać w tej samej dobie.
MAX_SLOTS_IN_DAY = 100
MAX_PASSES = 3
POWER_TOLERANCE_KWH = 1e-9
# Suszarka startująca najwyżej tyle po końcu prania jest z nim powiązana.
DRYER_AFTER_WASH = timedelta(minutes=60)

FIXED = "fixed"
SHIFTABLE = "shiftable"

MOVED = "moved"
UNCHANGED = "unchanged"
CONFLICT = "conflict"

MISSING_PRICES = "missing_prices"
OUTSIDE_WINDOW = "outside_window"
GRID_LIMIT = "grid_limit"
OTHER_DAY = "other_day"
DEVICE_BUSY = "device_busy"


@dataclass(frozen=True)
class TimeWindow:
    """Pora dnia w czasie lokalnym; `start` późniejszy niż `end` oznacza okno przez północ."""

    start: time
    end: time

    def contains(self, moment: time) -> bool:
        if self.start == self.end:
            return True
        if self.start < self.end:
            return self.start <= moment < self.end
        return moment >= self.start or moment < self.end


@dataclass
class ScheduleAction:
    action_id: str
    device_id: str
    start: datetime
    profile_kwh: list[float]
    mode: str = FIXED
    program_id: str | None = None
    allowed_window: TimeWindow | None = None
    max_shift_min: int | None = None
    # Akcja przesuwa się razem ze wskazaną, o to samo przesunięcie (np. suszarka z praniem).
    after_action_id: str | None = None


@dataclass
class ScheduledAction:
    action_id: str
    device_id: str
    program_id: str | None
    original_start: datetime
    start: datetime
    end: datetime
    profile_kwh: list[float]
    cost_before: float | None
    cost_after: float | None
    status: str
    reason: str | None = None


@dataclass
class ScheduleResult:
    actions: list[ScheduledAction]
    # Bez akcji, dla których brakuje cen: inaczej porównanie byłoby niepełne.
    cost_before: float
    cost_after: float

    @property
    def conflicts(self) -> list[ScheduledAction]:
        return [action for action in self.actions if action.status == CONFLICT]


@dataclass
class _Group:
    """Akcje przesuwane razem: pojedyncza akcja albo łańcuch, np. pranie i suszarka."""

    actions: list[ScheduleAction]
    offset: int = 0
    placed: bool = False
    reason: str | None = None
    energy_kwh: float = field(init=False)
    movable: bool = field(init=False)
    max_offset: int = field(init=False)

    def __post_init__(self):
        self.energy_kwh = sum(sum(action.profile_kwh) for action in self.actions)
        self.movable = all(action.mode == SHIFTABLE for action in self.actions)
        limits = [action.max_shift_min // SLOT_MINUTES for action in self.actions if action.max_shift_min is not None]
        self.max_offset = min(limits, default=MAX_SLOTS_IN_DAY)

    def offsets(self) -> range:
        """Przesunięcia do sprawdzenia: w `max_shift_min` i w tym samym wystąpieniu okna co oryginał.

        Okno 19:00-7:00 obejmuje też 3:00 tego samego dnia, ale to noc wcześniejsza: bez tego zmywarka
        z wieczora przeskoczyłaby na noc przed kolacją.
        """
        low, high = -self.max_offset, self.max_offset
        for action in self.actions:
            window = action.allowed_window
            if window is None or not window.contains(_local_time(action.start)):
                continue
            in_window = lambda offset: window.contains(_local_time(action.start + offset * SLOT))  # noqa: E731
            below = next((offset for offset in range(-1, low - 1, -1) if not in_window(offset)), low - 1)
            above = next((offset for offset in range(1, high + 1) if not in_window(offset)), high + 1)
            low, high = below + 1, above - 1
        return range(low, high + 1)

    def slots(self, offset: int):
        """Pary (urządzenie, początek kwadransa, kWh) dla grupy przesuniętej o `offset` kwadransów."""
        for action in self.actions:
            start = action.start + offset * SLOT
            for index, kwh in enumerate(action.profile_kwh):
                yield action.device_id, start + index * SLOT, kwh


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc)


def _local_date(moment: datetime) -> date:
    return moment.astimezone(MARKET_TIMEZONE).date()


def _local_time(moment: datetime) -> time:
    return moment.astimezone(MARKET_TIMEZONE).time()


def _cost(start: datetime, profile_kwh: list[float], prices: dict) -> float | None:
    slot_prices = [prices.get(start + index * SLOT) for index in range(len(profile_kwh))]
    if None in slot_prices:
        return None
    return sum(price * kwh for price, kwh in zip(slot_prices, profile_kwh))


def _groups(actions: list[ScheduleAction]) -> list[_Group]:
    by_id = {action.action_id: action for action in actions}

    def root(action: ScheduleAction) -> str:
        while action.after_action_id in by_id:
            action = by_id[action.after_action_id]
        return action.action_id

    members = defaultdict(list)
    for action in actions:
        members[root(action)].append(action)
    return [_Group(group_actions) for group_actions in members.values()]


class _NoPlaceLeft(Exception):
    """Grupa nie ma dozwolonego miejsca, bo jej oryginalne miejsce zajęła inna grupa."""


class _Plan:
    """Bieżące rozmieszczenie: zajęte kwadranse urządzeń i obciążenie domu."""

    def __init__(self, prices: dict, max_grid_kw: float | None, retry_without_place: bool):
        self.prices = prices
        self.retry_without_place = retry_without_place
        self.slot_limit_kwh = None if max_grid_kw is None else max_grid_kw * SLOT_HOURS
        self.busy = defaultdict(set)
        self.load = defaultdict(float)

    def place(self, group: _Group) -> None:
        group.placed = True
        for device_id, slot, kwh in group.slots(group.offset):
            self.busy[device_id].add(slot)
            self.load[slot] += kwh

    def release(self, group: _Group) -> None:
        group.placed = False
        for device_id, slot, kwh in group.slots(group.offset):
            self.busy[device_id].discard(slot)
            self.load[slot] -= kwh

    def _occupied(self, group: _Group) -> bool:
        return any(slot in self.busy[device_id] for device_id, slot, _ in group.slots(group.offset))

    def rejection(self, group: _Group, offset: int) -> str | None:
        """Powód, dla którego grupy nie można ustawić z tym przesunięciem; None, gdy można."""
        added = defaultdict(float)
        for action in group.actions:
            if _local_date(action.start + offset * SLOT) != _local_date(action.start):
                return OTHER_DAY
        for action in group.actions:
            window = action.allowed_window
            start = action.start + offset * SLOT
            if window and not all(
                window.contains(_local_time(start + index * SLOT)) for index in range(len(action.profile_kwh))
            ):
                return OUTSIDE_WINDOW
        for device_id, slot, kwh in group.slots(offset):
            if slot in self.busy[device_id]:
                return DEVICE_BUSY
            if slot not in self.prices:
                return MISSING_PRICES
            added[slot] += kwh
        if self.slot_limit_kwh is not None:
            for slot, kwh in added.items():
                if self.load[slot] + kwh > self.slot_limit_kwh + POWER_TOLERANCE_KWH:
                    return GRID_LIMIT
        return None

    def cost(self, group: _Group, offset: int) -> float:
        return sum(self.prices[slot] * kwh for _, slot, kwh in group.slots(offset))

    def improve(self, group: _Group) -> bool:
        """Ustawia grupę w najtańszym dozwolonym miejscu. Zwraca True, gdy zmieniła położenie."""
        previous = group.offset
        if group.placed:
            self.release(group)
        options = [
            offset for offset in group.offsets()
            if self.rejection(group, offset) is None
        ]
        if options:
            group.offset = min(options, key=lambda offset: (round(self.cost(group, offset), 6), abs(offset), offset))
            group.reason = None
        else:
            group.reason = self.rejection(group, previous)
            if self.retry_without_place and (self._occupied(group) or group.reason == GRID_LIMIT):
                raise _NoPlaceLeft
        self.place(group)
        return group.offset != previous


def _arrange(actions: list[ScheduleAction], prices: dict, max_grid_kw: float | None,
             reserve_originals: bool) -> list[_Group]:
    groups = _groups(actions)
    plan = _Plan(prices, max_grid_kw, retry_without_place=not reserve_originals)
    movable = []
    for group in groups:
        # Akcje bez cen na oryginalnym miejscu zostają: nie ma z czym porównać nowego miejsca.
        priced = all(_cost(action.start, action.profile_kwh, prices) is not None for action in group.actions)
        if not priced:
            group.reason = MISSING_PRICES
        if group.movable and priced:
            movable.append(group)
        if reserve_originals or not group.movable or not priced:
            plan.place(group)
    movable.sort(key=lambda group: (-group.energy_kwh, group.actions[0].start, group.actions[0].action_id))

    for _ in range(MAX_PASSES):
        changed = [plan.improve(group) for group in movable]
        if not any(changed):
            break
    return groups


def schedule(actions: list[ScheduleAction], prices: dict, max_grid_kw: float | None = None) -> ScheduleResult:
    """Rozmieszcza akcje `shiftable` tak, żeby koszt był najmniejszy; akcje `fixed` zostają bez zmian.

    `prices` to słownik: początek kwadransa w UTC -> cena za kWh. Start jest dozwolony, gdy wypada
    co 15 minut, tej samej doby lokalnej co oryginalny, w `max_shift_min`, a akcja mieści się
    w `allowed_window`, nie nakłada się na inną akcję urządzenia, ma ceny we wszystkich kwadransach
    i nie przekracza `max_grid_kw`.

    Grupy układamy od największej energii, bo najwięcej tracą na gorszym starcie, a kolejne przebiegi
    wykorzystują miejsca zwolnione przez inne grupy. Przy równym koszcie wygrywa start najbliższy
    oryginalnemu. Układamy bez rezerwowania miejsc grup, które czekają na swoją kolej, bo duża akcja
    powinna móc zająć miejsce małej. Jeśli przez to jakaś grupa zostanie bez miejsca, układamy od nowa
    z rezerwacją: wtedy każda grupa ma przynajmniej swoje oryginalne miejsce.
    """
    utc_prices = {_utc(slot): price for slot, price in prices.items()}
    utc_actions = [replace(action, start=_utc(action.start)) for action in actions]
    try:
        groups = _arrange(utc_actions, utc_prices, max_grid_kw, reserve_originals=False)
    except _NoPlaceLeft:
        groups = _arrange(utc_actions, utc_prices, max_grid_kw, reserve_originals=True)

    scheduled = []
    for group in groups:
        for action in group.actions:
            start = action.start + group.offset * SLOT
            cost_before = _cost(action.start, action.profile_kwh, utc_prices)
            status = CONFLICT if group.reason else MOVED if group.offset else UNCHANGED
            scheduled.append(ScheduledAction(
                action_id=action.action_id,
                device_id=action.device_id,
                program_id=action.program_id,
                original_start=action.start,
                start=start,
                end=start + len(action.profile_kwh) * SLOT,
                profile_kwh=action.profile_kwh,
                cost_before=cost_before,
                cost_after=_cost(start, action.profile_kwh, utc_prices),
                status=status,
                reason=group.reason,
            ))
    scheduled.sort(key=lambda action: (action.original_start, action.action_id))
    priced_actions = [action for action in scheduled if action.cost_before is not None]
    return ScheduleResult(
        actions=scheduled,
        cost_before=sum(action.cost_before for action in priced_actions),
        cost_after=sum(action.cost_after for action in priced_actions),
    )


def actions_from_devices(devices: list[DeviceRecord]) -> list[ScheduleAction]:
    """Akcje urządzeń z pliku jako wejście `schedule`. Produkcji PV nie ma: nie obniża kosztu w wycenie."""
    actions, washes, dryers = [], [], []
    for device in devices:
        window = None
        if device.allowed_window_from is not None and device.allowed_window_to is not None:
            window = TimeWindow(device.allowed_window_from, device.allowed_window_to)
        for action in device.actions:
            if action.energy_kwh < 0:
                continue
            item = ScheduleAction(
                action_id=action.action_id,
                device_id=device.device_id,
                start=_utc(action.start),
                profile_kwh=action.slots_kwh,
                mode=SHIFTABLE if device.flexibility_mode == SHIFTABLE else FIXED,
                program_id=action.program_id,
                allowed_window=window,
                max_shift_min=device.max_shift_min,
            )
            actions.append(item)
            if device.device_type == "washing_machine":
                washes.append(item)
            elif device.device_type == "tumble_dryer":
                dryers.append(item)

    for dryer in dryers:
        for wash in washes:
            wash_end = wash.start + len(wash.profile_kwh) * SLOT
            if timedelta(0) <= dryer.start - wash_end <= DRYER_AFTER_WASH:
                dryer.after_action_id = wash.action_id
                break
    return actions
