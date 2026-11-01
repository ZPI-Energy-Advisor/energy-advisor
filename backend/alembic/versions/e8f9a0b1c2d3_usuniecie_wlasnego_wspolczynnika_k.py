"""Usunięcie możliwości ustawiania własnego współczynnika k.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE user_profiles
        SET pv_config = pv_config - 'custom_k_factor'
        WHERE pv_config ? 'custom_k_factor'
        """
    )


def downgrade() -> None:
    pass
