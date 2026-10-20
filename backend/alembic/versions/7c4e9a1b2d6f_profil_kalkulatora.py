"""Przechowywanie pełnego profilu kalkulatora użytkownika.

Revision ID: 7c4e9a1b2d6f
Revises: f2a7c9d4e1b6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7c4e9a1b2d6f"
down_revision: Union[str, Sequence[str], None] = "f2a7c9d4e1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("base_info", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.add_column(
        "user_profiles",
        sa.Column(
            "consumption_and_tariff",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
    )
    op.add_column(
        "user_profiles",
        sa.Column("pv_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.add_column(
        "user_profiles",
        sa.Column(
            "commercial_offer",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "user_profiles",
        sa.Column(
            "distribution_fees",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
    )

    op.drop_constraint("user_profiles_current_tariff_id_fkey", "user_profiles", type_="foreignkey")
    op.drop_column("user_profiles", "current_tariff_id")
    op.drop_column("user_profiles", "type_of_property")
    op.drop_column("user_profiles", "heating_area_m2")
    op.drop_column("user_profiles", "place_latitude")
    op.drop_column("user_profiles", "place_longitude")
    op.drop_column("user_profiles", "number_of_residents")


def downgrade() -> None:
    op.add_column("user_profiles", sa.Column("type_of_property", sa.String(), nullable=True))
    op.add_column("user_profiles", sa.Column("heating_area_m2", sa.Float(), nullable=True))
    op.add_column("user_profiles", sa.Column("place_latitude", sa.Float(), nullable=True))
    op.add_column("user_profiles", sa.Column("place_longitude", sa.Float(), nullable=True))
    op.add_column("user_profiles", sa.Column("number_of_residents", sa.Integer(), nullable=True))
    op.add_column("user_profiles", sa.Column("current_tariff_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "user_profiles_current_tariff_id_fkey",
        "user_profiles",
        "tariffs",
        ["current_tariff_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("user_profiles", "distribution_fees")
    op.drop_column("user_profiles", "commercial_offer")
    op.drop_column("user_profiles", "pv_config")
    op.drop_column("user_profiles", "consumption_and_tariff")
    op.drop_column("user_profiles", "base_info")
