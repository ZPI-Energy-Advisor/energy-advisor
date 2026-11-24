"""Pogoda dla komórek siatki ok. 0,1° (ZP-117).

Revision ID: b3e8f1a6c4d2
Revises: a7d3e9c2b5f1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b3e8f1a6c4d2"
down_revision: Union[str, Sequence[str], None] = "a7d3e9c2b5f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weather_observations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("latitude", sa.Numeric(4, 1), nullable=False),
        sa.Column("longitude", sa.Numeric(4, 1), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("temperature_c", sa.Numeric(5, 2), nullable=True),
        sa.Column("cloud_cover_pct", sa.SmallInteger(), nullable=True),
        sa.Column("ghi_w_m2", sa.Numeric(7, 2), nullable=True),
        sa.Column("tilted_w_m2", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("latitude", "longitude", "source", "interval_start", name="uq_weather_cell_source_interval"),
    )
    op.create_index("ix_weather_cell_interval", "weather_observations", ["latitude", "longitude", "interval_start"])


def downgrade() -> None:
    op.drop_index("ix_weather_cell_interval", table_name="weather_observations")
    op.drop_table("weather_observations")
