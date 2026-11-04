"""Odczyty dwukierunkowe: energia oddana do sieci w osobnej kolumnie.

Wcześniej produkcja PV była zapisywana jako ujemne energy_kwh. Migracja przenosi takie wartości
do exported_kwh, więc energy_kwh oznacza odtąd wyłącznie pobór z sieci.

Revision ID: a7c3e9f1b2d4
Revises: ca5e69978b80
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e9f1b2d4"
down_revision: Union[str, Sequence[str], None] = "ca5e69978b80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "energy_readings",
        sa.Column(
            "exported_kwh",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
            server_default="0",
        ),
    )
    op.execute(
        "UPDATE energy_readings SET exported_kwh = -energy_kwh, energy_kwh = 0 WHERE energy_kwh < 0"
    )


def downgrade() -> None:
    # Kwadrans z poborem i oddaniem naraz nie mieści się w jednej wartości ze znakiem: zostaje saldo.
    op.execute("UPDATE energy_readings SET energy_kwh = energy_kwh - exported_kwh WHERE exported_kwh > 0")
    op.drop_column("energy_readings", "exported_kwh")
