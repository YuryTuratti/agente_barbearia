from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Appointment, AppointmentService, Customer
from app.domain.scheduling import ensure_aware_utc, interval_overlaps
from app.schemas.appointment import AppointmentServiceSnapshot
from app.schemas.service import ServiceSummary


async def find_overlapping_appointments(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
    exclude_appointment_id: str | None = None,
) -> list[Appointment]:
    statement = select(Appointment).where(
        Appointment.instance == instance,
        Appointment.resource_key == resource_key,
        Appointment.status == "scheduled",
        Appointment.start_at < end_at,
        Appointment.end_at > start_at,
    )
    if exclude_appointment_id is not None:
        statement = statement.where(Appointment.id != exclude_appointment_id)
    result = await session.execute(statement.order_by(Appointment.start_at.asc()))
    appointments = list(result.scalars().all())
    return [
        appointment
        for appointment in appointments
        if interval_overlaps(
            ensure_aware_utc(appointment.start_at),
            ensure_aware_utc(appointment.end_at),
            ensure_aware_utc(start_at),
            ensure_aware_utc(end_at),
        )
    ]


async def get_appointment_by_id(
    session: AsyncSession,
    *,
    appointment_id: str,
) -> Appointment | None:
    result = await session.execute(select(Appointment).where(Appointment.id == appointment_id))
    return result.scalar_one_or_none()


async def get_appointment_by_confirmation_code(
    session: AsyncSession,
    *,
    confirmation_code: str,
) -> Appointment | None:
    result = await session.execute(
        select(Appointment).where(Appointment.confirmation_code == confirmation_code)
    )
    return result.scalar_one_or_none()


async def get_appointment_by_idempotency_key(
    session: AsyncSession,
    *,
    idempotency_key: str,
) -> Appointment | None:
    result = await session.execute(
        select(Appointment).where(Appointment.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


async def list_future_appointments_by_customer(
    session: AsyncSession,
    *,
    customer_id: str,
    now_utc: datetime,
) -> list[Appointment]:
    result = await session.execute(
        select(Appointment)
        .where(
            Appointment.customer_id == customer_id,
            Appointment.status == "scheduled",
            Appointment.start_at >= now_utc,
        )
        .order_by(Appointment.start_at.asc())
    )
    return list(result.scalars().all())


async def insert_appointment(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    customer_id: str,
    confirmation_code: str,
    idempotency_key: str | None,
    start_at: datetime,
    end_at: datetime,
    total_duration_minutes: int,
    total_price_cents: int,
) -> Appointment:
    appointment = Appointment(
        instance=instance,
        resource_key=resource_key,
        customer_id=customer_id,
        confirmation_code=confirmation_code,
        idempotency_key=idempotency_key,
        status="scheduled",
        start_at=start_at,
        end_at=end_at,
        total_duration_minutes=total_duration_minutes,
        total_price_cents=total_price_cents,
    )
    session.add(appointment)
    await session.flush()
    return appointment


async def insert_appointment_services(
    session: AsyncSession,
    *,
    appointment_id: str,
    services: list[ServiceSummary],
) -> None:
    for position, service in enumerate(services):
        session.add(
            AppointmentService(
                appointment_id=appointment_id,
                service_id=service.id,
                position=position,
                service_name_snapshot=service.name,
                duration_minutes_snapshot=service.duration_minutes,
                price_cents_snapshot=service.price_cents,
            )
        )
    await session.flush()


async def list_appointment_service_snapshots(
    session: AsyncSession,
    *,
    appointment_id: str,
) -> list[AppointmentServiceSnapshot]:
    result = await session.execute(
        select(AppointmentService)
        .where(AppointmentService.appointment_id == appointment_id)
        .order_by(AppointmentService.position.asc())
    )
    return [
        AppointmentServiceSnapshot(
            service_id=record.service_id,
            name=record.service_name_snapshot,
            duration_minutes=record.duration_minutes_snapshot,
            price_cents=record.price_cents_snapshot,
        )
        for record in result.scalars().all()
    ]


async def get_customer_for_appointment(
    session: AsyncSession,
    *,
    appointment: Appointment,
) -> Customer | None:
    result = await session.execute(select(Customer).where(Customer.id == appointment.customer_id))
    return result.scalar_one_or_none()


async def cancel_appointment(
    session: AsyncSession,
    *,
    appointment: Appointment,
    cancelled_at: datetime,
    reason: str | None,
) -> None:
    appointment.status = "cancelled"
    appointment.cancelled_at = cancelled_at
    appointment.cancellation_reason = reason
    appointment.updated_at = cancelled_at
    await session.flush()


async def reschedule_appointment(
    session: AsyncSession,
    *,
    appointment: Appointment,
    start_at: datetime,
    end_at: datetime,
    updated_at: datetime,
) -> None:
    appointment.start_at = start_at
    appointment.end_at = end_at
    appointment.updated_at = updated_at
    await session.flush()
