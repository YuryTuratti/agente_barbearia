from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.clock import Clock, SystemClock
from app.domain.scheduling import (
    combine_local_datetime,
    ensure_aware_utc,
    interval_overlaps,
    local_interval_fits_business_hours,
    get_timezone,
    to_utc,
    total_duration_minutes,
    validate_availability_date,
    validate_instance,
    validate_resource_key,
)
from app.repositories.appointment_repository import find_overlapping_appointments
from app.repositories.business_hours_repository import list_business_hours_for_weekday
from app.repositories.barbershop_resource_repository import get_booking_resource, list_booking_resources, resource_display_name
from app.repositories.service_repository import get_active_services_by_ids
from app.schemas.availability import AvailabilityResult, AvailableSlot


class AvailabilityService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        clock: Clock | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.clock = clock or SystemClock()

    async def list_available_slots(
        self,
        *,
        instance: str,
        local_date: date,
        service_ids: list[str],
        resource_key: str | None = None,
    ) -> AvailabilityResult:
        clean_instance = validate_instance(instance)
        clean_resource_key = validate_resource_key(resource_key) if resource_key else None
        now_utc = ensure_aware_utc(self.clock.now_utc())
        timezone_name = self.settings.barbershop_timezone
        validate_availability_date(
            local_date=local_date,
            now_utc=now_utc,
            max_days_ahead=self.settings.scheduling_max_days_ahead,
            timezone_name=timezone_name,
        )

        services = await get_active_services_by_ids(self.session, service_ids=service_ids)
        duration_minutes = total_duration_minutes(services)
        if clean_resource_key and clean_resource_key != self.settings.default_resource_key:
            if await get_booking_resource(self.session, instance=clean_instance, resource_key=clean_resource_key) is None:
                return AvailabilityResult(local_date=local_date, timezone=timezone_name, total_duration_minutes=duration_minutes, slots=[])
        resources = ([clean_resource_key] if clean_resource_key else [item.resource_key for item in await list_booking_resources(self.session, instance=clean_instance)])
        # Backwards compatibility for databases that have not been seeded with resources yet.
        if not resources:
            resources = [validate_resource_key(self.settings.default_resource_key)]
        slots: list[AvailableSlot] = []
        for current_resource_key in resources:
            slots.extend(await self._slots_for_resource(instance=clean_instance, resource_key=current_resource_key, local_date=local_date, duration_minutes=duration_minutes, now_utc=now_utc))
        slots.sort(key=lambda slot: (slot.start_time, slot.resource_key or ""))
        return AvailabilityResult(local_date=local_date, timezone=timezone_name, total_duration_minutes=duration_minutes, slots=slots)

    async def _slots_for_resource(self, *, instance: str, resource_key: str, local_date: date, duration_minutes: int, now_utc: datetime) -> list[AvailableSlot]:
        timezone_name = self.settings.barbershop_timezone
        intervals = await list_business_hours_for_weekday(
            self.session,
            instance=instance,
            resource_key=resource_key,
            weekday=local_date.weekday(),
        )
        if not intervals:
            return []

        zone = get_timezone(timezone_name)
        local_day_start = datetime.combine(local_date, time.min, tzinfo=zone)
        local_next_day = local_day_start + timedelta(days=1)
        overlaps = await find_overlapping_appointments(
            self.session,
            instance=instance,
            resource_key=resource_key,
            start_at=to_utc(local_day_start),
            end_at=to_utc(local_next_day),
        )

        slots: list[AvailableSlot] = []
        min_start_utc = now_utc + timedelta(
            minutes=self.settings.scheduling_min_notice_minutes
        )
        slot_step = timedelta(minutes=self.settings.scheduling_slot_interval_minutes)
        duration = timedelta(minutes=duration_minutes)

        for interval in intervals:
            cursor = combine_local_datetime(local_date, interval.opens_at, timezone_name)
            interval_close = combine_local_datetime(local_date, interval.closes_at, timezone_name)
            while cursor + duration <= interval_close:
                candidate_end = cursor + duration
                candidate_start_utc = to_utc(cursor)
                candidate_end_utc = to_utc(candidate_end)
                if (
                    candidate_start_utc >= min_start_utc
                    and local_interval_fits_business_hours(
                        local_start=cursor,
                        local_end=candidate_end,
                        intervals=intervals,
                    )
                    and not any(
                        interval_overlaps(
                            candidate_start_utc,
                            candidate_end_utc,
                            ensure_aware_utc(appointment.start_at),
                            ensure_aware_utc(appointment.end_at),
                        )
                        for appointment in overlaps
                    )
                ):
                    slots.append(
                        AvailableSlot(
                            start_time=cursor.timetz().replace(tzinfo=None),
                            end_time=candidate_end.timetz().replace(tzinfo=None),
                            resource_key=resource_key,
                            barber_name=resource_display_name(resource_key),
                        )
                    )
                cursor += slot_step

        return slots
