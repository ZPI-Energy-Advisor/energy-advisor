"""Zapisane scalanie plików urządzeń: dokładny okres pliku i flaga superseded kwadransów.

Kwadrans urządzenia należy do najnowszego pliku (kolejność uploadu), który zawiera to urządzenie
i obejmuje ten kwadrans swoim okresem. Pozostałe wersje mają superseded = true i nie są liczone.

Okres istniejących plików pochodzi z serii zużycia zapisanej przy imporcie (usage_15min w wynikach
symulacji), a gdy jej nie ma - z akcji urządzeń albo surowych odczytów.

Revision ID: b8d4f2a6c9e1
Revises: a7c3e9f1b2d4
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Sequence, Union
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa


revision: str = "b8d4f2a6c9e1"
down_revision: Union[str, Sequence[str], None] = "a7c3e9f1b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCAL_TIMEZONE = ZoneInfo("Europe/Warsaw")
SLOT = timedelta(minutes=15)

# Po dodaniu kolumny wszystkie flagi są false, więc wystarczy oznaczyć przykryte kwadranse.
# Najpierw przedziały przykrycia dla par (plik, urządzenie) - jest ich kilka na plik - a potem
# jeden UPDATE po indeksie (plik, superseded, kwadrans), tak jak w DeviceRepository.
MARK_ALL_COVERED = """
WITH cover AS MATERIALIZED (
    SELECT own.id AS file_id, own_link.device_instance_id AS device_id,
           newer.period_start AS cover_start, newer.period_end AS cover_end
    FROM energy_data_files AS own
    JOIN device_instance_files AS own_link ON own_link.energy_data_file_id = own.id
    JOIN device_instance_files AS newer_link ON newer_link.device_instance_id = own_link.device_instance_id
    JOIN energy_data_files AS newer ON newer.id = newer_link.energy_data_file_id
    WHERE (newer.uploaded_at, newer.id) > (own.uploaded_at, own.id)
      AND newer.period_start IS NOT NULL AND newer.period_end IS NOT NULL
)
UPDATE device_slot_usage AS slot SET superseded = true
FROM cover, device_actions AS action
WHERE slot.energy_data_file_id = cover.file_id AND NOT slot.superseded
  AND slot.slot_start >= cover.cover_start AND slot.slot_start < cover.cover_end
  AND action.id = slot.device_action_id AND action.device_instance_id = cover.device_id
"""


def _local_slot_utc(day: str, slot: int) -> datetime:
    local = datetime.combine(date.fromisoformat(day), time(), LOCAL_TIMEZONE) + slot * SLOT
    return local.astimezone(timezone.utc)


def _period_from_usage(usage: dict) -> tuple[datetime, datetime] | None:
    slots = [(day, index) for day, values in usage.items() for index, kwh in enumerate(values) if kwh is not None]
    if not slots:
        return None
    first, last = min(slots), max(slots)
    return _local_slot_utc(*first), _local_slot_utc(*last) + SLOT


def _backfill_periods(connection) -> None:
    files = connection.execute(sa.text("SELECT id FROM energy_data_files")).scalars().all()
    for file_id in files:
        results = connection.execute(
            sa.text(
                "SELECT results FROM simulations WHERE energy_data_file_id = :id "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"id": file_id},
        ).scalar()
        period = _period_from_usage(results.get("usage_15min") or {}) if isinstance(results, dict) else None
        if period is None:
            period = connection.execute(
                sa.text(
                    "SELECT min(action_start), max(action_end) FROM device_actions WHERE energy_data_file_id = :id"
                ),
                {"id": file_id},
            ).one()
        if period[0] is None:
            # Surowe odczyty są w czasie lokalnym bez strefy.
            period = connection.execute(
                sa.text(
                    "SELECT min(measured_at) AT TIME ZONE 'Europe/Warsaw', "
                    "(max(measured_at) + interval '15 minutes') AT TIME ZONE 'Europe/Warsaw' "
                    "FROM energy_readings WHERE energy_data_file_id = :id"
                ),
                {"id": file_id},
            ).one()
        if period[0] is not None:
            connection.execute(
                sa.text("UPDATE energy_data_files SET period_start = :start, period_end = :end WHERE id = :id"),
                {"start": period[0], "end": period[1], "id": file_id},
            )


def upgrade() -> None:
    op.add_column("energy_data_files", sa.Column("period_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("energy_data_files", sa.Column("period_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "device_slot_usage",
        sa.Column("superseded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_device_slot_usage_file_superseded_slot",
        "device_slot_usage",
        ["energy_data_file_id", "superseded", "slot_start"],
    )
    # Nowy indeks obsługuje też zapytania po (plik, kwadrans), a każdy indeks spowalnia zmianę flag.
    op.drop_index("ix_device_slot_usage_file_slot", table_name="device_slot_usage")
    connection = op.get_bind()
    _backfill_periods(connection)
    connection.execute(sa.text(MARK_ALL_COVERED))


def downgrade() -> None:
    op.create_index("ix_device_slot_usage_file_slot", "device_slot_usage", ["energy_data_file_id", "slot_start"])
    op.drop_index("ix_device_slot_usage_file_superseded_slot", table_name="device_slot_usage")
    op.drop_column("device_slot_usage", "superseded")
    op.drop_column("energy_data_files", "period_end")
    op.drop_column("energy_data_files", "period_start")
