"""dodanie tabel urządzeń z pliku urządzeń (JSON)

Revision ID: c33cfa78046e
Revises: 7c4e9a1b2d6f
Create Date: 2026-10-26 12:00:00.000000

Słowniki kategorii i typów są seedowane według docs/devices-file-format.md. Lista jest tu
zamrożona (migracja nie importuje kodu aplikacji); zgodność z walidatorem pilnuje test
tests/test_device_repository.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c33cfa78046e'
down_revision: Union[str, Sequence[str], None] = '7c4e9a1b2d6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEVICE_CATEGORIES = ["AGD", "Ogrzewanie", "OZE", "Oświetlenie", "RTV/IT", "Pojazd elektryczny", "Inne"]
DEVICE_TYPES = [
    ("washing_machine", "Pralka"),
    ("tumble_dryer", "Suszarka do ubrań"),
    ("dishwasher", "Zmywarka"),
    ("fridge", "Lodówka"),
    ("freezer", "Zamrażarka"),
    ("induction_hob", "Płyta indukcyjna"),
    ("oven", "Piekarnik"),
    ("microwave", "Kuchenka mikrofalowa"),
    ("kettle", "Czajnik"),
    ("coffee_machine", "Ekspres do kawy"),
    ("vacuum_cleaner", "Odkurzacz"),
    ("heat_pump", "Pompa ciepła"),
    ("electric_heater", "Grzejnik elektryczny"),
    ("water_heater", "Podgrzewacz wody"),
    ("ventilation", "Rekuperator / wentylacja"),
    ("pv_inverter", "Instalacja PV"),
    ("light", "Oświetlenie"),
    ("tv", "Telewizor"),
    ("computer", "Komputer"),
    ("router", "Router"),
    ("ev_charger", "Ładowarka EV"),
    ("hair_dryer", "Suszarka do włosów"),
    ("other", "Inne urządzenie"),
]


def upgrade() -> None:
    """Upgrade schema."""
    categories = op.create_table('device_categories',
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('code')
    )
    types = op.create_table('device_types',
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('label', sa.String(length=80), nullable=False),
    sa.PrimaryKeyConstraint('code')
    )

    op.create_table('device_instances',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('energy_data_file_id', sa.UUID(), nullable=False),
    sa.Column('source_device_id', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('device_type', sa.String(length=40), nullable=False),
    sa.Column('device_category', sa.String(length=40), nullable=False),
    sa.Column('max_power_kw', sa.Float(), nullable=True),
    sa.Column('flexibility_mode', sa.String(length=20), nullable=False),
    sa.Column('allowed_window_from', sa.Time(), nullable=True),
    sa.Column('allowed_window_to', sa.Time(), nullable=True),
    sa.Column('max_shift_min', sa.Integer(), nullable=True),
    sa.CheckConstraint(
        "flexibility_mode IN ('fixed', 'shiftable', 'interruptible')",
        name='ck_device_instance_flexibility_mode',
    ),
    sa.ForeignKeyConstraint(['device_category'], ['device_categories.code']),
    sa.ForeignKeyConstraint(['device_type'], ['device_types.code']),
    sa.ForeignKeyConstraint(['energy_data_file_id'], ['energy_data_files.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('energy_data_file_id', 'source_device_id', name='uq_device_instance_file_device')
    )
    op.create_index(op.f('ix_device_instances_energy_data_file_id'), 'device_instances', ['energy_data_file_id'], unique=False)
    op.create_index(op.f('ix_device_instances_user_id'), 'device_instances', ['user_id'], unique=False)

    op.create_table('device_programs',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('device_instance_id', sa.UUID(), nullable=False),
    sa.Column('source_program_id', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('duration_min', sa.Integer(), nullable=False),
    sa.Column('profile_kwh', postgresql.ARRAY(sa.Float()), nullable=False),
    sa.ForeignKeyConstraint(['device_instance_id'], ['device_instances.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device_instance_id', 'source_program_id', name='uq_device_program_instance_program')
    )

    op.create_table('device_actions',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('device_instance_id', sa.UUID(), nullable=False),
    sa.Column('device_program_id', sa.BigInteger(), nullable=True),
    sa.Column('source_action_id', sa.String(length=100), nullable=False),
    sa.Column('action_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('action_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('energy_kwh', sa.Float(), nullable=False),
    sa.Column('plugged_in', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('action_start < action_end', name='ck_device_action_start_before_end'),
    sa.ForeignKeyConstraint(['device_instance_id'], ['device_instances.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['device_program_id'], ['device_programs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device_instance_id', 'source_action_id', name='uq_device_action_instance_action')
    )
    op.create_index(op.f('ix_device_actions_device_instance_id'), 'device_actions', ['device_instance_id'], unique=False)
    op.create_index(op.f('ix_device_actions_device_program_id'), 'device_actions', ['device_program_id'], unique=False)

    op.create_table('device_slot_usage',
    sa.Column('device_action_id', sa.BigInteger(), nullable=False),
    sa.Column('slot_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('energy_data_file_id', sa.UUID(), nullable=False),
    sa.Column('kwh', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['device_action_id'], ['device_actions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['energy_data_file_id'], ['energy_data_files.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('device_action_id', 'slot_start')
    )
    op.create_index('ix_device_slot_usage_file_slot', 'device_slot_usage', ['energy_data_file_id', 'slot_start'], unique=False)

    op.bulk_insert(categories, [{"code": code} for code in DEVICE_CATEGORIES])
    op.bulk_insert(types, [{"code": code, "label": label} for code, label in DEVICE_TYPES])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_device_slot_usage_file_slot', table_name='device_slot_usage')
    op.drop_table('device_slot_usage')
    op.drop_index(op.f('ix_device_actions_device_program_id'), table_name='device_actions')
    op.drop_index(op.f('ix_device_actions_device_instance_id'), table_name='device_actions')
    op.drop_table('device_actions')
    op.drop_table('device_programs')
    op.drop_index(op.f('ix_device_instances_user_id'), table_name='device_instances')
    op.drop_index(op.f('ix_device_instances_energy_data_file_id'), table_name='device_instances')
    op.drop_table('device_instances')
    op.drop_table('device_types')
    op.drop_table('device_categories')
