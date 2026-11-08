"""Seed data required by the CalculationDetails -> PV -> tariff -> settlement flow.

Run from the backend directory:

    python calculations_seed.py

Cennik ładuje z plików data/tariffs (to samo co scripts/load_tariffs.py); jeśli pliki mają błędy,
wypisuje je i kończy się kodem 1 bez zapisu do bazy. Reszta (użytkownicy scenariuszy, próbka RCE)
jest idempotentna.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from app.database import SessionLocal
from app.models.EnergyDataFile import EnergyDataFile
from app.models.EnergyReading import EnergyReading
from app.models.RcePriceObservation import RcePriceObservation
from app.models.User import User
from app.models.UserProfile import UserProfile
from app.tariff_data.db import load_data_set
from app.tariff_data.files import TariffDataError, read_data_set

TARIFF_DATA_DIR = Path(__file__).resolve().parent / "data" / "tariffs"
SOURCE = "pse_rce"

SCENARIOS = (
    {
        "email": "calculation-no-pv@example.com",
        "file_name": "scenario_without_pv.csv",
        "pv_config": {"mode": "none"},
        "readings": (
            ("2026-01-15 07:00", 2.40),
            ("2026-01-15 13:00", 1.20),
            ("2026-01-15 23:00", 0.80),
            ("2026-01-16 07:00", 2.00),
            ("2026-01-16 13:00", 1.00),
            ("2026-01-16 23:00", 0.60),
        ),
    },
    {
        "email": "calculation-net-metering@example.com",
        "file_name": "scenario_net_metering.csv",
        "pv_config": {"mode": "net_metering", "power_of_pv_kwp": 5.0},
        "readings": (
            ("2026-01-15 07:00", 2.40),
            ("2026-01-15 12:00", -3.20),
            ("2026-01-15 23:00", 0.80),
            ("2026-01-16 07:00", 1.60),
            ("2026-01-16 12:00", -2.40),
            ("2026-01-16 23:00", 0.80),
        ),
    },
    {
        "email": "calculation-net-billing@example.com",
        "file_name": "scenario_net_billing.csv",
        "pv_config": {"mode": "net_billing"},
        "readings": (
            ("2026-01-15 07:00", 2.00),
            ("2026-01-15 12:00", -3.20),
            ("2026-01-15 23:00", 1.20),
            ("2026-01-16 07:00", 1.60),
            ("2026-01-16 12:00", -2.40),
            ("2026-01-16 23:00", 0.80),
        ),
    },
)


def _ensure_dynamic_tariff_enum(db):
    """Keep manual seed runs safe when the database predates the enum migration."""
    db.execute(
        text(
            "ALTER TYPE tarifftypeenum "
            "ADD VALUE IF NOT EXISTS 'DYNAMIC'"
        )
    )


def _load_tariffs() -> None:
    """Ładuje prawdziwy cennik z backend/data/tariffs; przy błędach w plikach niczego nie wstawia."""
    try:
        data_set = read_data_set([TARIFF_DATA_DIR])
    except TariffDataError as exc:
        print(f"Błędy w plikach cennika ({len(exc.errors)}):", file=sys.stderr)
        for error in exc.errors:
            print(f"  - {error}", file=sys.stderr)
        raise SystemExit(1) from exc
    db = SessionLocal()
    try:
        load_data_set(db, data_set)
        db.commit()
    except TariffDataError as exc:
        db.rollback()
        print("Nie załadowano cennika (baza bez zmian):", file=sys.stderr)
        for error in exc.errors:
            print(f"  - {error}", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _seed_market_prices(db):
    start = datetime(2026, 1, 15, 11, tzinfo=timezone.utc)
    for offset in range(0, 48, 15):
        interval_start = start + timedelta(minutes=offset)
        exists = (
            db.query(RcePriceObservation)
            .filter_by(source=SOURCE, interval_start=interval_start)
            .first()
        )
        if exists is None:
            db.add(
                RcePriceObservation(
                    source=SOURCE,
                    interval_start=interval_start,
                    interval_minutes=15,
                    business_date=interval_start.date(),
                    price_pln_mwh=Decimal("420.00") + Decimal(offset) / Decimal("10"),
                )
            )


def _seed_calculation_scenarios(db):
    for scenario in SCENARIOS:
        user = db.query(User).filter_by(email=scenario["email"]).first()
        if user is None:
            user = User(email=scenario["email"], password_hash=None, provider="seed")
            db.add(user)
            db.flush()

        profile = db.query(UserProfile).filter_by(user_id=user.id).first()
        profile_values = {
            "type_of_property": "single_family_house",
            "year_of_construction": 2010,
            "heating_area_m2": 120.0,
            "number_of_residents": 3,
            "town": "Warszawa",
            "postal_code": "00-001",
            "distribution_operator": "PGE",
            "phase_type": "1_phase",
            "contracted_power_kw": 10.0,
            "billing_cycle": 1,
            "billing_period_start_date": "2026-01-01",
        }
        tariff_values = {"tariff_type": "G12"}
        if profile is None:
            db.add(
                UserProfile(
                    user_id=user.id,
                    base_info=profile_values,
                    consumption_and_tariff=tariff_values,
                    pv_config=scenario["pv_config"],
                )
            )
        else:
            profile.base_info = profile_values
            profile.consumption_and_tariff = tariff_values
            profile.pv_config = scenario["pv_config"]

        energy_file = (
            db.query(EnergyDataFile)
            .filter_by(user_id=user.id, file_name=scenario["file_name"])
            .first()
        )
        if energy_file is None:
            energy_file = EnergyDataFile(
                user_id=user.id,
                file_name=scenario["file_name"],
                data_start=date(2026, 1, 15),
                data_end=date(2026, 1, 16),
                records_count=len(scenario["readings"]),
                status=EnergyDataFile.STATUS_COMPLETED,
            )
            db.add(energy_file)
            db.flush()

        if not db.query(EnergyReading).filter_by(energy_data_file_id=energy_file.id).first():
            for timestamp_text, value in scenario["readings"]:
                end_time = datetime.strptime(timestamp_text, "%Y-%m-%d %H:%M")
                # Ujemna wartość scenariusza to energia oddana do sieci, jak wiersz „Oddanie” w CSV.
                for minutes in (60, 45, 30, 15):
                    db.add(
                        EnergyReading(
                            energy_data_file_id=energy_file.id,
                            measured_at=end_time - timedelta(minutes=minutes),
                            energy_kwh=Decimal(str(max(value, 0) / 4)),
                            exported_kwh=Decimal(str(max(-value, 0) / 4)),
                        )
                    )


def seed_calculation_data():
    # Cennik (taryfy, opłaty regulacyjne) pochodzi z plików, a nie z danych testowych.
    _load_tariffs()
    db = SessionLocal()
    try:
        _ensure_dynamic_tariff_enum(db)
        _seed_market_prices(db)
        _seed_calculation_scenarios(db)
        db.commit()
        print("Seed zakończony: cennik z plików, próbka cen RCE i użytkownicy scenariuszy.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_calculation_data()
