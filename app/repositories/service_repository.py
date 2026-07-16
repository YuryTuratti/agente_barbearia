from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Service
from app.domain.barbershop_catalog import get_service_catalog_item
from app.exceptions.scheduling import InactiveServiceError, ServiceNotFoundError
from app.schemas.service import ServiceSummary


def _to_summary(service: Service) -> ServiceSummary:
    catalog_item = get_service_catalog_item(service.slug)
    return ServiceSummary(
        id=service.id,
        slug=service.slug,
        name=service.name,
        description=service.description,
        duration_minutes=service.duration_minutes,
        price_cents=service.price_cents,
        booking_enabled=True if catalog_item is None else catalog_item.booking_enabled,
        price_type="fixed" if catalog_item is None else catalog_item.price_type,
        requires_quote=False if catalog_item is None else catalog_item.requires_quote,
    )


async def list_active_services(session: AsyncSession) -> list[ServiceSummary]:
    result = await session.execute(
        select(Service).where(Service.active.is_(True)).order_by(Service.name.asc())
    )
    return [_to_summary(service) for service in result.scalars().all()]


async def get_service_by_slug(
    session: AsyncSession,
    *,
    slug: str,
) -> ServiceSummary | None:
    clean_slug = slug.strip()
    result = await session.execute(select(Service).where(Service.slug == clean_slug))
    service = result.scalar_one_or_none()
    return None if service is None else _to_summary(service)


async def get_active_services_by_ids(
    session: AsyncSession,
    *,
    service_ids: list[str],
) -> list[ServiceSummary]:
    if not service_ids:
        raise ServiceNotFoundError("At least one service is required.")
    if len(set(service_ids)) != len(service_ids):
        raise ServiceNotFoundError("Duplicate service IDs are not allowed.")

    result = await session.execute(select(Service).where(Service.id.in_(service_ids)))
    services_by_id = {service.id: service for service in result.scalars().all()}

    missing_ids = [service_id for service_id in service_ids if service_id not in services_by_id]
    if missing_ids:
        raise ServiceNotFoundError("Service was not found.")

    inactive_ids = []
    for service_id in service_ids:
        service = services_by_id[service_id]
        catalog_item = get_service_catalog_item(service.slug)
        if not service.active or (catalog_item is not None and not catalog_item.booking_enabled):
            inactive_ids.append(service_id)
    if inactive_ids:
        raise InactiveServiceError("Inactive services cannot be scheduled.")

    return [_to_summary(services_by_id[service_id]) for service_id in service_ids]
