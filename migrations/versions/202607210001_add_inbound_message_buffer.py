"""add inbound message quiet-period deadline

Revision ID: 202607210001
Revises: 202607140001
"""
from alembic import op
import sqlalchemy as sa

revision = "202607210001"
down_revision = "202607140001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inbound_messages",
        sa.Column("process_after_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_inbound_messages_process_after_at",
        "inbound_messages",
        ["status", "process_after_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inbound_messages_process_after_at", table_name="inbound_messages")
    op.drop_column("inbound_messages", "process_after_at")
