"""Seed data required by the CalculationDetails -> PV -> tariff -> settlement flow.

Run from the backend directory:

    python calculations_seed.py

The script is idempotent for the seeded period and tariff definitions.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.database import SessionLocal
from app.models.RcePriceObservation import RcePriceObservation
from app.models.EnergyDataFile import EnergyDataFile
from app.models.EnergyReading import EnergyReading
from app.schemas.other import DistributionOperatorEnum
from app.models.NewModels import (
    CapacityFeeThreshold,
    OsdSubscriptionFee,
    OsdVariableNetworkRate,
    RegulatoryPeriod,
    SupplierUreRate,
    TariffDefinition,
    TariffTypeEnum,
    TransitionFeeThreshold,
)
from app.models.User import User
from app.models.UserProfile import UserProfile
from app.models.RcEmPriceObservation import RcEmPriceObservation


SEED_FROM = date(2026, 1, 1)
SEED_TO = date(2026, 12, 31)
SOURCE = "pse_rce"
RCEM_SOURCE = "pse_rcem"

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
        "pv_config": {"mode": "net_billing", "type_of_price": "RCE"},
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


def _seed_regulatory_period(db):
    period = (
        db.query(RegulatoryPeriod)
        .filter_by(valid_from=SEED_FROM, valid_to=SEED_TO)
        .first()
    )
    if period is not None:
        return period

    period = RegulatoryPeriod(
        valid_from=SEED_FROM,
        valid_to=SEED_TO,
        quality_fee_per_kwh=Decimal("0.0120"),
        renewable_energy_fee_per_kwh=Decimal("0.0000"),
        cogeneration_fee_per_kwh=Decimal("0.0030"),
        vat_rate=Decimal("0.23"),
    )
    period.capacity_thresholds = [
        CapacityFeeThreshold(min_kwh_annual=0, max_kwh_annual=500, monthly_fee_net_pln=3.00),
        CapacityFeeThreshold(min_kwh_annual=500, max_kwh_annual=1200, monthly_fee_net_pln=8.00),
        CapacityFeeThreshold(min_kwh_annual=1200, max_kwh_annual=None, monthly_fee_net_pln=15.00),
    ]
    period.transition_thresholds = [
        TransitionFeeThreshold(min_kwh_annual=0, max_kwh_annual=500, monthly_fee_net_pln=0.00),
        TransitionFeeThreshold(min_kwh_annual=500, max_kwh_annual=1200, monthly_fee_net_pln=1.00),
        TransitionFeeThreshold(min_kwh_annual=1200, max_kwh_annual=None, monthly_fee_net_pln=2.00),
    ]
    db.add(period)
    db.flush()
    return period


def _seed_tariff(db, code: TariffTypeEnum, zones: list[tuple[Decimal, Decimal]]):
    tariff = (
        db.query(TariffDefinition)
        .filter_by(
            osd_operator=DistributionOperatorEnum.PGE,
            tariff_code=code,
            valid_from=SEED_FROM,
        )
        .first()
    )
    if tariff is not None:
        if code == TariffTypeEnum.DYNAMIC:
            for rate in tariff.variable_network_rates:
                if rate.zone_index == 1 and Decimal(str(rate.rate_per_kwh_net_pln)) == Decimal("0"):
                    rate.rate_per_kwh_net_pln = Decimal("0.25")
        return tariff

    tariff = TariffDefinition(
        osd_operator=DistributionOperatorEnum.PGE,
        tariff_code=code,
        number_of_zones=len(zones),
        valid_from=SEED_FROM,
        valid_to=SEED_TO,
        fixed_network_fee_1phase_monthly=Decimal("8.50"),
        fixed_network_fee_3phase_monthly=Decimal("16.50"),
    )
    tariff.variable_network_rates = [
        OsdVariableNetworkRate(zone_index=index, rate_per_kwh_net_pln=network)
        for index, (_, network) in enumerate(zones, start=1)
    ]
    tariff.supplier_ure_rates = [
        SupplierUreRate(
            supplier_name="Sprzedawca z urzędu - dane testowe",
            zone_index=index,
            energy_price_per_kwh_net_pln=energy,
        )
        for index, (energy, _) in enumerate(zones, start=1)
    ]
    tariff.subscription_fees = [
        OsdSubscriptionFee(billing_cycle_months=months, monthly_fee_net_pln=fee)
        for months, fee in ((1, Decimal("3.00")), (2, Decimal("5.00")), (6, Decimal("12.00")), (12, Decimal("20.00")))
    ]
    db.add(tariff)
    return tariff


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
    rcem = (
        db.query(RcEmPriceObservation)
        .filter_by(source=RCEM_SOURCE, price_month=date(2026, 1, 1))
        .first()
    )
    if rcem is None:
        db.add(
            RcEmPriceObservation(
                source=RCEM_SOURCE,
                price_month=date(2026, 1, 1),
                price_pln_mwh=Decimal("551.96"),
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
                for minutes in (60, 45, 30, 15):
                    db.add(
                        EnergyReading(
                            energy_data_file_id=energy_file.id,
                            measured_at=end_time - timedelta(minutes=minutes),
                            energy_kwh=Decimal(str(value / 4)),
                        )
                    )


def seed_calculation_data():
    db = SessionLocal()
    try:
        _ensure_dynamic_tariff_enum(db)
        _seed_regulatory_period(db)
        _seed_tariff(
            db,
            TariffTypeEnum.G11,
            [(Decimal("0.72"), Decimal("0.31"))],
        )
        _seed_tariff(
            db,
            TariffTypeEnum.G12,
            [
                (Decimal("0.86"), Decimal("0.34")),
                (Decimal("0.46"), Decimal("0.18")),
            ],
        )
        _seed_tariff(
            db,
            TariffTypeEnum.G12W,
            [
                (Decimal("0.90"), Decimal("0.36")),
                (Decimal("0.42"), Decimal("0.16")),
            ],
        )
        _seed_tariff(
            db,
            TariffTypeEnum.G13,
            [
                (Decimal("0.92"), Decimal("0.38")),
                (Decimal("0.58"), Decimal("0.24")),
                (Decimal("0.40"), Decimal("0.16")),
            ],
        )
        _seed_tariff(
            db,
            TariffTypeEnum.G13S,
            [
                (Decimal("0.95"), Decimal("0.40")),
                (Decimal("0.60"), Decimal("0.25")),
                (Decimal("0.38"), Decimal("0.15")),
            ],
        )
        _seed_tariff(
            db,
            TariffTypeEnum.G14D,
            [
                (Decimal("1.00"), Decimal("0.42")),
                (Decimal("0.70"), Decimal("0.28")),
                (Decimal("0.52"), Decimal("0.21")),
                (Decimal("0.35"), Decimal("0.14")),
            ],
        )
        _seed_tariff(
            db,
            TariffTypeEnum.DYNAMIC,
            [(Decimal("0.42"), Decimal("0.25"))],
        )
        _seed_market_prices(db)
        _seed_calculation_scenarios(db)
        db.commit()
        print(
            "Calculation seed completed for PGE G11/G12/G12w/G13/G13s/G14d/"
            "dynamic and RCE observations."
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_calculation_data()
