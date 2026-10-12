"""narzut i VAT taryf dynamicznych w tabeli tariffs

Revision ID: d8a3f6b2c1e5
Revises: c4d7e2a1f9b3
Create Date: 2026-10-11 21:00:00.000000

Narzut netto (dystrybucja, opłaty, marża sprzedawcy) i VAT są częścią definicji taryfy,
tak jak stawki G11/G12 w tariff_rates - dlatego trzymamy je w bazie, a nie w konfiguracji.
Istniejące taryfy typu "dynamiczna" dostają wartości domyślne 0.40 PLN/kWh i 23%.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8a3f6b2c1e5'
down_revision: Union[str, Sequence[str], None] = 'c4d7e2a1f9b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tariffs', sa.Column('markup_pln_kwh', sa.Numeric(precision=10, scale=4), nullable=True))
    op.add_column('tariffs', sa.Column('vat_rate', sa.Numeric(precision=5, scale=4), nullable=True))

    op.execute(
        "UPDATE tariffs SET markup_pln_kwh = 0.40, vat_rate = 0.23 "
        "WHERE type = 'dynamiczna' AND markup_pln_kwh IS NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tariffs', 'vat_rate')
    op.drop_column('tariffs', 'markup_pln_kwh')
