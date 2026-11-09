"""Ceny RCEm z powrotem.

Nowelizacja ustawy o OZE z 27.11.2024 (Dz.U. 2024 poz. 1847) przywróciła od 1.02.2025 rozliczenie po miesięcznej
cenie RCEm dla prosumentów, którzy pierwszy raz oddali energię do sieci przed 1.07.2024 (mogą przejść na RCE).

Revision ID: a7c3e9f1d2b4
Revises: 4b7d2e9c1a60
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e9f1d2b4"
down_revision: Union[str, Sequence[str], None] = "4b7d2e9c1a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("ix_rcem_price_source_month", table_name="rcem_price_observations")
    op.drop_table("rcem_price_observations")
