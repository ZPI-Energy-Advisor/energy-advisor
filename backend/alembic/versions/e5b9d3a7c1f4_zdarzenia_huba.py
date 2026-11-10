"""Zdarzenia urządzeń z webhooka huba Smart Home (ZP-95).

Revision ID: e5b9d3a7c1f4
Revises: c3e8a1f5d7b2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e5b9d3a7c1f4"
down_revision: Union[str, Sequence[str], None] = "c3e8a1f5d7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "home_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("simulation_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.String(length=100), nullable=False),
        sa.Column("sim_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("energy_kwh", sa.Float(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(type = 'energy_report') = (energy_kwh IS NOT NULL AND interval_start IS NOT NULL)",
            name="ck_home_events_energy_report",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "ix_home_events_energy", "home_events", ["simulation_id", "sim_time"],
        postgresql_where=sa.text("type = 'energy_report'"),
    )
    op.create_index("ix_home_events_user_received", "home_events", ["user_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_home_events_user_received", table_name="home_events")
    op.drop_index("ix_home_events_energy", table_name="home_events")
    op.drop_table("home_events")
