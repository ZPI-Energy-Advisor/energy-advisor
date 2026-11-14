"""Rdzeń harmonogramowania dla planu na jutro (ZP-112): dozwolone starty i kwadranse zamiast okna i doby."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.scheduling import INTERRUPTIBLE, MOVED, SHIFTABLE, SLOT, ScheduleAction, schedule

WARSAW = ZoneInfo("Europe/Warsaw")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=WARSAW)


def prices(cheap: set, first=at(12, 0), last=at(13, 6)) -> dict:
    result, slot = {}, first
    while slot < last:
        result[slot] = 0.2 if slot in cheap else 1.0
        slot += SLOT
    return result


def test_allowed_starts_cross_midnight_and_ignore_same_day_rule():
    # Start bazowy 23:00, tanio dopiero o 01:00 następnego dnia: plan przechodzi przez północ.
    action = ScheduleAction(
        action_id="dw", device_id="dw", start=at(12, 23), profile_kwh=[0.5, 0.5], mode=SHIFTABLE,
        allowed_starts=frozenset(at(12, 23) + index * SLOT for index in range(12)),
    )

    result = schedule([action], prices({at(13, 1), at(13, 1, 15)}))

    assert result.actions[0].start == at(13, 1)
    assert result.actions[0].status == MOVED


def test_start_outside_allowed_starts_is_never_used_even_when_cheaper():
    # Dwa przedziały: 08:00–09:00 i 15:00–16:00; najtańsze 12:00 leży między nimi.
    allowed = {at(12, 8), at(12, 8, 15), at(12, 15), at(12, 15, 15)}
    action = ScheduleAction(
        action_id="wm", device_id="wm", start=at(12, 8), profile_kwh=[0.5, 0.5, 0.5], mode=SHIFTABLE,
        allowed_starts=frozenset(allowed),
    )

    result = schedule([action], prices({at(12, 12), at(12, 15, 15), at(12, 15, 30), at(12, 15, 45)}))

    assert result.actions[0].start == at(12, 15, 15)


def test_chain_moves_together_within_both_allowed_starts():
    washer = ScheduleAction(
        action_id="wm", device_id="wm", start=at(12, 7), profile_kwh=[0.5, 0.5], mode=SHIFTABLE,
        allowed_starts=frozenset(at(12, 7) + index * SLOT for index in range(40)),
    )
    # Suszarka zaraz po praniu, ale musi skończyć do 10:00.
    dryer = ScheduleAction(
        action_id="td", device_id="td", start=at(12, 7, 30), profile_kwh=[0.5, 0.5], mode=SHIFTABLE,
        after_action_id="wm", allowed_starts=frozenset(at(12, 0) + index * SLOT for index in range(39)),
    )

    result = {item.action_id: item for item in schedule([washer, dryer], prices({at(12, 13)})).actions}

    assert result["td"].start == result["wm"].end
    assert result["td"].end <= at(12, 10)


def test_session_uses_only_allowed_slots():
    # Auto podłączone 18:00–20:00 i 02:00–04:00; tanio 21:00, kiedy go nie ma, i 03:00.
    allowed = [at(12, 18) + index * SLOT for index in range(8)] + [at(13, 2) + index * SLOT for index in range(8)]
    session = ScheduleAction(
        action_id="ev", device_id="ev", start=at(12, 18), profile_kwh=[1.0, 1.0], mode=INTERRUPTIBLE,
        window_start=allowed[0], window_end=allowed[-1] + SLOT, max_slot_kwh=1.0, allowed_slots=frozenset(allowed),
    )

    item = schedule([session], prices({at(12, 21), at(12, 21, 15), at(13, 3), at(13, 3, 15)})).actions[0]

    assert item.start == at(13, 3)
    assert item.end == at(13, 3) + timedelta(minutes=30)
