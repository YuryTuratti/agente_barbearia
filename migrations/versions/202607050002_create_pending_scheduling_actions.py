"""create pending scheduling actions

Revision ID: 202607050002
Revises: 202607050001
Create Date: 2026-07-05 00:02:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "202607050002"
down_revision: Union[str, Sequence[str], None] = "202607050001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_scheduling_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("instance", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("resource_key", sa.String(length=80), server_default="main", nullable=False),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="awaiting_confirmation", nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("preview", sa.JSON(), nullable=False),
        sa.Column("confirmation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("prepared_from_inbound_message_id", sa.String(length=36), nullable=False),
        sa.Column("confirmed_by_inbound_message_id", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_appointment_id", sa.String(length=36), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "action_type IN ('create', 'cancel', 'reschedule')",
            name="ck_pending_scheduling_actions_action_type",
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_confirmation', 'executing', 'completed', "
            "'rejected', 'expired', 'failed', 'superseded')",
            name="ck_pending_scheduling_actions_status",
        ),
        sa.ForeignKeyConstraint(
            ["prepared_from_inbound_message_id"],
            ["inbound_messages.id"],
            name="fk_pending_scheduling_actions_prepared_inbound",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_inbound_message_id"],
            ["inbound_messages.id"],
            name="fk_pending_scheduling_actions_confirmed_inbound",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["result_appointment_id"],
            ["appointments.id"],
            name="fk_pending_scheduling_actions_result_appointment",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pending_scheduling_actions_instance_phone_status",
        "pending_scheduling_actions",
        ["instance", "phone", "status"],
    )
    op.create_index(
        "ix_pending_scheduling_actions_expires_at",
        "pending_scheduling_actions",
        ["expires_at"],
    )
    op.create_index(
        "uq_pending_scheduling_actions_active",
        "pending_scheduling_actions",
        ["instance", "phone"],
        unique=True,
        postgresql_where=sa.text("status = 'awaiting_confirmation'"),
        sqlite_where=sa.text("status = 'awaiting_confirmation'"),
    )


def downgrade() -> None:
    op.drop_index("uq_pending_scheduling_actions_active", table_name="pending_scheduling_actions")
    op.drop_index("ix_pending_scheduling_actions_expires_at", table_name="pending_scheduling_actions")
    op.drop_index(
        "ix_pending_scheduling_actions_instance_phone_status",
        table_name="pending_scheduling_actions",
    )
    op.drop_table("pending_scheduling_actions")
