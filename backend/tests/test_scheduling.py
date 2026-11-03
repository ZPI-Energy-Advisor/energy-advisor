import os
import subprocess
import sys
import time as clock
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.parsers import parse_energy_file
from app.services.scheduling import (
    CONFLICT,
    FIXED,
    GRID_LIMIT,
    MISSING_PRICES,
    MOVED,
    OUTSIDE_WINDOW,
    SHIFTABLE,
    SLOT,
    UNCHANGED,
    ScheduleAction,
    TimeWindow,
    actions_from_devices,
    schedule,
)


WARSAW = ZoneInfo("Europe/Warsaw")
DEMO_FILE = Path(__file__).parent / "fixtures" / "devices_demo_30d.json"
WASH = [0.45, 0.45, 0.30, 0.10, 0.10, 0.15, 0.20, 0.20]


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """Czas lokalny w październiku 2026."""
    return datetime(2026, 10, day, hour, minute, tzinfo=WARSAW).astimezone(timezone.utc)


def prices(first_day=19, days=2, base=1.0, cheap=()) -> dict:
    """Ceny kwadransów: `base`, a w przedziałach `cheap` (początek, koniec, cena) inna cena."""
    start = at(first_day, 0)
    end = datetime(2026, 10, first_day + days, 0, 0, tzinfo=WARSAW).astimezone(timezone.utc)
    result, slot = {}, start
    while slot < end:
        price = base
        for range_start, range_end, range_price in cheap:
            if range_start <= slot < range_end:
                price = range_price
        result[slot] = price
        slot += SLOT
    return result


def action(action_id="a", device_id="dev", start=None, profile=None, mode=SHIFTABLE, **kwargs) -> ScheduleAction:
    return ScheduleAction(
        action_id=action_id, device_id=device_id, start=start or at(19, 9),
        profile_kwh=profile or [0.25, 0.25], mode=mode, **kwargs,
    )


def by_id(result) -> dict:
    return {item.action_id: item for item in result.actions}


def test_shiftable_action_moves_to_cheapest_start_with_the_same_profile():
    result = schedule([action(profile=WASH)], prices(cheap=[(at(19, 13), at(19, 15), 0.2)]))

    moved = result.actions[0]
    assert moved.status == MOVED
    assert moved.start == at(19, 13)
    assert moved.end == at(19, 15)
    assert moved.profile_kwh == WASH
    assert result.cost_before == pytest.approx(sum(WASH))
    assert result.cost_after == pytest.approx(sum(WASH) * 0.2)


def test_fixed_action_stays_and_counts_in_cost():
    result = schedule([action(mode=FIXED)], prices(cheap=[(at(19, 13), at(19, 15), 0.2)]))

    assert result.actions[0].status == UNCHANGED
    assert result.actions[0].start == at(19, 9)
    assert result.cost_before == result.cost_after == pytest.approx(0.5)


def test_flat_prices_move_nothing():
    result = schedule([action(profile=WASH), action("b", "dev2", at(19, 18))], prices())

    assert all(item.status == UNCHANGED for item in result.actions)


def test_equal_prices_prefer_start_closest_to_original():
    cheap = [(at(19, 6), at(19, 7), 0.2), (at(19, 12), at(19, 13), 0.2)]

    result = schedule([action(start=at(19, 11), profile=[0.5])], prices(cheap=cheap))

    assert result.actions[0].start == at(19, 12)


def test_negative_prices_attract_actions():
    result = schedule([action()], prices(cheap=[(at(19, 13), at(19, 14), -0.5)]))

    assert result.actions[0].start == at(19, 13)
    assert result.cost_after < 0


def test_max_shift_limits_the_move_both_ways():
    cheap = [(at(19, 13), at(19, 15), 0.2), (at(19, 10), at(19, 10, 30), 0.5)]

    result = schedule([action(max_shift_min=60)], prices(cheap=cheap))

    assert result.actions[0].start == at(19, 10)


def test_window_is_a_hard_limit_for_the_whole_action():
    window = TimeWindow(time(7), time(22))

    result = schedule(
        [action(allowed_window=window, profile=WASH)],
        prices(cheap=[(at(19, 21), at(19, 23), 0.1)]),
    )

    # 21:00-23:00 jest najtańsze, ale akcja musi skończyć się do 22:00.
    assert result.actions[0].end == at(19, 22)


def test_window_across_midnight_allows_action_ending_next_day():
    window = TimeWindow(time(19), time(7))

    result = schedule(
        [action(start=at(19, 19), profile=[0.1] * 12, allowed_window=window)],
        prices(cheap=[(at(19, 23), at(20, 2), 0.1)]),
    )

    assert result.actions[0].start == at(19, 23)
    assert result.actions[0].end == at(20, 2)


def test_overnight_window_does_not_jump_to_the_night_before():
    window = TimeWindow(time(19), time(7))

    result = schedule(
        [action(start=at(19, 20), profile=[0.1] * 12, allowed_window=window)],
        prices(cheap=[(at(19, 3), at(19, 6), 0.1)]),
    )

    # 3:00 tego samego dnia mieści się w oknie, ale to poprzednia noc, przed oryginalnym wieczorem.
    assert result.actions[0].start >= at(19, 19)


def test_window_equal_to_action_leaves_it_in_place():
    window = TimeWindow(time(9), time(9, 30))

    result = schedule([action(allowed_window=window)], prices(cheap=[(at(19, 13), at(19, 14), 0.1)]))

    assert result.actions[0].status == UNCHANGED


def test_action_outside_window_is_pulled_in_even_if_it_costs_more():
    window = TimeWindow(time(7), time(22))

    result = schedule(
        [action(start=at(19, 23), allowed_window=window)],
        prices(cheap=[(at(19, 23), at(20, 0), 0.1)]),
    )

    item = result.actions[0]
    assert item.status == MOVED
    assert item.end <= at(19, 22)
    assert item.cost_after > item.cost_before


def test_action_outside_window_without_allowed_start_is_a_conflict():
    window = TimeWindow(time(7), time(9))

    result = schedule([action(start=at(19, 23), allowed_window=window, max_shift_min=60)], prices())

    assert result.actions[0].status == CONFLICT
    assert result.actions[0].reason == OUTSIDE_WINDOW
    assert result.actions[0].start == at(19, 23)
    assert result.conflicts == result.actions


def test_action_must_start_on_its_original_day():
    actions = [action("mon", "ev", at(19, 18)), action("tue", "ev", at(20, 18))]

    result = schedule(actions, prices(cheap=[(at(19, 3), at(19, 3, 30), 0.1)]))

    moved = by_id(result)
    assert moved["mon"].start == at(19, 3)
    assert moved["tue"].start.astimezone(WARSAW).date() == date(2026, 10, 20)


def test_same_device_never_runs_two_actions_at_once():
    actions = [action("big", "washer", at(19, 9), [0.5] * 4), action("small", "washer", at(19, 18), [0.1] * 4)]

    result = schedule(actions, prices(cheap=[(at(19, 13), at(19, 14), 0.1)]))

    moved = by_id(result)
    assert moved["big"].start == at(19, 13)
    assert moved["small"].end <= at(19, 13) or moved["small"].start >= moved["big"].end


def test_different_devices_can_share_a_cheap_slot():
    actions = [action("a", "washer"), action("b", "dishwasher")]

    result = schedule(actions, prices(cheap=[(at(19, 13), at(19, 13, 30), 0.1)]))

    assert {item.start for item in result.actions} == {at(19, 13)}


def test_big_action_can_take_the_place_of_smaller_one():
    big = action("big", "washer", at(19, 9), [0.5] * 8)
    small = action("small", "washer", at(19, 12), [0.1] * 4)

    result = schedule([big, small], prices(cheap=[(at(19, 12), at(19, 14), 0.1), (at(19, 15), at(19, 16), 0.2)]))

    moved = by_id(result)
    assert moved["big"].start == at(19, 12)
    assert moved["small"].start == at(19, 15)


def test_every_action_keeps_a_place_when_big_one_would_take_it():
    # Mała akcja może stać tylko o 9:00; duża też tam chce, ale musi jej zostawić miejsce.
    big = action("big", "washer", at(19, 7), [0.5] * 4, allowed_window=TimeWindow(time(7), time(10)))
    small = action("small", "washer", at(19, 9), [0.1] * 4, allowed_window=TimeWindow(time(9), time(10)))

    result = schedule([big, small], prices(cheap=[(at(19, 9), at(19, 10), 0.1)]))

    moved = by_id(result)
    assert moved["small"].start == at(19, 9)
    assert moved["big"].end <= at(19, 9)
    assert not result.conflicts


def test_conflicting_action_keeps_its_place_free_from_others():
    # Mała akcja nie ma dokąd pójść (poza oknem), więc większa nie może zająć jej miejsca.
    big = action("big", "washer", at(19, 20), [0.5] * 4)
    small = action("small", "washer", at(19, 23), [0.1] * 4, allowed_window=TimeWindow(time(7), time(9)), max_shift_min=60)

    result = schedule([big, small], prices(cheap=[(at(19, 23), at(20, 0), 0.1)]))

    moved = by_id(result)
    assert moved["small"].status == CONFLICT
    assert moved["small"].start == at(19, 23)
    assert moved["big"].end <= at(19, 23)


def test_chain_moves_together_and_keeps_order_and_gap():
    wash = action("wash", "washer", at(19, 9), WASH)
    dryer = action("dryer", "dryer", at(19, 11, 15), [0.35] * 4, after_action_id="wash")

    result = schedule([wash, dryer], prices(cheap=[(at(19, 13), at(19, 17), 0.2)]))

    moved = by_id(result)
    assert moved["wash"].start == at(19, 13)
    assert moved["dryer"].start == at(19, 15, 15)


def test_chain_respects_window_of_each_action():
    window = TimeWindow(time(7), time(16))
    wash = action("wash", "washer", at(19, 9), WASH)
    dryer = action("dryer", "dryer", at(19, 11, 15), [0.35] * 4, after_action_id="wash", allowed_window=window)

    result = schedule([wash, dryer], prices(cheap=[(at(19, 16), at(19, 20), 0.2)]))

    assert by_id(result)["dryer"].end <= at(19, 16)


def test_chain_with_fixed_action_stays():
    wash = action("wash", "washer", mode=FIXED)
    dryer = action("dryer", "dryer", at(19, 10), after_action_id="wash")

    result = schedule([wash, dryer], prices(cheap=[(at(19, 13), at(19, 15), 0.2)]))

    assert all(item.status == UNCHANGED for item in result.actions)


def test_missing_prices_keep_action_and_exclude_it_from_costs():
    priced = prices(days=1)

    result = schedule([action("known"), action("unknown", "dev2", at(20, 9))], priced)

    moved = by_id(result)
    assert moved["unknown"].status == CONFLICT
    assert moved["unknown"].reason == MISSING_PRICES
    assert moved["unknown"].cost_before is None
    assert result.cost_before == pytest.approx(0.5)


def test_start_needs_prices_in_all_slots():
    result = schedule(
        [action(start=at(19, 20), profile=[0.1] * 8)],
        prices(days=1, cheap=[(at(19, 23), at(20, 0), 0.1)]),
    )

    # Ostatnia godzina jest najtańsza, ale akcja nie może wyjść poza znane ceny.
    assert result.actions[0].end == at(20, 0)


def test_grid_limit_keeps_devices_apart():
    actions = [action("a", "washer", profile=[0.5, 0.5]), action("b", "dishwasher", profile=[0.5, 0.5])]

    result = schedule(actions, prices(cheap=[(at(19, 13), at(19, 13, 30), 0.1)]), max_grid_kw=2.5)

    moved = by_id(result)
    assert moved["a"].start == at(19, 13)
    assert moved["b"].start != at(19, 13)


def test_grid_limit_counts_fixed_actions():
    fixed = action("oven", "oven", at(19, 13), [0.5, 0.5], mode=FIXED)
    washer = action("wash", "washer", profile=[0.5, 0.5])

    result = schedule([fixed, washer], prices(cheap=[(at(19, 13), at(19, 13, 30), 0.1)]), max_grid_kw=2.5)

    assert by_id(result)["wash"].start != at(19, 13)


def test_grid_limit_exceeded_with_nowhere_to_go_is_a_conflict():
    actions = [action("a", "washer", profile=[1.0], max_shift_min=0), action("b", "dishwasher", profile=[1.0], max_shift_min=0)]

    result = schedule(actions, prices(), max_grid_kw=2)

    assert [item.reason for item in result.actions].count(GRID_LIMIT) >= 1


def test_dst_day_has_100_quarters_and_action_can_use_the_repeated_hour():
    # 25.10.2026: godzina 2:00-3:00 występuje dwa razy; druga to 01:00-02:00 UTC.
    cheap_utc = datetime(2026, 10, 25, 1, 15, tzinfo=timezone.utc)
    all_prices = {
        datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc) + index * SLOT: 1.0 for index in range(100)
    }
    all_prices[cheap_utc] = 0.1

    result = schedule([action(start=datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc), profile=[1.0])], all_prices)

    assert len(all_prices) == 100
    assert result.actions[0].start == cheap_utc


def test_energy_of_each_action_is_preserved():
    with DEMO_FILE.open("rb") as handle:
        devices = parse_energy_file(handle).devices
    actions = actions_from_devices(devices)
    start = min(item.start for item in actions)
    all_prices = {start + index * SLOT: 1.0 + (index % 96) / 96 for index in range(96 * 33)}

    result = schedule(actions, all_prices)

    moved = by_id(result)
    assert sum(sum(item.profile_kwh) for item in result.actions) == pytest.approx(sum(sum(a.profile_kwh) for a in actions))
    assert all(moved[item.action_id].profile_kwh == item.profile_kwh for item in actions)
    assert all(
        item.start == moved[item.action_id].original_start for item in actions if item.mode == FIXED
    )
    assert result.cost_after < result.cost_before


def test_actions_from_devices_links_dryer_and_skips_pv():
    with DEMO_FILE.open("rb") as handle:
        devices = parse_energy_file(handle).devices

    actions = actions_from_devices(devices)

    assert not any(item.device_id == "dev_pv_01" for item in actions)
    dryers = [item for item in actions if item.device_id == "dev_td_01"]
    assert dryers and all(item.after_action_id for item in dryers)


def test_week_of_demo_file_is_scheduled_under_2_seconds():
    with DEMO_FILE.open("rb") as handle:
        devices = parse_energy_file(handle).devices
    actions = actions_from_devices(devices)
    start = min(item.start for item in actions)
    week = [item for item in actions if item.start < start + timedelta(days=7)]
    all_prices = {start + index * SLOT: 1.0 + (index % 96) / 96 for index in range(96 * 8)}

    started = clock.perf_counter()
    schedule(week, all_prices)

    assert clock.perf_counter() - started < 2


def test_show_schedule_prints_saving_for_demo_files():
    fixtures = Path(__file__).parent / "fixtures"
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "show_schedule.py"),
            str(fixtures / "scheduling_demo.json"),
            str(fixtures / "scheduling_demo_prices.json"),
        ],
        capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    assert result.returncode == 0, result.stderr
    assert "oszczędność:" in result.stdout
