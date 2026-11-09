"""Wycena energii oddanej w net-billingu według daty (nowelizacja ustawy o OZE, Dz.U. 2024 poz. 1847)."""

from datetime import datetime

import pytest

from app.schemas.other import TypeOfMarketEnergyEnum as M
from app.services.pv_service import PVBalancingEngine


def _engine(rce, rcem=0.20):
    calls = []

    def resolver(moment, type_of_market_energy):
        calls.append(type_of_market_energy)
        return rcem if type_of_market_energy == M.RCEm else rce

    return PVBalancingEngine(resolver), calls


def test_until_end_of_january_2025_everyone_gets_rce_without_coefficient():
    engine, calls = _engine(rce=0.40)

    assert engine.get_price_for_pv_energy(datetime(2025, 1, 31, 23, 45), M.RCEm) == pytest.approx(0.40)
    assert calls == [M.RCE]


def test_from_february_2025_profile_choice_and_deposit_coefficient_apply():
    engine, calls = _engine(rce=0.40, rcem=0.20)

    assert engine.get_price_for_pv_energy(datetime(2025, 2, 1, 0, 0), M.RCEm) == pytest.approx(0.20 * 1.23)
    assert engine.get_price_for_pv_energy(datetime(2025, 2, 1, 0, 0), M.RCE) == pytest.approx(0.40 * 1.23)
    assert calls == [M.RCEm, M.RCE]


@pytest.mark.parametrize("moment", [datetime(2024, 12, 1, 12, 0), datetime(2026, 5, 1, 12, 0)])
def test_negative_market_price_values_export_at_zero(moment):
    engine, _ = _engine(rce=-0.15)

    assert engine.get_price_for_pv_energy(moment, M.RCE) == 0.0
