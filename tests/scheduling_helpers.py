from datetime import UTC, datetime, time

from app.core.config import Settings
from app.database.models import BusinessHours, Service


class FakeClock:
    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or datetime(2026, 7, 10, 12, 0, tzinfo=UTC)

    def now_utc(self) -> datetime:
        return self.now


def scheduling_settings(**overrides) -> Settings:
    values = {
        "scheduling_min_notice_minutes": 0,
        "scheduling_max_days_ahead": 30,
        "scheduling_slot_interval_minutes": 10,
        "scheduling_confirmation_code_length": 8,
        "scheduling_max_services_per_appointment": 5,
    }
    values.update(overrides)
    return Settings(**values)


async def add_service(
    session,
    *,
    slug: str = "corte",
    name: str = "Corte",
    duration_minutes: int = 30,
    price_cents: int = 3500,
    active: bool = True,
) -> Service:
    service = Service(
        slug=slug,
        name=name,
        duration_minutes=duration_minutes,
        price_cents=price_cents,
        active=active,
    )
    session.add(service)
    await session.commit()
    return service


async def add_hours(
    session,
    *,
    instance: str = "turatti",
    resource_key: str = "main",
    weekday: int = 4,
    opens_at: time = time(8, 0),
    closes_at: time = time(18, 0),
    active: bool = True,
) -> BusinessHours:
    hours = BusinessHours(
        instance=instance,
        resource_key=resource_key,
        weekday=weekday,
        opens_at=opens_at,
        closes_at=closes_at,
        active=active,
    )
    session.add(hours)
    await session.commit()
    return hours
