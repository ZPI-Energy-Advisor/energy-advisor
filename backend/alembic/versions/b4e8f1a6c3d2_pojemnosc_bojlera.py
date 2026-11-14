"""Pojemność zbiornika bojlera z pliku urządzeń (ZP-112).

Revision ID: b4e8f1a6c3d2
Revises: a7d2e4c9b1f3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4e8f1a6c3d2"
down_revision: Union[str, Sequence[str], None] = "a7d2e4c9b1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("device_instances", sa.Column("tank_liters", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("device_instances", "tank_liters")
