"""create inbound messages table

Revision ID: 202607030001
Revises:
Create Date: 2026-07-03 00:01:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "202607030001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inbound_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("instance", sa.String(length=120), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("event", sa.String(length=120), nullable=True),
        sa.Column("remote_jid", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("message_type", sa.String(length=40), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("media_mimetype", sa.String(length=120), nullable=True),
        sa.Column("message_timestamp", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=40),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instance",
            "message_id",
            name="uq_inbound_messages_instance_message_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("inbound_messages")
