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

    # Pliki urządzeń wgrane przed tą migracją: typ z raportu importu, liczba rekordów i akcje
    # na dobę (czas lokalny) z zapisanych akcji urządzeń.
    op.execute("""
        UPDATE energy_data_files f
        SET source_type = 'devices',
            records_count = (SELECT count(*) FROM device_actions a WHERE a.energy_data_file_id = f.id)
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
                s.results || jsonb_build_object('actions_per_day', counts.per_day),
                '{statistics,data_source}', '"devices"'
            ),
            '{statistics,records_count}', to_jsonb(counts.total)
        )
        FROM (
            SELECT energy_data_file_id, jsonb_object_agg(day, actions) AS per_day, sum(actions) AS total
            FROM (
                SELECT energy_data_file_id,
                       to_char(action_start AT TIME ZONE 'Europe/Warsaw', 'YYYY-MM-DD') AS day,
                       count(*) AS actions
                FROM device_actions
                GROUP BY 1, 2
            ) per_file_day
            GROUP BY 1
        ) counts
        WHERE counts.energy_data_file_id = s.energy_data_file_id
          AND s.results -> 'import_report' ->> 'detected_format' = 'devices'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE simulations
        SET results = (results - 'actions_per_day') #- '{statistics,data_source}'
        WHERE results ? 'actions_per_day'
    """)
    op.drop_column("energy_data_files", "source_type")
