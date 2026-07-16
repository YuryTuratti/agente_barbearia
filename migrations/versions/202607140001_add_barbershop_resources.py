"""add barbershop resources

Revision ID: 202607140001
Revises: 202607060001
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "202607140001"
down_revision: Union[str, Sequence[str], None] = "202607060001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "barbershop_resources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("instance", sa.String(120), nullable=False),
        sa.Column("resource_key", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("booking_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instance", "resource_key", name="uq_barbershop_resources_instance_key"),
    )
    op.create_index("ix_barbershop_resources_instance_booking", "barbershop_resources", ["instance", "is_active", "booking_enabled"])


def downgrade() -> None:
    op.drop_index("ix_barbershop_resources_instance_booking", table_name="barbershop_resources")
    op.drop_table("barbershop_resources")
