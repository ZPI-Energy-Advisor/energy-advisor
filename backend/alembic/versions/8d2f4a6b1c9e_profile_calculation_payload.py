"""Dostosowanie profilu do payloadu kalkulacji.

Revision ID: 8d2f4a6b1c9e
Revises: 7c4e9a1b2d6f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "8d2f4a6b1c9e"
down_revision: Union[str, Sequence[str], None] = "7c4e9a1b2d6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("user_profiles", "base_info", new_column_name="connection")
    op.alter_column(
        "user_profiles",
        "consumption_and_tariff",
        new_column_name="consumption",
    )
    op.drop_column("user_profiles", "distribution_fees")


def downgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column(
            "distribution_fees",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.alter_column("user_profiles", "consumption", new_column_name="consumption_and_tariff")
    op.alter_column("user_profiles", "connection", new_column_name="base_info")
