"""ZPI-16: Dodanie tabel Tariffs i TariffRates

Revision ID: 73df67d58350
Revises: 
Create Date: 2026-05-19 14:01:17.899682

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = '73df67d58350'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
