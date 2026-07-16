from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BusinessHours
from app.domain.scheduling import validate_instance, validate_resource_key
from app.exceptions.scheduling import InvalidAppointmentTimeError
from app.schemas.business_hours import BusinessHoursInterval


async def list_business_hours_for_weekday(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str,
    weekday: int,
) -> list[BusinessHoursInterval]:
    if weekday < 0 or weekday > 6:
        raise InvalidAppointmentTimeError("Weekday must be between 0 and 6.")

    result = await session.execute(
        select(BusinessHours)
        .where(
            BusinessHours.instance == validate_instance(instance),
            BusinessHours.resource_key == validate_resource_key(resource_key),
            BusinessHours.weekday == weekday,
            BusinessHours.active.is_(True),
        )
        .order_by(BusinessHours.opens_at.asc())
    )
    return [
        BusinessHoursInterval(opens_at=interval.opens_at, closes_at=interval.closes_at)
        for interval in result.scalars().all()
    ]
