"""Przeniesienie początku okresu rozliczeniowego do base_info.

Revision ID: d7e8f9a0b1c2
Revises: c6e7f8a9b0c1
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE user_profiles
        SET base_info = base_info || jsonb_build_object(
            'billing_period_start_date',
            consumption_and_tariff->'billing_period_start_date'
        ),
            consumption_and_tariff = consumption_and_tariff - 'billing_period_start_date'
        WHERE consumption_and_tariff ? 'billing_period_start_date'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE user_profiles
        SET consumption_and_tariff = consumption_and_tariff || jsonb_build_object(
            'billing_period_start_date',
            base_info->'billing_period_start_date'
        ),
            base_info = base_info - 'billing_period_start_date'
        WHERE base_info ? 'billing_period_start_date'
        """
    )
