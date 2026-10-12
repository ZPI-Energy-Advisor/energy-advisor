"""dodanie tabel dynamic_price_observations i price_sync_runs

Revision ID: c4d7e2a1f9b3
Revises: b3f1c8d2a9e7
Create Date: 2026-10-11 18:00:00.000000

Ceny taryfy dynamicznej pochodzą teraz z tabeli dynamic_price_observations (zasilanej
przez worker synchronizacji), więc usuwamy z tariff_rates sztuczne stawki seedowane
dla taryf typu "dynamiczna". Downgrade nie odtwarza tych stawek.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d7e2a1f9b3'
down_revision: Union[str, Sequence[str], None] = 'b3f1c8d2a9e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('dynamic_price_observations',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('interval_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('interval_minutes', sa.SmallInteger(), nullable=False),
    sa.Column('business_date', sa.Date(), nullable=False),
    sa.Column('price_pln_mwh', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'interval_start', name='uq_dynamic_price_source_interval')
    )
    op.create_index('ix_dynamic_price_source_business_date', 'dynamic_price_observations', ['source', 'business_date'], unique=False)

    op.create_table('price_sync_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.Column('trigger', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('date_from', sa.Date(), nullable=False),
    sa.Column('date_to', sa.Date(), nullable=False),
    sa.Column('days_requested', sa.Integer(), nullable=False),
    sa.Column('days_synced', sa.Integer(), nullable=False),
    sa.Column('records_upserted', sa.Integer(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_price_sync_runs_source_started_at', 'price_sync_runs', ['source', 'started_at'], unique=False)

    op.execute(
        "DELETE FROM tariff_rates "
        "WHERE tariff_id IN (SELECT id FROM tariffs WHERE type = 'dynamiczna')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_price_sync_runs_source_started_at', table_name='price_sync_runs')
    op.drop_table('price_sync_runs')
    op.drop_index('ix_dynamic_price_source_business_date', table_name='dynamic_price_observations')
    op.drop_table('dynamic_price_observations')
