"""Rachunek przed i po planie w przebiegu symulacji (ZP-114): migawka cen planu i zapisany raport.

Revision ID: d4b8e2f6a1c3
Revises: c6f2a9d4e8b1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d4b8e2f6a1c3"
down_revision: Union[str, Sequence[str], None] = "c6f2a9d4e8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plan_runs", sa.Column("tariff", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("plan_runs", sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    # Starty i końce urządzeń przebiegu w raporcie (ręczne włączenia, przerwane akcje): tysiące zdarzeń
    # energii na dobę, a tych kilkadziesiąt.
    op.create_index(
        "ix_home_events_actions", "home_events", ["simulation_id"],
        postgresql_where=sa.text("type IN ('device_started', 'device_finished')"),
    )


def downgrade() -> None:
    op.drop_index("ix_home_events_actions", table_name="home_events")
    op.drop_column("plan_runs", "report")
    op.drop_column("plan_runs", "tariff")
