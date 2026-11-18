"""Pomieszczenie urządzenia z pliku urządzeń (ZP-109).

Tylko wartość z pliku: urządzenia bez pola `room` (także wgrane wcześniej) dostają pomieszczenie domyślne
przy odczycie (app/services/device_rooms.py), więc migracja nie uzupełnia istniejących wierszy.

Revision ID: d3a8c5e1f7b2
Revises: c6f2a9d4e8b1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3a8c5e1f7b2"
down_revision: Union[str, Sequence[str], None] = "c6f2a9d4e8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("device_instances", sa.Column("room", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("device_instances", "room")
