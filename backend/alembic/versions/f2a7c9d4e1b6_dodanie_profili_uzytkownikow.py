"""dodanie profili użytkowników

Revision ID: f2a7c9d4e1b6
Revises: d8a3f6b2c1e5
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a7c9d4e1b6"
down_revision: Union[str, Sequence[str], None] = "d8a3f6b2c1e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


property_type = sa.Enum(
    "APARTMENT",
    "SINGLE_FAMILY_HOUSE",
    "TERRACE_HOUSE",
    "RECREATIONAL_COTTAGE",
    "OTHER",
    name="property_type",
)


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type_of_property", property_type, nullable=False),
        sa.Column("heating_area_m2", sa.Float(), nullable=False),
        sa.Column("place_latitude", sa.Float(), nullable=True),
        sa.Column("place_longitude", sa.Float(), nullable=True),
        sa.Column("number_of_residents", sa.Integer(), nullable=False),
        sa.Column("current_tariff_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_tariff_id"], ["tariffs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
    property_type.drop(op.get_bind(), checkfirst=True)
