from datetime import date
from decimal import Decimal
import enum

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


# ==========================================
# SŁOWNIKI
# ==========================================

class OsdOperatorEnum(str, enum.Enum):
    TAURON = "TAURON"
    PGE = "PGE"
    ENEA = "ENEA"
    ENERGA = "ENERGA"
    STOEN = "STOEN"


class TariffTypeEnum(str, enum.Enum):
    G11 = "G11"
    G12 = "G12"
    G12W = "G12w"
    G13 = "G13"
    G13S = "G13s"
    G14D = "G14d"


# ==========================================
# 1. OPŁATY OGÓLNOKRAJOWE (REGULACYJNE)
# ==========================================

class RegulatoryPeriod(Base):
    """
    Okres obowiązywania ogólnokrajowych stawek i progów (zazwyczaj rok kalendarzowy).
    """
    __tablename__ = "regulatory_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)

    # Stawki zmienne ogólnokrajowe (zł/kWh)
    quality_fee_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    renewable_energy_fee_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0.0"))
    cogeneration_fee_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=Decimal("0.23"))

    # Relacje do progów ryczałtowych
    capacity_thresholds: Mapped[list["CapacityFeeThreshold"]] = relationship(
        back_populates="period", cascade="all, delete-orphan"
    )
    transition_thresholds: Mapped[list["TransitionFeeThreshold"]] = relationship(
        back_populates="period", cascade="all, delete-orphan"
    )


class CapacityFeeThreshold(Base):
    """Progi opłaty mocowej (zł/miesiąc) przypisane do danego okresu regulacyjnego."""
    __tablename__ = "capacity_fee_thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("regulatory_periods.id", ondelete="CASCADE"), nullable=False)

    min_kwh_annual: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_kwh_annual: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    monthly_fee_net_pln: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)

    period: Mapped["RegulatoryPeriod"] = relationship(back_populates="capacity_thresholds")


class TransitionFeeThreshold(Base):
    """Progi opłaty przejściowej (zł/miesiąc) przypisane do danego okresu regulacyjnego."""
    __tablename__ = "transition_fee_thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("regulatory_periods.id", ondelete="CASCADE"), nullable=False)

    min_kwh_annual: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_kwh_annual: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    monthly_fee_net_pln: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)

    period: Mapped["RegulatoryPeriod"] = relationship(back_populates="transition_thresholds")


# ==========================================
# 2. DEFINICJE TARYF I DYSTRYBUCJA (OSD)
# ==========================================

class TariffDefinition(Base):
    """
    Nagłówek taryfy dla danego OSD i okresu obowiązywania.
    """
    __tablename__ = "tariff_definitions"
    __table_args__ = (
        UniqueConstraint("osd_operator", "tariff_code", "valid_from", name="uq_osd_tariff_validity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    osd_operator: Mapped[OsdOperatorEnum] = mapped_column(Enum(OsdOperatorEnum), nullable=False, index=True)
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
    Stawka zmienna sieciowa OSD za 1 kWh dla poszczególnych stref (zł/kWh).
    zone_index: 1 (dzień / szczyt), 2 (noc / pozaszczyt), itd.
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
    Opłata abonamentowa w zależności od cyklu rozliczeniowego (zł/miesiąc).
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


# ==========================================
# 3. CENY ENERGII CZYNNEJ URE (SPRZEDAWCA Z URZĘDU)
# ==========================================

class SupplierUreRate(Base):
    """
    Zatwierdzone przez URE ceny energii czynnej sprzedawcy z urzędu dla danej strefy.
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