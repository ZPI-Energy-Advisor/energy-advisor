"""Ustawienia planu na jutro: wymagania urządzeń użytkownika (ZP-111).

Revision ID: f3b8c2d6a9e1
Revises: e5b9d3a7c1f4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f3b8c2d6a9e1"
down_revision: Union[str, Sequence[str], None] = "e5b9d3a7c1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "planning_templates",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("devices", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("planning_templates")
