"""Ładowanie EV (interruptible): energia sesji na najtańszych kwadransach okna podłączenia."""

from collections import defaultdict
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from app.parsers.device_records import ActionRecord, DeviceRecord
from app.services.scheduling import (
    CONFLICT,
    FIXED,
    GRID_LIMIT,
    INTERRUPTIBLE,
    MISSING_PRICES,
    MOVED,
    SHIFTABLE,
    SLOT,
    UNCHANGED,
    ScheduleAction,
    actions_from_devices,
    ev_min_slot_kwh,
    schedule,
)

WARSAW = ZoneInfo("Europe/Warsaw")
# 3,7 kW przez kwadrans.
EV_SLOT_KWH = 3.7 * 0.25


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=WARSAW).astimezone(timezone.utc)


def prices(cheap=(), base=1.0, first=(19, 0), last=(21, 0)) -> dict:
    result, slot, end = {}, at(*first), at(*last)
    while slot < end:
        result[slot] = next((price for start, stop, price in cheap if start <= slot < stop), base)
        slot += SLOT
    return result


def session(energy=4.0, start=None, window=(at(19, 17), at(20, 7)), max_slot_kwh=EV_SLOT_KWH, action_id="ev"):
    """Sesja jak w pliku: ładowanie pełną mocą od podłączenia, ostatni kwadrans z resztą energii."""
    full, rest = divmod(round(energy / max_slot_kwh, 9), 1)
    profile = [max_slot_kwh] * int(full) + ([energy - int(full) * max_slot_kwh] if rest else [])
    return ScheduleAction(
        action_id=action_id, device_id="dev_ev", start=start or window[0], profile_kwh=profile,
        mode=INTERRUPTIBLE, window_start=window[0], window_end=window[1], max_slot_kwh=max_slot_kwh,
    )


def plan(item) -> dict:
    """Kwadranse planu z energią (bez przerw)."""
    return {item.start + index * SLOT: kwh for index, kwh in enumerate(item.profile_kwh) if kwh}


def test_session_energy_goes_to_cheapest_quarters_within_power_and_window():
    ev = session(energy=4.0)
    # Najtańsze 1:00-2:00 i 3:00-3:30; 2:00-3:00 droższe, więc w planie będzie przerwa.
    cheap = [(at(20, 1), at(20, 2), 0.2), (at(20, 3), at(20, 3, 30), 0.3)]

    result = schedule([ev], prices(cheap))

    item, = result.actions
    slots = plan(item)
    assert sum(slots.values()) == pytest.approx(4.0)
    assert max(slots.values()) <= EV_SLOT_KWH + 1e-9
    assert all(ev.window_start <= slot and slot + SLOT <= ev.window_end for slot in slots)
    assert sorted(slots) == [at(20, 1), at(20, 1, 15), at(20, 1, 30), at(20, 1, 45), at(20, 3)]
    assert 0.0 in item.profile_kwh  # przerwa 2:00-3:00
    assert item.original_profile_kwh == ev.profile_kwh
    assert item.status == MOVED
    assert result.cost_after < result.cost_before


def test_session_in_cheapest_place_already_is_unchanged():
    ev = session(energy=1.85)
    result = schedule([ev], prices([(at(19, 17), at(19, 17, 30), 0.1)]))

    assert result.actions[0].status == UNCHANGED
    assert result.cost_after == pytest.approx(result.cost_before)


def test_flat_price_keeps_charging_from_file():
    # Ładowanie mniejszą mocą niż ładowarka: przy płaskiej cenie plan pełną mocą nic nie oszczędza.
    ev = session(energy=2.0, start=at(19, 22), window=(at(19, 18), at(20, 7)), max_slot_kwh=EV_SLOT_KWH)
    ev.profile_kwh = [0.5] * 4

    item, = schedule([ev], prices()).actions

    assert item.status == UNCHANGED
    assert item.start == ev.start
    assert item.profile_kwh == ev.profile_kwh


def test_equal_prices_outside_cheap_quarters_charge_as_early_as_possible():
    # Jeden tani kwadrans o 3:00 mieści część energii; reszta w równej cenie od najwcześniejszego kwadransu.
    ev = session(energy=2.0, start=at(19, 22), window=(at(19, 18), at(20, 7)))

    item, = schedule([ev], prices(cheap=[(at(20, 3), at(20, 3, 15), 0.5)])).actions

    assert item.status == MOVED
    assert min(plan(item)) == at(19, 18)
    assert at(20, 3) in plan(item)


def test_grid_limit_counts_other_devices_and_ev_takes_what_is_left():
    ev = session(energy=4.0)
    cheap = [(at(20, 1), at(20, 3), 0.2)]
    # Bojler 1,5 kWh na kwadrans (6 kW) przez całą tanią noc; limit 8 kW zostawia 0,5 kWh na kwadrans.
    boiler = ScheduleAction("boiler", "dev_boiler", at(20, 1), [1.5] * 8, mode=FIXED)

    result = schedule([boiler, ev], prices(cheap), max_grid_kw=8.0)

    slots = plan(next(item for item in result.actions if item.action_id == "ev"))
    assert sum(slots.values()) == pytest.approx(4.0)
    for slot, kwh in slots.items():
        load = kwh + (1.5 if at(20, 1) <= slot < at(20, 3) else 0.0)
        assert load <= 8.0 * 0.25 + 1e-9
    assert all(slots[slot] == pytest.approx(0.5) for slot in slots if at(20, 1) <= slot < at(20, 3))


def test_ev_is_placed_after_shiftable_devices():
    # Jeden tani kwadrans i limit 4 kW (1 kWh): pralka go zajmuje, EV ładuje się obok.
    cheap = [(at(20, 2), at(20, 2, 15), 0.1)]
    wash = ScheduleAction("wash", "dev_wm", at(20, 6), [1.0], mode=SHIFTABLE)
    ev = session(energy=0.9)

    result = schedule([ev, wash], prices(cheap, last=(21, 0)), max_grid_kw=4.0)

    by_id = {item.action_id: item for item in result.actions}
    assert by_id["wash"].start == at(20, 2)
    assert at(20, 2) not in plan(by_id["ev"])


def test_session_does_not_return_to_original_quarters_taken_by_shiftable_device():
    # Tanie 02:00-03:00: EV ładuje tam w pliku, ale pralka przenosi się tam pierwsza. Plan EV obok jest
    # droższy od oryginału, a mimo to oryginał nie wchodzi w grę, bo z pralką przekroczyłby limit 4 kW.
    cheap = [(at(20, 2), at(20, 3), 0.1)]
    ev = session(energy=4 * EV_SLOT_KWH, start=at(20, 2), window=(at(20, 1), at(20, 4)))
    wash = ScheduleAction("wash", "dev_wm", at(20, 1), [0.5] * 4, mode=SHIFTABLE)

    result = schedule([ev, wash], prices(cheap, first=(20, 0), last=(20, 6)), max_grid_kw=4.0)

    by_id = {item.action_id: item for item in result.actions}
    assert by_id["wash"].start == at(20, 2)
    load = defaultdict(float)
    for item in result.actions:
        for slot, kwh in plan(item).items():
            load[slot] += kwh
    assert max(load.values()) <= 4.0 * 0.25 + 1e-9
    assert sum(plan(by_id["ev"]).values()) == pytest.approx(4 * EV_SLOT_KWH)
    assert by_id["ev"].status == MOVED


def test_session_without_energy_stays_unchanged():
    # Auto podłączone już naładowane: plik ma sesję z 0 kWh.
    ev = ScheduleAction(
        "ev", "dev_ev", at(19, 17), [0.0, 0.0], mode=INTERRUPTIBLE,
        window_start=at(19, 17), window_end=at(20, 7), max_slot_kwh=EV_SLOT_KWH,
    )

    item, = schedule([ev], prices()).actions

    assert item.status == UNCHANGED
    assert item.reason is None
    assert (item.start, item.profile_kwh) == (ev.start, ev.profile_kwh)
    assert item.cost_before == item.cost_after == 0.0


def test_unchanged_session_keeps_its_start_and_profile_with_zero_quarters():
    # Profil z zerami na początku i końcu przy płaskiej cenie: nic się nie przesuwa, więc start i profil jak w pliku.
    profile = [0.0, 0.0, EV_SLOT_KWH, EV_SLOT_KWH, 0.0]
    ev = ScheduleAction(
        "ev", "dev_ev", at(19, 22), profile, mode=INTERRUPTIBLE,
        window_start=at(19, 22), window_end=at(19, 23, 15), max_slot_kwh=EV_SLOT_KWH,
    )

    item, = schedule([ev], prices(first=(19, 22), last=(20, 0))).actions

    assert item.status == UNCHANGED
    assert (item.start, item.end) == (at(19, 22), at(19, 23, 15))
    assert item.profile_kwh == profile


def test_session_too_big_for_grid_limit_does_not_spoil_other_devices():
    # Dwie pralki rano: bez rezerwacji duża zajmuje najtańszą godzinę małej, a mała idzie na drugą tanią.
    # EV stoi tylko godzinę (10:00-11:00) i potrzebuje 4,8 kWh: nawet ładując lżej, pełnym limitem 4 kW,
    # zdąży pobrać 4 kWh. Nie zmieści się w żadnym ułożeniu, więc nie może przełączyć całego domu
    # na gorsze ułożenie z rezerwacją oryginałów.
    cheap = [(at(20, 2), at(20, 3), 0.1), (at(20, 3), at(20, 4), 0.2)]
    small = ScheduleAction("small", "dev_small", at(20, 2), [0.3] * 4, mode=SHIFTABLE)
    big = ScheduleAction("big", "dev_big", at(20, 0), [0.9] * 4, mode=SHIFTABLE)
    ev = session(energy=4.8, window=(at(20, 10), at(20, 11)), max_slot_kwh=1.2)
    day = prices(cheap, first=(20, 0), last=(20, 12))

    def washers(result):
        return {item.action_id: item.start for item in result.actions if item.action_id != "ev"}

    with_ev = schedule([small, big, ev], day, max_grid_kw=4.0)

    assert washers(with_ev) == washers(schedule([small, big], day, max_grid_kw=4.0))
    assert washers(with_ev) == {"big": at(20, 2), "small": at(20, 3)}
    item = next(item for item in with_ev.actions if item.action_id == "ev")
    assert (item.status, item.reason) == (CONFLICT, GRID_LIMIT)


def test_session_squeezed_out_by_shiftable_devices_gets_reserved_place():
    # Pralka zajmuje cały zapas jedynej godziny, w której stoi auto; EV mieści się tylko wtedy,
    # gdy pralka zostanie na swoim miejscu, więc ułożenie z rezerwacją oryginałów nadal pomaga.
    cheap = [(at(20, 2), at(20, 3), 0.1)]
    wash = ScheduleAction("wash", "dev_wm", at(20, 5), [0.5] * 4, mode=SHIFTABLE)
    ev = session(energy=4 * EV_SLOT_KWH, window=(at(20, 2), at(20, 3)))

    result = schedule([ev, wash], prices(cheap, first=(20, 0), last=(20, 12)), max_grid_kw=4.0)

    by_id = {item.action_id: item for item in result.actions}
    assert by_id["ev"].reason is None
    assert by_id["wash"].start != at(20, 2)


def test_session_that_cannot_fit_under_grid_limit_keeps_its_shape_as_conflict():
    ev = session(energy=2.0, window=(at(19, 17), at(19, 17, 45)))
    fixed = ScheduleAction("oven", "dev_ov", at(19, 17), [0.9] * 3, mode=FIXED)

    item = next(item for item in schedule([fixed, ev], prices(), max_grid_kw=5.0).actions if item.action_id == "ev")

    assert item.status == CONFLICT
    assert item.reason == GRID_LIMIT
    assert item.profile_kwh == ev.profile_kwh
    assert item.start == ev.start


def test_session_without_prices_stays_and_is_not_counted():
    ev = session(energy=2.0, start=at(22, 18), window=(at(22, 18), at(23, 7)))

    result = schedule([ev], prices())

    assert result.actions[0].reason == MISSING_PRICES
    assert result.actions[0].profile_kwh == ev.profile_kwh
    assert result.cost_before == result.cost_after == 0


def _ev_device(deadline, plugged_in=None, start=None, slots=4):
    start = start or at(20, 18)
    return DeviceRecord(
        device_id="dev_ev", name="Ładowarka EV", device_type="ev_charger", device_category="Pojazd elektryczny",
        flexibility_mode=INTERRUPTIBLE, max_power_kw=3.7,
        allowed_window_from=time(17, 0), allowed_window_to=time(7, 0),
        actions=[ActionRecord(
            action_id="ev", start=start, end=start + slots * SLOT, energy_kwh=slots * EV_SLOT_KWH,
            slots_kwh=[EV_SLOT_KWH] * slots, plugged_in=plugged_in or start, deadline=deadline,
        )],
    )


def test_session_window_reaches_deadline_after_midnight():
    ev, = actions_from_devices([_ev_device(deadline=at(21, 7))])

    assert ev.mode == INTERRUPTIBLE
    assert (ev.window_start, ev.window_end) == (at(20, 18), at(21, 7))
    assert ev.max_slot_kwh == pytest.approx(EV_SLOT_KWH)

    item, = schedule([ev], prices(cheap=[(at(21, 2), at(21, 4), 0.1)], last=(22, 0))).actions
    assert set(plan(item)) <= {at(21, 2) + index * SLOT for index in range(8)}
    assert sum(item.profile_kwh) == pytest.approx(4 * EV_SLOT_KWH)


def test_neighbour_day_load_counts_to_grid_limit_but_is_not_in_result():
    # Pompa ciepła z kolejnej doby (poza okresem) pracuje w tanie godziny; limit 4 kW zostawia EV 0,1 kWh.
    ev, = actions_from_devices([_ev_device(deadline=at(21, 7), slots=2)])
    heat_pump = ScheduleAction("hp", "dev_hp", at(21, 2), [0.9] * 8, load_only=True)

    result = schedule([ev, heat_pump], prices(cheap=[(at(21, 2), at(21, 4), 0.1)], last=(22, 0)), max_grid_kw=4.0)

    item, = result.actions
    assert all(kwh <= 0.1 + 1e-9 for slot, kwh in plan(item).items() if at(21, 2) <= slot < at(21, 4))
    assert result.cost_before == pytest.approx(2 * EV_SLOT_KWH)


def test_pv_production_lowers_grid_load_like_a_meter():
    # Limit 4 kW (1 kWh/kwadrans), piekarnik 0,9 kWh; panele dają 0,8 kWh, więc z sieci dom bierze tylko 0,1 kWh.
    cheap = [(at(19, 12), at(19, 12, 15), 0.1)]
    oven = ScheduleAction("oven", "dev_ov", at(19, 12), [0.9], mode=FIXED)
    pv = ScheduleAction("pv", "dev_pv", at(19, 12), [-0.8], load_only=True)

    def noon(extra):
        ev = session(energy=EV_SLOT_KWH, start=at(19, 17), window=(at(19, 11), at(19, 18)))
        result = schedule([oven, ev, *extra], prices(cheap), max_grid_kw=4.0)
        return plan(next(item for item in result.actions if item.action_id == "ev")).get(at(19, 12), 0.0)

    assert noon([]) == pytest.approx(0.1)
    assert noon([pv]) == pytest.approx(0.9)


def test_minimum_charging_power_depends_on_charger_phases():
    assert ev_min_slot_kwh(3.7) == pytest.approx(1.38 * 0.25)  # 1 faza, 6 A
    assert ev_min_slot_kwh(11.0) == pytest.approx(4.14 * 0.25)  # 3 fazy, 6 A
    assert ev_min_slot_kwh(1.0) == pytest.approx(0.25)  # nie więcej niż moc ładowarki
    assert ev_min_slot_kwh(None) == 0.0


def test_quarter_with_headroom_below_minimum_power_is_skipped():
    # Limit 2 kW (0,5 kWh/kwadrans), w tanie 1:00-2:00 bojler 0,3 kWh: zostaje 0,2 kWh, czyli 0,8 kW < 1,38 kW.
    cheap = [(at(20, 1), at(20, 2), 0.1)]
    boiler = ScheduleAction("boiler", "dev_boiler", at(20, 1), [0.3] * 4, mode=FIXED)
    ev = session(energy=1.0)
    ev.min_slot_kwh = ev_min_slot_kwh(3.7)

    result = schedule([boiler, ev], prices(cheap), max_grid_kw=2.0)

    slots = plan(next(item for item in result.actions if item.action_id == "ev"))
    assert not any(at(20, 1) <= slot < at(20, 2) for slot in slots)
    assert sum(slots.values()) == pytest.approx(1.0)


def test_last_portion_of_session_may_be_below_minimum_power():
    ev = session(energy=1.0)
    ev.min_slot_kwh = ev_min_slot_kwh(3.7)

    item, = schedule([ev], prices(cheap=[(at(20, 1), at(20, 2), 0.1)])).actions

    assert sorted(plan(item).values()) == pytest.approx([1.0 - EV_SLOT_KWH, EV_SLOT_KWH])


def test_pv_of_device_file_is_load_only():
    pv = DeviceRecord(
        device_id="dev_pv", name="PV", device_type="pv_inverter", device_category="OZE", flexibility_mode=FIXED,
        actions=[ActionRecord("pv_1", at(19, 12), at(19, 12, 15), -0.8, [-0.8])],
    )

    action, = actions_from_devices([pv])

    assert action.load_only
    assert schedule([action], prices()).actions == []


def test_allowed_window_of_charger_does_not_limit_session():
    # Weekend: auto podłączone o 14:00, poza allowed_window ładowarki 17:00-7:00.
    ev, = actions_from_devices([_ev_device(deadline=at(20, 20), plugged_in=at(20, 14), start=at(20, 14))])

    assert ev.allowed_window is None
    item, = schedule([ev], prices(cheap=[(at(20, 15), at(20, 16), 0.1)])).actions
    assert min(plan(item)) == at(20, 15)
