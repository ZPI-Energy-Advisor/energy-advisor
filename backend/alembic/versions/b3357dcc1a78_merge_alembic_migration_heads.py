"""Merge Alembic migration heads

Revision ID: b3357dcc1a78
Revises: b2c3d4e5f6a7, 7eb07436f4dc
Create Date: 2026-11-01 19:51:23.371186

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = 'b3357dcc1a78'
down_revision: Union[str, Sequence[str], None] = ('b2c3d4e5f6a7', '7eb07436f4dc')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
