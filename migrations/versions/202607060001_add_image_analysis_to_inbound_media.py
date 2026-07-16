"""add image analysis to inbound media

Revision ID: 202607060001
Revises: 202607050003
Create Date: 2026-07-06 00:01:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "202607060001"
down_revision: Union[str, Sequence[str], None] = "202607050003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inbound_media",
        sa.Column("analysis_kind", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "inbound_media",
        sa.Column("analysis_data", sa.JSON(), nullable=True),
    )
    op.create_check_constraint(
        "ck_inbound_media_analysis_kind",
        "inbound_media",
        "analysis_kind IS NULL OR analysis_kind IN ('haircut_reference', 'payment_receipt', 'other', 'unclear')",
    )
    op.create_index(
        "ix_inbound_media_analysis_kind",
        "inbound_media",
        ["analysis_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_inbound_media_analysis_kind", table_name="inbound_media")
    op.drop_constraint(
        "ck_inbound_media_analysis_kind",
        "inbound_media",
        type_="check",
    )
    op.drop_column("inbound_media", "analysis_data")
    op.drop_column("inbound_media", "analysis_kind")
