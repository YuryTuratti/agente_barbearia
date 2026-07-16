"""create outbound messages table

Revision ID: 202607040001
Revises: 202607030002
Create Date: 2026-07-04 00:01:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "202607040001"
down_revision: Union[str, Sequence[str], None] = "202607030002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("inbound_message_id", sa.String(length=36), nullable=True),
        sa.Column("deduplication_key", sa.String(length=255), nullable=False),
        sa.Column("instance", sa.String(length=120), nullable=False),
        sa.Column("recipient", sa.String(length=32), nullable=False),
        sa.Column("message_type", sa.String(length=40), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=40),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("external_message_id", sa.String(length=255), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["inbound_message_id"],
            ["inbound_messages.id"],
            name="fk_outbound_messages_inbound_message_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "deduplication_key",
            name="uq_outbound_messages_deduplication_key",
        ),
    )
    op.create_index(
        "ix_outbound_messages_deduplication_key",
        "outbound_messages",
        ["deduplication_key"],
    )
    op.create_index(
        "ix_outbound_messages_status_next_attempt_at",
        "outbound_messages",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbound_messages_status_next_attempt_at",
        table_name="outbound_messages",
    )
    op.drop_index(
        "ix_outbound_messages_deduplication_key",
        table_name="outbound_messages",
    )
    op.drop_table("outbound_messages")
