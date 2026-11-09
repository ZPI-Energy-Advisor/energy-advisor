"""Dom Smart Home: podłączony właściciel i stan rejestru wysłanego do huba (ZP-93).

Hub obsługuje jeden dom, więc home_connection ma jeden wiersz (id = 1), zakładany tutaj.

Revision ID: c3e8a1f5d7b2
Revises: a7c3e9f1d2b4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c3e8a1f5d7b2"
down_revision: Union[str, Sequence[str], None] = "a7c3e9f1d2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "home_connection",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registry_hash", sa.String(length=64), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_home_connection_single_row"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO home_connection (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("home_connection")
