"""Przebiegi planu dnia w symulacji Smart Home (ZP-113) i indeks awarii urządzeń w zdarzeniach huba.

Revision ID: c6f2a9d4e8b1
Revises: b4e8f1a6c3d2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c6f2a9d4e8b1"
down_revision: Union[str, Sequence[str], None] = "b4e8f1a6c3d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("simulation_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("horizon_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("history_day", sa.Date(), nullable=True),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("replay", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("replayed_devices", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_sim_time", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'ended', 'superseded')", name="ck_plan_run_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["day_plan_id"], ["day_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_runs_user_started", "plan_runs", ["user_id", "started_at"])
    # Indeks pod klucz obcy: usunięcie planu (np. razem z kontem) nie skanuje całej tabeli przebiegów.
    op.create_index("ix_plan_runs_day_plan_id", "plan_runs", ["day_plan_id"])
    op.create_index(
        "ix_home_events_errors", "home_events", ["simulation_id"],
        postgresql_where=sa.text("type = 'device_error'"),
    )


def downgrade() -> None:
    op.drop_index("ix_home_events_errors", table_name="home_events")
    op.drop_index("ix_plan_runs_day_plan_id", table_name="plan_runs")
    op.drop_index("ix_plan_runs_user_started", table_name="plan_runs")
    op.drop_table("plan_runs")
