from datetime import date
from decimal import Decimal
from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

from app.schemas.other import DistributionOperatorEnum, TariffTypeEnum



class RegulatoryPeriod(Base):
    """Validity period for nationwide rates and thresholds, usually a calendar year."""

    __tablename__ = "regulatory_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)

    # Fixed fees per kWh (zł/kWh) for the period
    quality_fee_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    renewable_energy_fee_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0.0"))
    cogeneration_fee_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=Decimal("0.23"))

    # Relationships to capacity and transition fee thresholds for this regulatory period
    capacity_thresholds: Mapped[list["CapacityFeeThreshold"]] = relationship(
        back_populates="period", cascade="all, delete-orphan"
    )
    transition_thresholds: Mapped[list["TransitionFeeThreshold"]] = relationship(
        back_populates="period", cascade="all, delete-orphan"
    )


class CapacityFeeThreshold(Base):
    """Thresholds for capacity fees (zł/month) assigned to a given regulatory period."""

    __tablename__ = "capacity_fee_thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("regulatory_periods.id", ondelete="CASCADE"), nullable=False)

    min_kwh_annual: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_kwh_annual: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    monthly_fee_net_pln: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)

    period: Mapped["RegulatoryPeriod"] = relationship(back_populates="capacity_thresholds")


class TransitionFeeThreshold(Base):
    """Thresholds for transition fees (zł/month) assigned to a given regulatory period."""
    __tablename__ = "transition_fee_thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("regulatory_periods.id", ondelete="CASCADE"), nullable=False)

    min_kwh_annual: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_kwh_annual: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    monthly_fee_net_pln: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)

    period: Mapped["RegulatoryPeriod"] = relationship(back_populates="transition_thresholds")


class TariffDefinition(Base):
    """
    Tariff definition for a distribution system operator and validity period.
    """
    __tablename__ = "tariff_definitions"
    __table_args__ = (
        UniqueConstraint("osd_operator", "tariff_code", "valid_from", name="uq_osd_tariff_validity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    osd_operator: Mapped[DistributionOperatorEnum] = mapped_column(Enum(DistributionOperatorEnum), nullable=False, index=True)
    tariff_code: Mapped[TariffTypeEnum] = mapped_column(Enum(TariffTypeEnum), nullable=False, index=True)
    number_of_zones: Mapped[int] = mapped_column(Integer, nullable=False)

    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)

    # Składniki stałe sieciowe OSD (zł/miesiąc)
    fixed_network_fee_1phase_monthly: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    fixed_network_fee_3phase_monthly: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)

    # Relacje do opłat strefowych i abonamentów
    variable_network_rates: Mapped[list["OsdVariableNetworkRate"]] = relationship(
        back_populates="tariff", cascade="all, delete-orphan", order_by="OsdVariableNetworkRate.zone_index"
    )
    subscription_fees: Mapped[list["OsdSubscriptionFee"]] = relationship(
        back_populates="tariff", cascade="all, delete-orphan"
    )
    supplier_ure_rates: Mapped[list["SupplierUreRate"]] = relationship(
        back_populates="tariff", cascade="all, delete-orphan", order_by="SupplierUreRate.zone_index"
    )


class OsdVariableNetworkRate(Base):
    """
    OSD variable network rate per kWh for each tariff zone.
    zone_index: 1 (day / peak), 2 (night / off-peak), and so on.
    """
    __tablename__ = "osd_variable_network_rates"
    __table_args__ = (
        UniqueConstraint("tariff_id", "zone_index", name="uq_osd_rate_zone"),
        CheckConstraint("zone_index >= 1 AND zone_index <= 4", name="chk_osd_zone_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariff_definitions.id", ondelete="CASCADE"), nullable=False)
    zone_index: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_per_kwh_net_pln: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)

    tariff: Mapped["TariffDefinition"] = relationship(back_populates="variable_network_rates")


class OsdSubscriptionFee(Base):
    """
    Subscription fee based on the billing cycle (PLN/month).
    """
    __tablename__ = "osd_subscription_fees"
    __table_args__ = (
        UniqueConstraint("tariff_id", "billing_cycle_months", name="uq_osd_sub_cycle"),
        CheckConstraint("billing_cycle_months IN (1, 2, 6, 12)", name="chk_sub_valid_cycle"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariff_definitions.id", ondelete="CASCADE"), nullable=False)
    billing_cycle_months: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_fee_net_pln: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)

    tariff: Mapped["TariffDefinition"] = relationship(back_populates="subscription_fees")


class SupplierUreRate(Base):
    """
    URE-approved active energy rate from the default supplier for a tariff zone.
    """
    __tablename__ = "supplier_ure_rates"
    __table_args__ = (
        UniqueConstraint("tariff_id", "zone_index", name="uq_ure_supplier_zone"),
        CheckConstraint("zone_index >= 1 AND zone_index <= 4", name="chk_supplier_zone_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariff_definitions.id", ondelete="CASCADE"), nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(120), nullable=False)
    zone_index: Mapped[int] = mapped_column(Integer, nullable=False)
    energy_price_per_kwh_net_pln: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)

    tariff: Mapped["TariffDefinition"] = relationship(back_populates="supplier_ure_rates")