from datetime import UTC, datetime, time
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


def _generate_uuid() -> str:
    return str(uuid4())


class InboundMessage(Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (
        UniqueConstraint(
            "instance",
            "message_id",
            name="uq_inbound_messages_instance_message_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    instance: Mapped[str] = mapped_column(String(120), nullable=False)
    message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event: Mapped[str | None] = mapped_column(String(120), nullable=True)
    remote_jid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_type: Mapped[str] = mapped_column(String(40), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_mimetype: Mapped[str | None] = mapped_column(String(120), nullable=True)
    message_timestamp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="pending",
        server_default=sql_text("'pending'"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    process_after_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    __table_args__ = (
        UniqueConstraint(
            "deduplication_key",
            name="uq_outbound_messages_deduplication_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    inbound_message_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("inbound_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    deduplication_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    instance: Mapped[str] = mapped_column(String(120), nullable=False)
    recipient: Mapped[str] = mapped_column(String(32), nullable=False)
    message_type: Mapped[str] = mapped_column(String(40), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="pending",
        server_default=sql_text("'pending'"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("instance", "phone", name="uq_customers_instance_phone"),
        Index("ix_customers_instance_phone", "instance", "phone"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    instance: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_services_duration_positive"),
        CheckConstraint("price_cents >= 0", name="ck_services_price_non_negative"),
        Index("ix_services_active", "active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sql_text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class BusinessHours(Base):
    __tablename__ = "business_hours"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_business_hours_weekday"),
        CheckConstraint("opens_at < closes_at", name="ck_business_hours_open_before_close"),
        UniqueConstraint(
            "instance",
            "resource_key",
            "weekday",
            "opens_at",
            "closes_at",
            name="uq_business_hours_exact_interval",
        ),
        Index("ix_business_hours_instance_resource_weekday", "instance", "resource_key", "weekday"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    instance: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(80), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    opens_at: Mapped[time] = mapped_column(Time(), nullable=False)
    closes_at: Mapped[time] = mapped_column(Time(), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sql_text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class BarbershopResource(Base):
    __tablename__ = "barbershop_resources"
    __table_args__ = (
        UniqueConstraint("instance", "resource_key", name="uq_barbershop_resources_instance_key"),
        Index("ix_barbershop_resources_instance_booking", "instance", "is_active", "booking_enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    instance: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_text("true"))
    booking_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=sql_text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sql_text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), server_default=func.now())


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'cancelled', 'completed', 'no_show')",
            name="ck_appointments_status",
        ),
        CheckConstraint("start_at < end_at", name="ck_appointments_start_before_end"),
        CheckConstraint(
            "total_duration_minutes > 0",
            name="ck_appointments_total_duration_positive",
        ),
        CheckConstraint(
            "total_price_cents >= 0",
            name="ck_appointments_total_price_non_negative",
        ),
        UniqueConstraint("confirmation_code", name="uq_appointments_confirmation_code"),
        UniqueConstraint("idempotency_key", name="uq_appointments_idempotency_key"),
        Index("ix_appointments_idempotency_key", "idempotency_key"),
        Index("ix_appointments_instance_resource_start", "instance", "resource_key", "start_at"),
        Index("ix_appointments_customer_start", "customer_id", "start_at"),
        Index("ix_appointments_status_start", "status", "start_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    instance: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_key: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="main",
        server_default=sql_text("'main'"),
    )
    customer_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    confirmation_code: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="scheduled",
        server_default=sql_text("'scheduled'"),
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    total_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class AppointmentService(Base):
    __tablename__ = "appointment_services"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_appointment_services_position"),
        CheckConstraint(
            "duration_minutes_snapshot > 0",
            name="ck_appointment_services_duration_positive",
        ),
        CheckConstraint(
            "price_cents_snapshot >= 0",
            name="ck_appointment_services_price_non_negative",
        ),
        UniqueConstraint(
            "appointment_id",
            "service_id",
            name="uq_appointment_services_appointment_service",
        ),
        UniqueConstraint(
            "appointment_id",
            "position",
            name="uq_appointment_services_appointment_position",
        ),
        Index("ix_appointment_services_appointment_id", "appointment_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    appointment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("appointments.id", ondelete="CASCADE"),
        nullable=False,
    )
    service_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("services.id", ondelete="RESTRICT"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    service_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    duration_minutes_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class PendingSchedulingAction(Base):
    __tablename__ = "pending_scheduling_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('create', 'cancel', 'reschedule')",
            name="ck_pending_scheduling_actions_action_type",
        ),
        CheckConstraint(
            "status IN ('awaiting_confirmation', 'executing', 'completed', "
            "'rejected', 'expired', 'failed', 'superseded')",
            name="ck_pending_scheduling_actions_status",
        ),
        Index(
            "ix_pending_scheduling_actions_instance_phone_status",
            "instance",
            "phone",
            "status",
        ),
        Index("ix_pending_scheduling_actions_expires_at", "expires_at"),
        Index(
            "uq_pending_scheduling_actions_active",
            "instance",
            "phone",
            unique=True,
            sqlite_where=sql_text("status = 'awaiting_confirmation'"),
            postgresql_where=sql_text("status = 'awaiting_confirmation'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    instance: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_key: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="main",
        server_default=sql_text("'main'"),
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="awaiting_confirmation",
        server_default=sql_text("'awaiting_confirmation'"),
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    preview: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confirmation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    prepared_from_inbound_message_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("inbound_messages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    confirmed_by_inbound_message_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("inbound_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_appointment_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sql_text("0"),
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )


class InboundMedia(Base):
    __tablename__ = "inbound_media"
    __table_args__ = (
        CheckConstraint(
            "media_type IN ('audio', 'image', 'video', 'document', 'sticker')",
            name="ck_inbound_media_media_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'unsupported')",
            name="ck_inbound_media_status",
        ),
        CheckConstraint(
            "source IN ('inline_base64', 'evolution_api', 'unknown')",
            name="ck_inbound_media_source",
        ),
        CheckConstraint(
            "file_size_bytes IS NULL OR file_size_bytes >= 0",
            name="ck_inbound_media_file_size_non_negative",
        ),
        CheckConstraint(
            "analysis_kind IS NULL OR analysis_kind IN ('haircut_reference', 'payment_receipt', 'other', 'unclear')",
            name="ck_inbound_media_analysis_kind",
        ),
        UniqueConstraint("inbound_message_id", name="uq_inbound_media_inbound_message_id"),
        Index("ix_inbound_media_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_inbound_media_analysis_kind", "analysis_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    inbound_message_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("inbound_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_type: Mapped[str] = mapped_column(String(40), nullable=False)
    mimetype: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="pending",
        server_default=sql_text("'pending'"),
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sql_text("0"))
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown", server_default=sql_text("'unknown'"))
    media_locator: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    inline_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    analysis_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    analysis_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
