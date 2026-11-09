"""Zużycie po przesunięciu akcji: saldo kwadransu z siecią z uwzględnieniem nadwyżki PV."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services.schedule_bill import shifted_readings

WARSAW = ZoneInfo("Europe/Warsaw")


def _reading(hour, imported, exported="0"):
    return SimpleNamespace(measured_at=datetime(2026, 7, 1, hour), energy_kwh=Decimal(imported), exported_kwh=Decimal(exported))


def _utc(hour):
    return datetime(2026, 7, 1, hour, tzinfo=WARSAW).astimezone(timezone.utc)


def test_moved_action_first_uses_pv_surplus_then_grid():
    readings = [_reading(20, "1.5"), _reading(12, "0", "0.8")]
    # Pralka 1,0 kWh przeniesiona z 20:00 na 12:00, gdy panele oddawały 0,8 kWh.
    action = SimpleNamespace(original_start=_utc(20), start=_utc(12), profile_kwh=[1.0])

    after = {reading.measured_at.hour: (reading.energy_kwh, reading.exported_kwh) for reading in shifted_readings(readings, [action])}

    assert after[20] == (Decimal("0.5"), Decimal("0"))
    assert after[12] == (Decimal("0.2"), Decimal("0"))  # 0,8 kWh z nadwyżki, 0,2 kWh z sieci


def test_unmoved_actions_keep_readings():
    readings = [_reading(20, "1.5"), _reading(12, "0", "0.8")]
    action = SimpleNamespace(original_start=_utc(20), start=_utc(20), profile_kwh=[1.0])

    after = shifted_readings(readings, [action])

    assert [(r.measured_at.hour, r.energy_kwh, r.exported_kwh) for r in after] == [
        (12, Decimal("0"), Decimal("0.8")), (20, Decimal("1.5"), Decimal("0")),
    ]
