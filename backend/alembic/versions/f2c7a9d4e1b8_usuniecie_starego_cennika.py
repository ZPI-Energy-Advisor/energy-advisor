"""Usunięcie starego cennika (ZP-104): tabele tariffs i tariff_rates oraz koszty zapisane przy imporcie.

Koszty liczy silnik rachunku z tariff_definitions przy każdym odczycie, więc stary cennik i policzone
z niego przy imporcie `slot_prices`, `tariffs` oraz kolumny cost_*/price_* wykresów nie są już używane.

Revision ID: f2c7a9d4e1b8
Revises: d4b8e2f6a1c3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f2c7a9d4e1b8"
down_revision: Union[str, Sequence[str], None] = "d4b8e2f6a1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_PRICING_KEYS = ("slot_prices", "tariffs")
CHARTS = ("chart_15min", "chart_hourly", "chart_daily")
CHART_PRICE_PREFIXES = ("cost_", "price_")


def without_old_pricing(results: dict) -> dict:
    cleaned = {key: value for key, value in results.items() if key not in OLD_PRICING_KEYS}
    for chart in CHARTS:
        if isinstance(cleaned.get(chart), list):
            cleaned[chart] = [
                {name: value for name, value in row.items() if not name.startswith(CHART_PRICE_PREFIXES)}
                for row in cleaned[chart]
            ]
    return cleaned


def upgrade() -> None:
    op.drop_index(op.f("ix_tariff_rates_id"), table_name="tariff_rates")
    op.drop_table("tariff_rates")
    op.drop_index(op.f("ix_tariffs_id"), table_name="tariffs")
    op.drop_table("tariffs")

    bind = op.get_bind()
    update = sa.text("UPDATE simulations SET results = :results WHERE id = :id").bindparams(
        sa.bindparam("results", type_=postgresql.JSONB)
    )
    ids = bind.execute(sa.text("SELECT id FROM simulations WHERE results ?| array['slot_prices', 'tariffs']")).scalars()
    for simulation_id in list(ids):
        results = bind.execute(sa.text("SELECT results FROM simulations WHERE id = :id"), {"id": simulation_id}).scalar()
        bind.execute(update, {"id": simulation_id, "results": without_old_pricing(results)})


def downgrade() -> None:
    # Odtwarza same, puste tabele: stare stawki i koszty policzone z nich przy imporcie nie wracają.
    op.create_table(
        "tariffs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("markup_pln_kwh", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("vat_rate", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tariffs_id"), "tariffs", ["id"], unique=False)
    op.create_table(
        "tariff_rates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tariff_id", sa.Integer(), nullable=False),
        sa.Column("time_start", sa.Time(), nullable=False),
        sa.Column("time_end", sa.Time(), nullable=False),
        sa.Column("price_per_kwh", sa.DECIMAL(precision=10, scale=4), nullable=False),
        sa.ForeignKeyConstraint(["tariff_id"], ["tariffs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tariff_rates_id"), "tariff_rates", ["id"], unique=False)
