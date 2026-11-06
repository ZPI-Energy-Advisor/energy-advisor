"""Operator STOEN w typie distributionoperatorenum.

Migracja ca5e69978b80 utworzyła typ bez STOEN, choć profil pozwala go wybrać, więc definicji
taryfy dla STOEN nie dało się zapisać.

Revision ID: 5f9ecf30a3c9
Revises: b8d4f2a6c9e1
"""
from typing import Sequence, Union

from alembic import op


revision: str = "5f9ecf30a3c9"
down_revision: Union[str, Sequence[str], None] = "b8d4f2a6c9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE distributionoperatorenum ADD VALUE IF NOT EXISTS 'STOEN'")


def downgrade() -> None:
    # PostgreSQL nie usuwa wartości z enuma. Zostawienie STOEN niczego nie psuje: wcześniejsza
    # migracja ca5e69978b80 przy cofaniu i tak zamienia kolumnę na tekst i usuwa cały typ.
    pass
