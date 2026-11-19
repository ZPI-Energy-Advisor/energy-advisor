"""ZP-96: przebiegi run_profile z kwadransów akcji urządzeń fixed (bez bazy)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.home_replay import ReplaySlot, replay_runs


DAY = datetime(2026, 10, 18, 22, 0, tzinfo=timezone.utc)  # Północ 19.10 w Warszawie.


def _slots(device_id: str, action_id: int, start_quarter: int, kwh: list[float], ref: str | None = None) -> list[ReplaySlot]:
    return [
        ReplaySlot(
            device_id=device_id,
            action_id=action_id,
            ref=ref or f"act_{action_id}",
            slot_start=DAY + timedelta(minutes=15 * (start_quarter + index)),
            kwh=value,
        )
        for index, value in enumerate(kwh)
    ]


def test_each_action_becomes_run_with_its_quarters():
    runs = replay_runs(_slots("dev_lt_01", 1, 72, [0.02, 0.02, 0.03]) + _slots("dev_tv_01", 2, 80, [0.05]))

    assert [(run.device_id, run.start, run.ref, run.profile_kwh) for run in runs] == [
        ("dev_lt_01", DAY + timedelta(hours=18), "act_1", [0.02, 0.02, 0.03]),
        ("dev_tv_01", DAY + timedelta(hours=20), "act_2", [0.05]),
    ]


def test_action_from_previous_day_starts_at_midnight_with_rest_of_profile():
    # Lampa 23:00–1:00: zapytanie zwraca tylko kwadranse od północy doby.
    run, = replay_runs(_slots("dev_lt_01", 1, 0, [0.02, 0.02, 0.02, 0.02]))

    assert (run.start, run.end) == (DAY, DAY + timedelta(hours=1))


def test_gap_in_action_quarters_splits_it_into_runs():
    # Środek akcji przykryty nowszym plikiem: odtwarzamy części przed i po przerwie.
    slots = _slots("dev_fr_01", 1, 0, [0.01, 0.01]) + _slots("dev_fr_01", 1, 8, [0.01])

    runs = replay_runs(slots)

    assert [(run.start, len(run.profile_kwh)) for run in runs] == [(DAY, 2), (DAY + timedelta(hours=2), 1)]


def test_adjacent_actions_of_device_stay_separate():
    runs = replay_runs(_slots("dev_lt_01", 1, 4, [0.02, 0.02]) + _slots("dev_lt_01", 2, 6, [0.03]))

    assert [run.ref for run in runs] == ["act_1", "act_2"]


def test_overlapping_actions_of_device_are_merged_without_losing_energy():
    runs = replay_runs(_slots("dev_lt_01", 1, 4, [0.02, 0.02, 0.02]) + _slots("dev_lt_01", 2, 5, [0.01, 0.01, 0.01]))

    run, = runs
    assert (run.start, run.ref) == (DAY + timedelta(hours=1), "act_1")
    assert run.profile_kwh == pytest.approx([0.02, 0.03, 0.03, 0.01])


def test_production_keeps_negative_energy():
    run, = replay_runs(_slots("dev_pv_01", 1, 40, [-0.2, -0.5, -0.3]))

    assert sum(run.profile_kwh) == pytest.approx(-1.0)


def test_no_slots_give_no_runs():
    assert replay_runs([]) == []
