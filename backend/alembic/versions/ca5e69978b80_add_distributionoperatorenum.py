"""Add distributionoperatorenum

Revision ID: ca5e69978b80
Revises: b3357dcc1a78
Create Date: 2026-11-01 21:44:10.854551

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ca5e69978b80'
down_revision: Union[str, Sequence[str], None] = 'b3357dcc1a78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    operator_enum = postgresql.ENUM('PGE', 'TAURON', 'ENEA', 'ENERGA', name='distributionoperatorenum')
    operator_enum.create(op.get_bind(), checkfirst=True)

    op.alter_column('tariff_definitions', 'osd_operator',
                    type_=operator_enum,
                    postgresql_using='osd_operator::text::distributionoperatorenum')

def downgrade():
    op.alter_column('tariff_definitions', 'osd_operator',
                    type_=sa.String(),
                    postgresql_using='osd_operator::text')

    operator_enum = postgresql.ENUM(name='distributionoperatorenum')
    operator_enum.drop(op.get_bind(), checkfirst=True)
    # ### end Alembic commands ###
