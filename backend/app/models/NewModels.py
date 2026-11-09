from datetime import date
from decimal import Decimal
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

from app.schemas.other import DistributionOperatorEnum, TariffTypeEnum


# Rodzaje dnia w godzinach stref: dni robocze (pon.–pt.), soboty, niedziele i dni ustawowo wolne od pracy.
DAY_TYPES = ("workday", "saturday", "sunday_holiday")


class RegulatoryPeriod(Base):
    """Okres ogólnokrajowych opłat i progów (jakościowa, OZE, kogeneracyjna, akcyza, VAT, mocowa, przejściowa)."""

    __tablename__ = "regulatory_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)

    # Opłaty za kWh (zł/kWh netto) w okresie
    quality_fee_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    renewable_energy_fee_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0.0"))
    cogeneration_fee_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    # Akcyza doliczana do energii, gdy cena sprzedawcy jej nie zawiera (osobna pozycja rachunku).
    excise_per_kwh: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0"))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=Decimal("0.23"))
    # Dokumenty i strony, z których pochodzą stawki okresu.
    source: Mapped[str] = mapped_column(Text, nullable=False)

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


def _same_as_definition(column):
    """Domyślny okres części taryfy = okres definicji (definicja złożona z jednego wpisu OSD i sprzedawcy)."""

    def default(context):
        return context.get_current_parameters()[column]

    return default


class TariffDefinition(Base):
    """Taryfa operatora w okresie, w którym nie zmienia się ani część dystrybucyjna (OSD), ani energetyczna.

    Definicja powstaje z wpisu taryfy OSD i wpisu taryfy sprzedawcy (albo oferty z ceną dynamiczną); każda
    część ma własny okres ważności i źródło. Dla oferty dynamicznej cena energii strefy 1 to marża sprzedawcy.
    """
    __tablename__ = "tariff_definitions"
    __table_args__ = (
        UniqueConstraint("osd_operator", "tariff_code", "distribution_group", "valid_from", name="uq_osd_tariff_validity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    osd_operator: Mapped[DistributionOperatorEnum] = mapped_column(Enum(DistributionOperatorEnum), nullable=False, index=True)
    tariff_code: Mapped[TariffTypeEnum] = mapped_column(Enum(TariffTypeEnum), nullable=False, index=True)
    # Grupa dystrybucyjna: dla taryf strefowych równa tariff_code, dla oferty dynamicznej grupa klienta.
    distribution_group: Mapped[TariffTypeEnum] = mapped_column(Enum(TariffTypeEnum), nullable=False)
    # Nazwa do wyświetlenia, np. „Dynamiczna energia z PGE”; brak = kod taryfy.
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    number_of_zones: Mapped[int] = mapped_column(Integer, nullable=False)

    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)

    # Część dystrybucyjna (taryfa OSD): okres wpisu, z którego pochodzi, i źródło stawek.
    distribution_valid_from: Mapped[date] = mapped_column(
        Date, nullable=False, default=_same_as_definition("valid_from")
    )
    distribution_valid_to: Mapped[date] = mapped_column(Date, nullable=False, default=_same_as_definition("valid_to"))
    distribution_source: Mapped[str] = mapped_column(Text, nullable=False)

    # Część energetyczna (taryfa sprzedawcy z urzędu albo oferta dynamiczna).
    energy_valid_from: Mapped[date] = mapped_column(Date, nullable=False, default=_same_as_definition("valid_from"))
    energy_valid_to: Mapped[date] = mapped_column(Date, nullable=False, default=_same_as_definition("valid_to"))
    energy_source: Mapped[str] = mapped_column(Text, nullable=False)
    # Czy ceny energii (marża oferty dynamicznej) zawierają akcyzę; jeśli nie, silnik dolicza ją osobno.
    energy_includes_excise: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Cena maksymalna energii (zł/kWh netto bez akcyzy), np. 0,50 w okresie 1.07.2024–31.12.2025.
    energy_price_cap_per_kwh: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)

    # Oferta z ceną dynamiczną: marża prosumenta, ograniczenie ceny giełdowej (zł/MWh) i wymagany okres.
    prosumer_margin_per_kwh: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    market_price_floor_mwh: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    market_price_cap_mwh: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Opłata handlowa sprzedawcy, zł/mies. netto (dla prosumenta osobna, jeśli oferta ją podaje); brak = 0.
    trade_fee_monthly: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    prosumer_trade_fee_monthly: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    required_billing_cycle_months: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
    zone_hours: Mapped[list["TariffZoneHour"]] = relationship(
        back_populates="tariff", cascade="all, delete-orphan", order_by="TariffZoneHour.id"
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
    # Nazwa strefy z taryfy, np. „dzienna”, „nocna”, „szczytowa”.
    zone_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
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



class TariffZoneHour(Base):
    """Przedział godzin strefy: rodzaj dnia, sezon (MM-DD–MM-DD, może przechodzić przez Nowy Rok) i minuty doby.

    Koniec przedziału wyłącznie (1440 = koniec doby). Przedziały taryfy pokrywają każdą dobę bez dziur i nakładania.
    """

    __tablename__ = "tariff_zone_hours"
    __table_args__ = (
        CheckConstraint("zone_index >= 1 AND zone_index <= 4", name="chk_zone_hours_zone_range"),
        CheckConstraint(
            "day_type IN ('workday', 'saturday', 'sunday_holiday')", name="chk_zone_hours_day_type"
        ),
        CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440 AND start_minute < end_minute", name="chk_zone_hours_minutes"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tariff_id: Mapped[int] = mapped_column(
        ForeignKey("tariff_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_index: Mapped[int] = mapped_column(Integer, nullable=False)
    day_type: Mapped[str] = mapped_column(String(20), nullable=False)
    season_from: Mapped[str] = mapped_column(String(5), nullable=False)
    season_to: Mapped[str] = mapped_column(String(5), nullable=False)
    start_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    end_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    tariff: Mapped["TariffDefinition"] = relationship(back_populates="zone_hours")


class UnsupportedTariff(Base):
    """Taryfa oferowana przez operatora, której jeszcze nie liczymy, z powodem i źródłem."""

    __tablename__ = "unsupported_tariffs"
    __table_args__ = (
        UniqueConstraint("osd_operator", "tariff_code", "valid_from", name="uq_unsupported_tariff_validity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    osd_operator: Mapped[DistributionOperatorEnum] = mapped_column(
        Enum(DistributionOperatorEnum), nullable=False, index=True
    )
    tariff_code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
