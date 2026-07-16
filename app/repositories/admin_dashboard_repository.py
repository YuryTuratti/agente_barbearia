from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Appointment, AppointmentService, BusinessHours, Customer, Service

COUNTED_REVENUE_STATUSES = {"scheduled", "completed"}
RANKING_STATUSES = {"scheduled", "completed", "no_show"}


@dataclass(frozen=True)
class StatusCount:
    status: str
    count: int


@dataclass(frozen=True)
class ServiceRankingRow:
    service_id: str
    service_slug: str
    service_name: str
    count: int
    estimated_revenue_cents: int
    average_duration_minutes: float | None


@dataclass(frozen=True)
class AppointmentServiceRow:
    name: str
    duration_minutes: int
    price_cents: int


@dataclass(frozen=True)
class AppointmentRow:
    id: str
    confirmation_code: str
    status: str
    start_at: datetime
    end_at: datetime
    customer_name: str | None
    phone: str | None
    total_duration_minutes: int
    total_price_cents: int
    services: list[AppointmentServiceRow]
    cancellation_reason: str | None = None
    resource_key: str = "main"


@dataclass(frozen=True)
class BusinessHoursRow:
    weekday: int
    opens_at_minutes: int
    closes_at_minutes: int


@dataclass(frozen=True)
class ClientActivityRow:
    customer_id: str
    customer_name: str | None
    phone: str | None
    appointments: int
    last_appointment_at: datetime | None
    next_appointment_at: datetime | None


def _appointments_in_range(
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
) -> Select[tuple[Appointment]]:
    statement = select(Appointment).where(
        Appointment.instance == instance,
        Appointment.start_at >= start_at,
        Appointment.start_at < end_at,
    )
    return statement if resource_key == "all" else statement.where(Appointment.resource_key == resource_key)


async def count_appointments(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
) -> int:
    result = await session.execute(
        select(func.count(Appointment.id)).where(
            Appointment.instance == instance,
        or_(resource_key == "all", Appointment.resource_key == resource_key),
            Appointment.start_at >= start_at,
            Appointment.start_at < end_at,
        )
    )
    return int(result.scalar_one() or 0)


async def count_appointments_by_status(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
) -> list[StatusCount]:
    result = await session.execute(
        select(Appointment.status, func.count(Appointment.id))
        .where(
            Appointment.instance == instance,
            or_(resource_key == "all", Appointment.resource_key == resource_key),
            Appointment.start_at >= start_at,
            Appointment.start_at < end_at,
        )
        .group_by(Appointment.status)
    )
    return [StatusCount(status=str(status), count=int(count)) for status, count in result.all()]


async def sum_estimated_revenue(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
) -> int:
    result = await session.execute(
        select(func.coalesce(func.sum(Appointment.total_price_cents), 0)).where(
            Appointment.instance == instance,
            or_(resource_key == "all", Appointment.resource_key == resource_key),
            Appointment.start_at >= start_at,
            Appointment.start_at < end_at,
            Appointment.status.in_(COUNTED_REVENUE_STATUSES),
        )
    )
    return int(result.scalar_one() or 0)


async def count_unique_clients(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
) -> int:
    result = await session.execute(
        select(func.count(distinct(Appointment.customer_id))).where(
            Appointment.instance == instance,
            or_(resource_key == "all", Appointment.resource_key == resource_key),
            Appointment.start_at >= start_at,
            Appointment.start_at < end_at,
        )
    )
    return int(result.scalar_one() or 0)


async def sum_scheduled_minutes(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
) -> int:
    result = await session.execute(
        select(func.coalesce(func.sum(Appointment.total_duration_minutes), 0)).where(
            Appointment.instance == instance,
            or_(resource_key == "all", Appointment.resource_key == resource_key),
            Appointment.start_at >= start_at,
            Appointment.start_at < end_at,
            Appointment.status.in_(COUNTED_REVENUE_STATUSES),
        )
    )
    return int(result.scalar_one() or 0)


async def list_business_hours(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
) -> list[BusinessHoursRow]:
    result = await session.execute(
        select(BusinessHours)
        .where(
            BusinessHours.instance == instance,
            or_(resource_key == "all", BusinessHours.resource_key == resource_key),
            BusinessHours.active.is_(True),
        )
        .order_by(BusinessHours.weekday.asc(), BusinessHours.opens_at.asc())
    )
    rows = []
    for item in result.scalars().all():
        rows.append(
            BusinessHoursRow(
                weekday=item.weekday,
                opens_at_minutes=item.opens_at.hour * 60 + item.opens_at.minute,
                closes_at_minutes=item.closes_at.hour * 60 + item.closes_at.minute,
            )
        )
    return rows


async def list_service_ranking(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
) -> list[ServiceRankingRow]:
    result = await session.execute(
        select(
            AppointmentService.service_id,
            func.coalesce(Service.slug, AppointmentService.service_id),
            AppointmentService.service_name_snapshot,
            func.count(AppointmentService.id),
            func.coalesce(func.sum(AppointmentService.price_cents_snapshot), 0),
            func.avg(AppointmentService.duration_minutes_snapshot),
        )
        .join(Appointment, Appointment.id == AppointmentService.appointment_id)
        .outerjoin(Service, Service.id == AppointmentService.service_id)
        .where(
            Appointment.instance == instance,
            or_(resource_key == "all", Appointment.resource_key == resource_key),
            Appointment.start_at >= start_at,
            Appointment.start_at < end_at,
            Appointment.status.in_(RANKING_STATUSES),
        )
        .group_by(
            AppointmentService.service_id,
            Service.slug,
            AppointmentService.service_name_snapshot,
            AppointmentService.price_cents_snapshot,
        )
    )
    return [
        ServiceRankingRow(
            service_id=str(service_id),
            service_slug=str(service_slug),
            service_name=str(service_name),
            count=int(count),
            estimated_revenue_cents=int(revenue or 0),
            average_duration_minutes=float(avg_duration) if avg_duration is not None else None,
        )
        for service_id, service_slug, service_name, count, revenue, avg_duration in result.all()
    ]


async def list_appointments_for_day(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
    status: str | None,
) -> list[AppointmentRow]:
    statement = (
        _appointments_in_range(
            instance=instance,
            resource_key=resource_key,
            start_at=start_at,
            end_at=end_at,
        )
        .join(Customer, Customer.id == Appointment.customer_id)
        .order_by(Appointment.start_at.asc())
        .with_only_columns(
            Appointment.id,
            Appointment.confirmation_code,
            Appointment.status,
            Appointment.start_at,
            Appointment.end_at,
            Customer.name,
            Customer.phone,
            Appointment.total_duration_minutes,
            Appointment.total_price_cents,
            Appointment.cancellation_reason,
            Appointment.resource_key,
        )
    )
    if status is not None:
        statement = statement.where(Appointment.status == status)
    result = await session.execute(statement)
    appointments = [
        AppointmentRow(
            id=str(row.id),
            confirmation_code=str(row.confirmation_code),
            status=str(row.status),
            start_at=row.start_at,
            end_at=row.end_at,
            customer_name=row.name,
            phone=row.phone,
            total_duration_minutes=int(row.total_duration_minutes),
            total_price_cents=int(row.total_price_cents),
            services=[],
            cancellation_reason=row.cancellation_reason,
            resource_key=str(row.resource_key),
        )
        for row in result.all()
    ]
    if not appointments:
        return []

    service_result = await session.execute(
        select(
            AppointmentService.appointment_id,
            AppointmentService.service_name_snapshot,
            AppointmentService.duration_minutes_snapshot,
            AppointmentService.price_cents_snapshot,
        )
        .where(AppointmentService.appointment_id.in_([item.id for item in appointments]))
        .order_by(AppointmentService.appointment_id.asc(), AppointmentService.position.asc())
    )
    services_by_appointment: dict[str, list[AppointmentServiceRow]] = {}
    for appointment_id, name, duration, price in service_result.all():
        services_by_appointment.setdefault(str(appointment_id), []).append(
            AppointmentServiceRow(
                name=str(name),
                duration_minutes=int(duration),
                price_cents=int(price),
            )
        )

    return [
        AppointmentRow(
            id=item.id,
            confirmation_code=item.confirmation_code,
            status=item.status,
            start_at=item.start_at,
            end_at=item.end_at,
            customer_name=item.customer_name,
            phone=item.phone,
            total_duration_minutes=item.total_duration_minutes,
            total_price_cents=item.total_price_cents,
            services=services_by_appointment.get(item.id, []),
            cancellation_reason=item.cancellation_reason,
            resource_key=item.resource_key,
        )
        for item in appointments
    ]


async def list_appointments_for_range(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
    statuses: set[str] | None = None,
) -> list[AppointmentRow]:
    statement = (
        _appointments_in_range(
            instance=instance,
            resource_key=resource_key,
            start_at=start_at,
            end_at=end_at,
        )
        .join(Customer, Customer.id == Appointment.customer_id)
        .order_by(Appointment.start_at.asc())
        .with_only_columns(
            Appointment.id,
            Appointment.confirmation_code,
            Appointment.status,
            Appointment.start_at,
            Appointment.end_at,
            Customer.name,
            Customer.phone,
            Appointment.total_duration_minutes,
            Appointment.total_price_cents,
            Appointment.cancellation_reason,
        )
    )
    if statuses is not None:
        statement = statement.where(Appointment.status.in_(statuses))
    result = await session.execute(statement)
    appointments = [
        AppointmentRow(
            id=str(row.id),
            confirmation_code=str(row.confirmation_code),
            status=str(row.status),
            start_at=row.start_at,
            end_at=row.end_at,
            customer_name=row.name,
            phone=row.phone,
            total_duration_minutes=int(row.total_duration_minutes),
            total_price_cents=int(row.total_price_cents),
            services=[],
            cancellation_reason=row.cancellation_reason,
        )
        for row in result.all()
    ]
    if not appointments:
        return []

    service_result = await session.execute(
        select(
            AppointmentService.appointment_id,
            AppointmentService.service_name_snapshot,
            AppointmentService.duration_minutes_snapshot,
            AppointmentService.price_cents_snapshot,
        )
        .where(AppointmentService.appointment_id.in_([item.id for item in appointments]))
        .order_by(AppointmentService.appointment_id.asc(), AppointmentService.position.asc())
    )
    services_by_appointment: dict[str, list[AppointmentServiceRow]] = {}
    for appointment_id, name, duration, price in service_result.all():
        services_by_appointment.setdefault(str(appointment_id), []).append(
            AppointmentServiceRow(
                name=str(name),
                duration_minutes=int(duration),
                price_cents=int(price),
            )
        )

    return [
        AppointmentRow(
            id=item.id,
            confirmation_code=item.confirmation_code,
            status=item.status,
            start_at=item.start_at,
            end_at=item.end_at,
            customer_name=item.customer_name,
            phone=item.phone,
            total_duration_minutes=item.total_duration_minutes,
            total_price_cents=item.total_price_cents,
            services=services_by_appointment.get(item.id, []),
            cancellation_reason=item.cancellation_reason,
        )
        for item in appointments
    ]


async def list_client_activity(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
    now_at: datetime,
    limit: int,
) -> list[ClientActivityRow]:
    result = await session.execute(
        select(
            Customer.id,
            Customer.name,
            Customer.phone,
            func.count(Appointment.id),
            func.max(Appointment.start_at),
        )
        .join(Appointment, Appointment.customer_id == Customer.id)
        .where(
            Appointment.instance == instance,
            or_(resource_key == "all", Appointment.resource_key == resource_key),
            Appointment.start_at >= start_at,
            Appointment.start_at < end_at,
        )
        .group_by(Customer.id, Customer.name, Customer.phone)
        .order_by(func.count(Appointment.id).desc(), func.max(Appointment.start_at).desc())
        .limit(limit)
    )
    rows = result.all()
    if not rows:
        return []

    next_result = await session.execute(
        select(Appointment.customer_id, func.min(Appointment.start_at))
        .where(
            Appointment.instance == instance,
            or_(resource_key == "all", Appointment.resource_key == resource_key),
            Appointment.status == "scheduled",
            Appointment.start_at >= now_at,
            Appointment.customer_id.in_([row[0] for row in rows]),
        )
        .group_by(Appointment.customer_id)
    )
    next_by_customer = {
        str(customer_id): appointment_at for customer_id, appointment_at in next_result.all()
    }

    return [
        ClientActivityRow(
            customer_id=str(row[0]),
            customer_name=row[1],
            phone=row[2],
            appointments=int(row[3]),
            last_appointment_at=row[4],
            next_appointment_at=next_by_customer.get(str(row[0])),
        )
        for row in rows
    ]


async def has_estimated_services(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    start_at: datetime,
    end_at: datetime,
    estimated_service_slugs: set[str],
) -> bool:
    if not estimated_service_slugs:
        return False
    result = await session.execute(
        select(func.count(AppointmentService.id))
        .join(Appointment, Appointment.id == AppointmentService.appointment_id)
        .join(Service, Service.id == AppointmentService.service_id)
        .where(
            Appointment.instance == instance,
            or_(resource_key == "all", Appointment.resource_key == resource_key),
            Appointment.start_at >= start_at,
            Appointment.start_at < end_at,
            Appointment.status.in_(COUNTED_REVENUE_STATUSES),
            Service.slug.in_(estimated_service_slugs),
        )
    )
    return int(result.scalar_one() or 0) > 0
