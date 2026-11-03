"""Dostosowanie profili użytkowników do schematu Pydantic.

Revision ID: c6e7f8a9b0c1
Revises: d1c148f62de7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "d1c148f62de7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("user_profiles", "connection", new_column_name="base_info")
    op.alter_column(
        "user_profiles",
        "consumption",
        new_column_name="consumption_and_tariff",
    )
    op.drop_column("user_profiles", "commercial_offer")


def downgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column(
            "commercial_offer",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.alter_column(
        "user_profiles",
        "consumption_and_tariff",
        new_column_name="consumption",
    )
    op.alter_column("user_profiles", "base_info", new_column_name="connection")
