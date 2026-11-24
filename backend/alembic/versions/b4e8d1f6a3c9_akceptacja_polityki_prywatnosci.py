"""Akceptacja polityki prywatności (ZP-129).

Istniejące konta nie mają akceptacji, więc po wdrożeniu zostaną poproszone o nią przy najbliższym wejściu.

Revision ID: b4e8d1f6a3c9
Revises: b3e8f1a6c4d2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4e8d1f6a3c9"
down_revision: Union[str, Sequence[str], None] = "b3e8f1a6c4d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "privacy_consents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_privacy_consents_user_id", "privacy_consents", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_privacy_consents_user_id", table_name="privacy_consents")
    op.drop_table("privacy_consents")
