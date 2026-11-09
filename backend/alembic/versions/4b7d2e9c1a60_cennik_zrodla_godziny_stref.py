"""Cennik z plików: źródła i okresy części OSD i sprzedawcy, godziny stref, opłata handlowa, taryfy nieliczone.

- tariff_definitions: nazwa, grupa dystrybucyjna (oferta dynamiczna ma osobną definicję dla każdej grupy, którą
  dopuszcza sprzedawca; unikalność obejmuje grupę), okres i źródło części dystrybucyjnej i energetycznej, akcyza
  w cenie, cena maksymalna, parametry oferty z ceną dynamiczną;
- osd_variable_network_rates: nazwa strefy;
- regulatory_periods: akcyza i źródło;
- tariff_definitions: opłata handlowa sprzedawcy (zł/mies.) i jej wariant dla prosumenta;
- nowe tabele: tariff_zone_hours, unsupported_tariffs;
- tarifftypeenum: G12N (PGE) i G12R (Energa);
- usunięta tabela rcem_price_observations: net-billing od 1.07.2024 rozlicza oddaną energię według RCE, a cennik
  zaczyna się 24.08.2024, więc miesięczna cena RCEm nie jest używana;
- usunięta tabela dynamic_price_observations: od ZP-68 ceny RCE są w rce_price_observations, a stara tabela
  była tylko zapisywaną kopią, której nic nie czytało.

Istniejące wiersze dostają okresy części równe okresowi definicji i źródło „brak źródła”, żeby kolumny mogły
być NOT NULL; prawdziwe dane ładuje scripts/load_tariffs.py.

Revision ID: 4b7d2e9c1a60
Revises: 5f9ecf30a3c9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4b7d2e9c1a60"
down_revision: Union[str, Sequence[str], None] = "5f9ecf30a3c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MISSING_SOURCE = "brak źródła (dane wprowadzone przed ZP-99)"
TARIFF_TYPE = postgresql.ENUM(name="tarifftypeenum", create_type=False)


def upgrade() -> None:
    # Nowych wartości enuma nie używamy w tej migracji, więc mogą być dodane w tej samej transakcji.
    op.execute("ALTER TYPE tarifftypeenum ADD VALUE IF NOT EXISTS 'G12N'")
    op.execute("ALTER TYPE tarifftypeenum ADD VALUE IF NOT EXISTS 'G12R'")

    op.add_column("tariff_definitions", sa.Column("name", sa.String(length=120), nullable=True))
    for column in ("distribution_valid_from", "distribution_valid_to", "energy_valid_from", "energy_valid_to"):
        op.add_column("tariff_definitions", sa.Column(column, sa.Date(), nullable=True))
    for column in ("distribution_source", "energy_source"):
        op.add_column("tariff_definitions", sa.Column(column, sa.Text(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE tariff_definitions SET distribution_valid_from = valid_from, distribution_valid_to = valid_to, "
            "energy_valid_from = valid_from, energy_valid_to = valid_to, "
            "distribution_source = :source, energy_source = :source"
        ).bindparams(source=MISSING_SOURCE)
    )
    for column in (
        "distribution_valid_from", "distribution_valid_to", "energy_valid_from", "energy_valid_to",
        "distribution_source", "energy_source",
    ):
        op.alter_column("tariff_definitions", column, nullable=False)
    for column in ("energy_includes_excise",):
        op.add_column(
            "tariff_definitions", sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false())
        )
        op.alter_column("tariff_definitions", column, server_default=None)
    op.add_column(
        "tariff_definitions", sa.Column("energy_price_cap_per_kwh", sa.Numeric(precision=8, scale=6), nullable=True)
    )
    op.add_column(
        "tariff_definitions", sa.Column("prosumer_margin_per_kwh", sa.Numeric(precision=8, scale=6), nullable=True)
    )
    op.add_column(
        "tariff_definitions", sa.Column("market_price_floor_mwh", sa.Numeric(precision=10, scale=2), nullable=True)
    )
    op.add_column(
        "tariff_definitions", sa.Column("market_price_cap_mwh", sa.Numeric(precision=10, scale=2), nullable=True)
    )
    op.add_column("tariff_definitions", sa.Column("required_billing_cycle_months", sa.Integer(), nullable=True))
    for column in ("trade_fee_monthly", "prosumer_trade_fee_monthly"):
        op.add_column("tariff_definitions", sa.Column(column, sa.Numeric(precision=8, scale=2), nullable=True))
    op.add_column("tariff_definitions", sa.Column("distribution_group", TARIFF_TYPE, nullable=True))
    op.execute(
        "UPDATE tariff_definitions SET distribution_group = "
        "CASE WHEN tariff_code::text = 'DYNAMIC' THEN 'G11'::tarifftypeenum ELSE tariff_code END"
    )
    op.alter_column("tariff_definitions", "distribution_group", nullable=False)
    op.drop_constraint("uq_osd_tariff_validity", "tariff_definitions", type_="unique")
    op.create_unique_constraint(
        "uq_osd_tariff_validity",
        "tariff_definitions",
        ["osd_operator", "tariff_code", "distribution_group", "valid_from"],
    )

    op.add_column("osd_variable_network_rates", sa.Column("zone_name", sa.String(length=60), nullable=True))

    op.add_column(
        "regulatory_periods",
        sa.Column("excise_per_kwh", sa.Numeric(precision=8, scale=6), nullable=False, server_default="0"),
    )
    op.alter_column("regulatory_periods", "excise_per_kwh", server_default=None)
    op.add_column("regulatory_periods", sa.Column("source", sa.Text(), nullable=True))
    op.execute(sa.text("UPDATE regulatory_periods SET source = :source").bindparams(source=MISSING_SOURCE))
    op.alter_column("regulatory_periods", "source", nullable=False)

    op.create_table(
        "tariff_zone_hours",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tariff_id", sa.Integer(), nullable=False),
        sa.Column("zone_index", sa.Integer(), nullable=False),
        sa.Column("day_type", sa.String(length=20), nullable=False),
        sa.Column("season_from", sa.String(length=5), nullable=False),
        sa.Column("season_to", sa.String(length=5), nullable=False),
        sa.Column("start_minute", sa.SmallInteger(), nullable=False),
        sa.Column("end_minute", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("zone_index >= 1 AND zone_index <= 4", name="chk_zone_hours_zone_range"),
        sa.CheckConstraint(
            "day_type IN ('workday', 'saturday', 'sunday_holiday')", name="chk_zone_hours_day_type"
        ),
        sa.CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440 AND start_minute < end_minute", name="chk_zone_hours_minutes"
        ),
        sa.ForeignKeyConstraint(["tariff_id"], ["tariff_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tariff_zone_hours_tariff_id"), "tariff_zone_hours", ["tariff_id"], unique=False)

    operator_enum = postgresql.ENUM(name="distributionoperatorenum", create_type=False)
    op.create_table(
        "unsupported_tariffs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("osd_operator", operator_enum, nullable=False),
        sa.Column("tariff_code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("osd_operator", "tariff_code", "valid_from", name="uq_unsupported_tariff_validity"),
    )
    op.create_index(
        op.f("ix_unsupported_tariffs_osd_operator"), "unsupported_tariffs", ["osd_operator"], unique=False
    )

    op.drop_index("ix_rcem_price_source_month", table_name="rcem_price_observations")
    op.drop_table("rcem_price_observations")
    op.drop_index("ix_dynamic_price_source_business_date", table_name="dynamic_price_observations")
    op.drop_table("dynamic_price_observations")


def downgrade() -> None:
    op.create_table(
        "dynamic_price_observations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("price_pln_mwh", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "interval_start", name="uq_dynamic_price_source_interval"),
    )
    op.create_index(
        "ix_dynamic_price_source_business_date", "dynamic_price_observations", ["source", "business_date"]
    )
    op.execute(
        "INSERT INTO dynamic_price_observations "
        "(id, source, interval_start, interval_minutes, business_date, price_pln_mwh, created_at, updated_at) "
        "SELECT id, source, interval_start, interval_minutes, business_date, price_pln_mwh, created_at, updated_at "
        "FROM rce_price_observations"
    )
    op.create_table(
        "rcem_price_observations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("price_month", sa.Date(), nullable=False),
        sa.Column("price_pln_mwh", sa.Numeric(12, 4), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("source", "price_month", name="uq_rcem_price_source_month"),
    )
    op.create_index("ix_rcem_price_source_month", "rcem_price_observations", ["source", "price_month"])
    # Przed zmianą była jedna definicja oferty dynamicznej na okres (z dystrybucją G11).
    op.execute("DELETE FROM tariff_definitions WHERE tariff_code::text = 'DYNAMIC' AND distribution_group::text <> 'G11'")
    op.drop_constraint("uq_osd_tariff_validity", "tariff_definitions", type_="unique")
    op.create_unique_constraint(
        "uq_osd_tariff_validity", "tariff_definitions", ["osd_operator", "tariff_code", "valid_from"]
    )
    # Wartości G12N i G12R zostają w typie tarifftypeenum: PostgreSQL nie usuwa wartości enuma, a ponowny
    # upgrade dodaje je z IF NOT EXISTS. Definicje z tymi kodami trzeba usunąć przed cofnięciem.
    op.execute("DELETE FROM tariff_definitions WHERE tariff_code IN ('G12N', 'G12R')")
    op.drop_index(op.f("ix_unsupported_tariffs_osd_operator"), table_name="unsupported_tariffs")
    op.drop_table("unsupported_tariffs")
    op.drop_index(op.f("ix_tariff_zone_hours_tariff_id"), table_name="tariff_zone_hours")
    op.drop_table("tariff_zone_hours")
    op.drop_column("regulatory_periods", "source")
    op.drop_column("regulatory_periods", "excise_per_kwh")
    op.drop_column("osd_variable_network_rates", "zone_name")
    for column in (
        "required_billing_cycle_months", "market_price_cap_mwh", "market_price_floor_mwh",
        "prosumer_margin_per_kwh", "energy_price_cap_per_kwh", "energy_includes_excise", "distribution_group",
        "trade_fee_monthly", "prosumer_trade_fee_monthly",
        "energy_source", "distribution_source", "energy_valid_to", "energy_valid_from",
        "distribution_valid_to", "distribution_valid_from", "name",
    ):
        op.drop_column("tariff_definitions", column)
