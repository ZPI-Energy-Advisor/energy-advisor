"""Separate interval RCE and monthly RCEm observations."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rce_price_observations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("price_pln_mwh", sa.Numeric(12, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("source", "interval_start", name="uq_rce_price_source_interval"),
    )
    op.create_index(
        "ix_rce_price_source_business_date",
        "rce_price_observations",
        ["source", "business_date"],
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
    op.execute(
        """
        INSERT INTO rce_price_observations
            (id, source, interval_start, interval_minutes, business_date, price_pln_mwh)
        SELECT id, source, interval_start, interval_minutes, business_date, price_pln_mwh
        FROM dynamic_price_observations
        ON CONFLICT (source, interval_start) DO NOTHING
        """
    )
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('rce_price_observations', 'id'),
            COALESCE((SELECT MAX(id) + 1 FROM rce_price_observations), 1),
            false
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_rcem_price_source_month", table_name="rcem_price_observations")
    op.drop_table("rcem_price_observations")
    op.drop_index("ix_rce_price_source_business_date", table_name="rce_price_observations")
    op.drop_table("rce_price_observations")
