"""add worker fields to inbound messages

Revision ID: 202607030002
Revises: 202607030001
Create Date: 2026-07-03 00:02:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "202607030002"
down_revision: Union[str, Sequence[str], None] = "202607030001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inbound_messages",
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "inbound_messages",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "inbound_messages",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("inbound_messages", "next_attempt_at")
    op.drop_column("inbound_messages", "processed_at")
    op.drop_column("inbound_messages", "locked_at")
