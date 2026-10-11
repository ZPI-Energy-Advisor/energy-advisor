"""dodanie tabeli energy_data_files i powiazanie symulacji z plikiem

Revision ID: b3f1c8d2a9e7
Revises: e801c64903f9
Create Date: 2026-10-11 12:00:00.000000

Istniejące symulacje nie mają zapisanej nazwy pliku, dlatego dla każdej z nich
tworzony jest rekord pliku "Import archiwalny" (z tym samym id co symulacja),
z zakresem dat odczytanym z results.statistics. Dzięki temu stare wyniki
są widoczne na liście plików i nic nie ginie.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f1c8d2a9e7'
down_revision: Union[str, Sequence[str], None] = 'e801c64903f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('energy_data_files',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    sa.Column('data_start', sa.Date(), nullable=True),
    sa.Column('data_end', sa.Date(), nullable=True),
    sa.Column('records_count', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_energy_data_files_user_id'), 'energy_data_files', ['user_id'], unique=False)

    op.add_column('simulations', sa.Column('energy_data_file_id', sa.UUID(), nullable=True))

    op.execute(
        """
        INSERT INTO energy_data_files (id, user_id, file_name, uploaded_at, data_start, data_end, records_count, status)
        SELECT
            s.id,
            s.user_id,
            'Import archiwalny',
            COALESCE(s.created_at, now()),
            (s.results -> 'statistics' ->> 'data_start')::date,
            (s.results -> 'statistics' ->> 'data_end')::date,
            NULL,
            'completed'
        FROM simulations s
        """
    )
    op.execute("UPDATE simulations SET energy_data_file_id = id")

    op.alter_column('simulations', 'energy_data_file_id', nullable=False)
    op.create_index(op.f('ix_simulations_energy_data_file_id'), 'simulations', ['energy_data_file_id'], unique=False)
    op.create_foreign_key(
        'fk_simulations_energy_data_file_id',
        'simulations', 'energy_data_files',
        ['energy_data_file_id'], ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_simulations_energy_data_file_id', 'simulations', type_='foreignkey')
    op.drop_index(op.f('ix_simulations_energy_data_file_id'), table_name='simulations')
    op.drop_column('simulations', 'energy_data_file_id')
    op.drop_index(op.f('ix_energy_data_files_user_id'), table_name='energy_data_files')
    op.drop_table('energy_data_files')
