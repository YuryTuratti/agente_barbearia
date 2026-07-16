"""create scheduling domain

Revision ID: 202607050001
Revises: 202607040001
Create Date: 2026-07-05 00:01:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "202607050001"
down_revision: Union[str, Sequence[str], None] = "202607040001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect_name = op.get_context().dialect.name
    if dialect_name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "customers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("instance", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instance", "phone", name="uq_customers_instance_phone"),
    )
    op.create_index("ix_customers_instance_phone", "customers", ["instance", "phone"])

    op.create_table(
        "services",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("duration_minutes > 0", name="ck_services_duration_positive"),
        sa.CheckConstraint("price_cents >= 0", name="ck_services_price_non_negative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_services_active", "services", ["active"])

    op.create_table(
        "business_hours",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("instance", sa.String(length=120), nullable=False),
        sa.Column("resource_key", sa.String(length=80), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("opens_at", sa.Time(), nullable=False),
        sa.Column("closes_at", sa.Time(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_business_hours_weekday"),
        sa.CheckConstraint("opens_at < closes_at", name="ck_business_hours_open_before_close"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instance",
            "resource_key",
            "weekday",
            "opens_at",
            "closes_at",
            name="uq_business_hours_exact_interval",
        ),
    )
    op.create_index(
        "ix_business_hours_instance_resource_weekday",
        "business_hours",
        ["instance", "resource_key", "weekday"],
    )

    op.create_table(
        "appointments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("instance", sa.String(length=120), nullable=False),
        sa.Column("resource_key", sa.String(length=80), server_default="main", nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("confirmation_code", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=40), server_default="scheduled", nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("total_price_cents", sa.Integer(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('scheduled', 'cancelled', 'completed', 'no_show')",
            name="ck_appointments_status",
        ),
        sa.CheckConstraint("start_at < end_at", name="ck_appointments_start_before_end"),
        sa.CheckConstraint("total_duration_minutes > 0", name="ck_appointments_total_duration_positive"),
        sa.CheckConstraint("total_price_cents >= 0", name="ck_appointments_total_price_non_negative"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_appointments_customer_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("confirmation_code", name="uq_appointments_confirmation_code"),
        sa.UniqueConstraint("idempotency_key", name="uq_appointments_idempotency_key"),
    )
    op.create_index("ix_appointments_idempotency_key", "appointments", ["idempotency_key"])
    op.create_index("ix_appointments_instance_resource_start", "appointments", ["instance", "resource_key", "start_at"])
    op.create_index("ix_appointments_customer_start", "appointments", ["customer_id", "start_at"])
    op.create_index("ix_appointments_status_start", "appointments", ["status", "start_at"])
    if dialect_name == "postgresql":
        op.execute(
            """
            ALTER TABLE appointments
            ADD CONSTRAINT excl_appointments_scheduled_time_overlap
            EXCLUDE USING gist (
                instance WITH =,
                resource_key WITH =,
                tstzrange(start_at, end_at, '[)') WITH &&
            )
            WHERE (status = 'scheduled')
            """
        )

    op.create_table(
        "appointment_services",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("appointment_id", sa.String(length=36), nullable=False),
        sa.Column("service_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("service_name_snapshot", sa.String(length=120), nullable=False),
        sa.Column("duration_minutes_snapshot", sa.Integer(), nullable=False),
        sa.Column("price_cents_snapshot", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_appointment_services_position"),
        sa.CheckConstraint(
            "duration_minutes_snapshot > 0",
            name="ck_appointment_services_duration_positive",
        ),
        sa.CheckConstraint(
            "price_cents_snapshot >= 0",
            name="ck_appointment_services_price_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name="fk_appointment_services_appointment_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            name="fk_appointment_services_service_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "appointment_id",
            "service_id",
            name="uq_appointment_services_appointment_service",
        ),
        sa.UniqueConstraint(
            "appointment_id",
            "position",
            name="uq_appointment_services_appointment_position",
        ),
    )
    op.create_index(
        "ix_appointment_services_appointment_id",
        "appointment_services",
        ["appointment_id"],
    )


def downgrade() -> None:
    dialect_name = op.get_context().dialect.name
    op.drop_index("ix_appointment_services_appointment_id", table_name="appointment_services")
    op.drop_table("appointment_services")
    if dialect_name == "postgresql":
        op.drop_constraint(
            "excl_appointments_scheduled_time_overlap",
            "appointments",
            type_="exclude",
        )
    op.drop_index("ix_appointments_status_start", table_name="appointments")
    op.drop_index("ix_appointments_customer_start", table_name="appointments")
    op.drop_index("ix_appointments_instance_resource_start", table_name="appointments")
    op.drop_index("ix_appointments_idempotency_key", table_name="appointments")
    op.drop_table("appointments")
    op.drop_index("ix_business_hours_instance_resource_weekday", table_name="business_hours")
    op.drop_table("business_hours")
    op.drop_index("ix_services_active", table_name="services")
    op.drop_table("services")
    op.drop_index("ix_customers_instance_phone", table_name="customers")
    op.drop_table("customers")
