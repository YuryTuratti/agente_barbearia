"""create Carlos conversation states

Revision ID: 202607230001
Revises: 202607210001
"""

from alembic import op
import sqlalchemy as sa

revision = "202607230001"
down_revision = "202607210001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "carlos_conversation_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("instance", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instance", "phone", name="uq_carlos_state_instance_phone"),
    )


def downgrade() -> None:
    op.drop_table("carlos_conversation_states")
