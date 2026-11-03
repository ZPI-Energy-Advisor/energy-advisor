"""Allow dynamic tariff definitions in the calculation tariff enum."""

from typing import Sequence, Union

from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE tarifftypeenum ADD VALUE IF NOT EXISTS 'DYNAMIC'")


def downgrade() -> None:
    raise RuntimeError(
        "PostgreSQL enum values cannot be removed safely; restore the database before downgrading."
    )
