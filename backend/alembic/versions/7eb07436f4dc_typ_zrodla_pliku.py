"""typ źródła pliku: licznik albo urządzenia

Revision ID: 7eb07436f4dc
Revises: c33cfa78046e
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7eb07436f4dc"
down_revision: Union[str, Sequence[str], None] = "c33cfa78046e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "energy_data_files",
        sa.Column("source_type", sa.String(length=20), nullable=False, server_default="meter"),
    )
    op.execute("""
        UPDATE energy_data_files f
        SET source_type = 'devices'
        WHERE EXISTS (
            SELECT 1 FROM simulations s
            WHERE s.energy_data_file_id = f.id
              AND s.results -> 'import_report' ->> 'detected_format' = 'devices'
        )
    """)
    op.execute("""
        UPDATE simulations s
        SET results = jsonb_set(
            jsonb_set(
                s.results || jsonb_build_object('actions_per_day', COALESCE(counts.per_day, '{}'::jsonb)),
                '{statistics,data_source}', '"devices"'
            ),
            '{statistics,records_count}', to_jsonb(COALESCE(counts.total, 0))
        )
        FROM energy_data_files f
        LEFT JOIN (
            SELECT energy_data_file_id, jsonb_object_agg(day, actions) AS per_day, sum(actions) AS total
            FROM (
                SELECT energy_data_file_id,
                       to_char(action_start AT TIME ZONE 'Europe/Warsaw', 'YYYY-MM-DD') AS day,
                       count(*) AS actions
                FROM device_actions
                GROUP BY 1, 2
            ) per_file_day
            GROUP BY 1
        ) counts ON counts.energy_data_file_id = f.id
        WHERE f.id = s.energy_data_file_id AND f.source_type = 'devices'
    """)
    _copy_records_count_from_simulations()


def downgrade() -> None:
    op.execute("""
        UPDATE simulations s
        SET results = jsonb_set(s.results - 'actions_per_day', '{statistics,records_count}', to_jsonb(slots.total))
        FROM (
            SELECT s2.id, count(*) AS total
            FROM simulations s2,
                 jsonb_each(s2.results -> 'usage_15min') AS day(key, value),
                 jsonb_array_elements(day.value) AS slot(value)
            WHERE slot.value <> 'null'::jsonb
            GROUP BY s2.id
        ) slots
        WHERE slots.id = s.id AND s.results ? 'actions_per_day'
    """)
    _copy_records_count_from_simulations()
    op.execute("""
        UPDATE simulations
        SET results = results #- '{statistics,data_source}'
        WHERE results -> 'statistics' ? 'data_source'
    """)
    op.drop_column("energy_data_files", "source_type")


def _copy_records_count_from_simulations() -> None:
    op.execute("""
        UPDATE energy_data_files f
        SET records_count = (s.results -> 'statistics' ->> 'records_count')::int
        FROM simulations s
        WHERE s.energy_data_file_id = f.id AND f.source_type = 'devices'
    """)
