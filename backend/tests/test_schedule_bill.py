"""Zużycie po przesunięciu akcji: saldo kwadransu z siecią z uwzględnieniem nadwyżki PV."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services.schedule_bill import grid_limit_note, padded_readings, shifted_readings

WARSAW = ZoneInfo("Europe/Warsaw")


def _reading(hour, imported, exported="0"):
    return SimpleNamespace(measured_at=datetime(2026, 7, 1, hour), energy_kwh=Decimal(imported), exported_kwh=Decimal(exported))


def _utc(hour):
    return datetime(2026, 7, 1, hour, tzinfo=WARSAW).astimezone(timezone.utc)


def test_moved_action_first_uses_pv_surplus_then_grid():
    readings = [_reading(20, "1.5"), _reading(12, "0", "0.8")]
    # Pralka 1,0 kWh przeniesiona z 20:00 na 12:00, gdy panele oddawały 0,8 kWh.
    action = SimpleNamespace(original_start=_utc(20), start=_utc(12), profile_kwh=[1.0], original_profile_kwh=[1.0])

    after = {reading.measured_at.hour: (reading.energy_kwh, reading.exported_kwh) for reading in shifted_readings(readings, [action])}

    assert after[20] == (Decimal("0.5"), Decimal("0"))
    assert after[12] == (Decimal("0.2"), Decimal("0"))  # 0,8 kWh z nadwyżki, 0,2 kWh z sieci


def test_unmoved_actions_keep_readings():
    readings = [_reading(20, "1.5"), _reading(12, "0", "0.8")]
    action = SimpleNamespace(original_start=_utc(20), start=_utc(20), profile_kwh=[1.0], original_profile_kwh=[1.0])

    after = shifted_readings(readings, [action])

    assert [(r.measured_at.hour, r.energy_kwh, r.exported_kwh) for r in after] == [
        (12, Decimal("0"), Decimal("0.8")), (20, Decimal("1.5"), Decimal("0")),
    ]


def test_ev_charging_with_gaps_moves_original_energy_into_planned_quarters():
    readings = [
        _reading(18, "1.0"), SimpleNamespace(measured_at=datetime(2026, 7, 1, 18, 15), energy_kwh=Decimal("1.0"), exported_kwh=Decimal("0")),
        _reading(1, "0.1"), _reading(3, "0.1"),
    ]
    # Ładowanie 2 × 0,9 kWh od 18:00 przeniesione na 1:00 i 3:00, z przerwą o 2:00.
    action = SimpleNamespace(
        original_start=_utc(18), original_profile_kwh=[0.9, 0.9],
        start=_utc(1), profile_kwh=[0.9, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.9],
    )

    after = {(r.measured_at.hour, r.measured_at.minute): r.energy_kwh for r in shifted_readings(readings, [action])}

    assert after[(18, 0)] == after[(18, 15)] == Decimal("0.1")
    assert after[(1, 0)] == Decimal("1.0")
    assert after[(3, 0)] == Decimal("1.0")
    assert after[(2, 0)] == Decimal("0")


def test_before_and_after_bills_get_the_same_quarters_when_charging_moves_past_midnight():
    readings = [_reading(23, "1.0")]
    # Ładowanie 1 kWh z 23:00 przeniesione na 2:00 kolejnej doby, za koniec odczytów.
    next_day_2am = datetime(2026, 7, 2, 2, tzinfo=WARSAW).astimezone(timezone.utc)
    action = SimpleNamespace(original_start=_utc(23), original_profile_kwh=[1.0], start=next_day_2am, profile_kwh=[1.0])

    before = padded_readings(readings, [action])
    after = shifted_readings(before, [action])

    assert {r.measured_at for r in before} == {r.measured_at for r in after}
    after_by_time = {r.measured_at: (r.energy_kwh, r.exported_kwh) for r in after}
    assert after_by_time[datetime(2026, 7, 1, 23)] == (Decimal("0"), Decimal("0"))
    assert after_by_time[datetime(2026, 7, 2, 2)] == (Decimal("1.0"), Decimal("0"))


def test_grid_limit_note_counts_quarters_above_contracted_power():
    # 1,2 kWh w kwadransie to 4,8 kW poboru z sieci.
    readings = [_reading(18, "1.2"), _reading(19, "0.2"), _reading(20, "2.5")]

    note = grid_limit_note(readings, 4.0)

    assert note.startswith("W wybranym okresie dom pobierał z sieci więcej niż 4,0 kW (moc umowna z profilu) w 2 kwadransach")
    assert "najwięcej 10,0 kW" in note
    assert grid_limit_note(readings, 12.0) is None
    assert grid_limit_note(readings, None) is None
