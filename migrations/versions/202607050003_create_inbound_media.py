"""create inbound media

Revision ID: 202607050003
Revises: 202607050002
Create Date: 2026-07-05 00:03:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "202607050003"
down_revision: Union[str, Sequence[str], None] = "202607050002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inbound_media",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("inbound_message_id", sa.String(length=36), nullable=False),
        sa.Column("media_type", sa.String(length=40), nullable=False),
        sa.Column("mimetype", sa.String(length=120), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=40), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=40), server_default="unknown", nullable=False),
        sa.Column("media_locator", sa.JSON(), nullable=False),
        sa.Column("inline_base64", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('audio', 'image', 'video', 'document', 'sticker')",
            name="ck_inbound_media_media_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'unsupported')",
            name="ck_inbound_media_status",
        ),
        sa.CheckConstraint(
            "source IN ('inline_base64', 'evolution_api', 'unknown')",
            name="ck_inbound_media_source",
        ),
        sa.CheckConstraint(
            "file_size_bytes IS NULL OR file_size_bytes >= 0",
            name="ck_inbound_media_file_size_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["inbound_message_id"],
            ["inbound_messages.id"],
            name="fk_inbound_media_inbound_message_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inbound_message_id", name="uq_inbound_media_inbound_message_id"),
    )
    op.create_index(
        "ix_inbound_media_status_next_attempt_at",
        "inbound_media",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inbound_media_status_next_attempt_at", table_name="inbound_media")
    op.drop_table("inbound_media")
