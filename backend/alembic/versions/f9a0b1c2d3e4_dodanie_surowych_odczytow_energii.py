"""Dodanie niezależnego magazynu surowych odczytów energii.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "energy_readings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("energy_data_file_id", sa.UUID(), nullable=False),
        sa.Column("measured_at", sa.DateTime(), nullable=False),
        sa.Column("energy_kwh", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.ForeignKeyConstraint(
            ["energy_data_file_id"],
            ["energy_data_files.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "energy_data_file_id",
            "measured_at",
            name="uq_energy_reading_file_timestamp",
        ),
    )
    op.create_index(
        "ix_energy_readings_energy_data_file_id",
        "energy_readings",
        ["energy_data_file_id"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO energy_readings (
            energy_data_file_id,
            measured_at,
            energy_kwh
        )
        SELECT
            s.energy_data_file_id,
            (day_entry.key::date
                + ((slot_entry.ordinality - 1) * interval '15 minutes'))::timestamp,
            slot_entry.value::numeric
        FROM simulations AS s
        CROSS JOIN LATERAL jsonb_each(s.results->'usage_15min') AS day_entry(key, slots)
        CROSS JOIN LATERAL jsonb_array_elements(day_entry.slots)
            WITH ORDINALITY AS slot_entry(value, ordinality)
        WHERE slot_entry.value IS NOT NULL
          AND slot_entry.value <> 'null'::jsonb
        ON CONFLICT (energy_data_file_id, measured_at) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_energy_readings_energy_data_file_id", table_name="energy_readings")
    op.drop_table("energy_readings")
