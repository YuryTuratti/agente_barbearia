from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BarbershopResource
from app.domain.scheduling import validate_instance, validate_resource_key


async def list_booking_resources(session: AsyncSession, *, instance: str) -> list[BarbershopResource]:
    result = await session.execute(
        select(BarbershopResource).where(
            BarbershopResource.instance == validate_instance(instance),
            BarbershopResource.is_active.is_(True),
            BarbershopResource.booking_enabled.is_(True),
        ).order_by(BarbershopResource.sort_order, BarbershopResource.display_name)
    )
    return list(result.scalars().all())


async def get_booking_resource(session: AsyncSession, *, instance: str, resource_key: str) -> BarbershopResource | None:
    result = await session.execute(
        select(BarbershopResource).where(
            BarbershopResource.instance == validate_instance(instance),
            BarbershopResource.resource_key == validate_resource_key(resource_key),
            BarbershopResource.is_active.is_(True),
            BarbershopResource.booking_enabled.is_(True),
        )
    )
    return result.scalar_one_or_none()


BARBER_ALIASES = {
    "daniel": "daniel", "com daniel": "daniel", "com o daniel": "daniel",
    "lucas": "main", "com lucas": "main", "com o lucas": "main",
    "main": "main", "barbeiro principal": "main", "o principal": "main", "principal": "main",
    "outro barbeiro": "main", "sem ser o daniel": "main",
    "qualquer": None, "sem preferencia": None, "sem preferência": None,
}


def normalize_barber(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return BARBER_ALIASES.get(value.strip().casefold(), "__invalid__")


def resource_display_name(resource_key: str) -> str:
    return "Daniel" if resource_key == "daniel" else "Lucas"
