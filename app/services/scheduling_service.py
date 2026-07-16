from datetime import date, time, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain.clock import Clock, SystemClock
from app.domain.scheduling import (
    combine_local_datetime,
    ensure_aware_utc,
    generate_confirmation_code,
    get_timezone,
    require_fits_business_hours,
    sanitize_cancellation_reason,
    to_utc,
    total_duration_minutes,
    total_price_cents,
    validate_booking_window,
    validate_instance,
    validate_phone,
    validate_resource_key,
)
from app.exceptions.scheduling import (
    AppointmentNotFoundError,
    AppointmentNotScheduledError,
    AppointmentOwnershipError,
    IdempotencyConflictError,
    ServiceNotFoundError,
    SlotUnavailableError,
)
from app.repositories.appointment_repository import (
    cancel_appointment as repo_cancel_appointment,
    find_overlapping_appointments,
    get_appointment_by_confirmation_code,
    get_appointment_by_id,
    get_appointment_by_idempotency_key,
    get_customer_for_appointment,
    insert_appointment,
    insert_appointment_services,
    list_appointment_service_snapshots,
    list_future_appointments_by_customer,
    reschedule_appointment as repo_reschedule_appointment,
)
from app.repositories.business_hours_repository import list_business_hours_for_weekday
from app.repositories.customer_repository import get_customer_by_phone, get_or_create_customer
from app.repositories.service_repository import get_active_services_by_ids
from app.schemas.appointment import AppointmentResult, AppointmentServiceSnapshot
from app.schemas.service import ServiceSummary

MAX_CONFIRMATION_CODE_ATTEMPTS = 10
POSTGRES_EXCLUSION_CONSTRAINT = "excl_appointments_scheduled_time_overlap"


class SchedulingService:
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

    async def create_appointment(
        self,
        *,
        instance: str,
        phone: str,
        customer_name: str | None,
        service_ids: list[str],
        local_date: date,
        local_start_time: time,
        resource_key: str | None = None,
        idempotency_key: str | None = None,
    ) -> AppointmentResult:
        clean_instance = validate_instance(instance)
        clean_phone = validate_phone(phone)
        clean_resource_key = validate_resource_key(
            resource_key or self.settings.default_resource_key
        )
        self._validate_service_count(service_ids)

        try:
            async with self.session.begin():
                existing = None
                if idempotency_key is not None:
                    existing = await get_appointment_by_idempotency_key(
                        self.session,
                        idempotency_key=idempotency_key,
                    )
                if existing is not None:
                    return await self._return_idempotent_replay(
                        existing=existing,
                        instance=clean_instance,
                        phone=clean_phone,
                        service_ids=service_ids,
                        local_date=local_date,
                        local_start_time=local_start_time,
                        resource_key=clean_resource_key,
                    )

                services = await get_active_services_by_ids(
                    self.session,
                    service_ids=service_ids,
                )
                duration_minutes = total_duration_minutes(services)
                price_cents = total_price_cents(services)
                local_start = combine_local_datetime(
                    local_date,
                    local_start_time,
                    self.settings.barbershop_timezone,
                )
                local_end = local_start + timedelta(minutes=duration_minutes)
                now_utc = ensure_aware_utc(self.clock.now_utc())
                validate_booking_window(
                    local_start=local_start,
                    now_utc=now_utc,
                    min_notice_minutes=self.settings.scheduling_min_notice_minutes,
                    max_days_ahead=self.settings.scheduling_max_days_ahead,
                    timezone_name=self.settings.barbershop_timezone,
                )
                intervals = await list_business_hours_for_weekday(
                    self.session,
                    instance=clean_instance,
                    resource_key=clean_resource_key,
                    weekday=local_date.weekday(),
                )
                require_fits_business_hours(
                    local_start=local_start,
                    local_end=local_end,
                    intervals=intervals,
                )
                start_at = to_utc(local_start)
                end_at = to_utc(local_end)
                await self._ensure_slot_available(
                    instance=clean_instance,
                    resource_key=clean_resource_key,
                    start_at=start_at,
                    end_at=end_at,
                )
                customer = await get_or_create_customer(
                    self.session,
                    instance=clean_instance,
                    phone=clean_phone,
                    name=customer_name,
                )
                confirmation_code = await self._new_confirmation_code()
                appointment = await insert_appointment(
                    self.session,
                    instance=clean_instance,
                    resource_key=clean_resource_key,
                    customer_id=customer.id,
                    confirmation_code=confirmation_code,
                    idempotency_key=idempotency_key,
                    start_at=start_at,
                    end_at=end_at,
                    total_duration_minutes=duration_minutes,
                    total_price_cents=price_cents,
                )
                await insert_appointment_services(
                    self.session,
                    appointment_id=appointment.id,
                    services=services,
                )
                snapshots = [
                    AppointmentServiceSnapshot(
                        service_id=service.id,
                        name=service.name,
                        duration_minutes=service.duration_minutes,
                        price_cents=service.price_cents,
                    )
                    for service in services
                ]
                return self._to_result(
                    appointment=appointment,
                    snapshots=snapshots,
                    created=True,
                    idempotent_replay=False,
                )
        except IntegrityError as error:
            await self.session.rollback()
            if _is_time_overlap_integrity_error(error):
                raise SlotUnavailableError("Requested slot is unavailable.") from error
            if idempotency_key is not None:
                existing = await get_appointment_by_idempotency_key(
                    self.session,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    return await self._return_idempotent_replay(
                        existing=existing,
                        instance=clean_instance,
                        phone=clean_phone,
                        service_ids=service_ids,
                        local_date=local_date,
                        local_start_time=local_start_time,
                        resource_key=clean_resource_key,
                    )
            raise

    async def list_future_appointments(
        self,
        *,
        instance: str,
        phone: str,
    ) -> list[AppointmentResult]:
        clean_instance = validate_instance(instance)
        clean_phone = validate_phone(phone)
        customer = await get_customer_by_phone(
            self.session,
            instance=clean_instance,
            phone=clean_phone,
        )
        if customer is None:
            return []
        appointments = await list_future_appointments_by_customer(
            self.session,
            customer_id=customer.id,
            now_utc=ensure_aware_utc(self.clock.now_utc()),
        )
        filtered = [appointment for appointment in appointments if appointment.instance == clean_instance]
        results = []
        for appointment in filtered:
            snapshots = await list_appointment_service_snapshots(
                self.session,
                appointment_id=appointment.id,
            )
            results.append(
                self._to_result(
                    appointment=appointment,
                    snapshots=snapshots,
                    created=False,
                    idempotent_replay=False,
                )
            )
        if self.session.in_transaction():
            await self.session.rollback()
        return results

    async def cancel_appointment(
        self,
        *,
        instance: str,
        phone: str,
        appointment_id: str,
        reason: str | None = None,
    ) -> AppointmentResult:
        clean_instance = validate_instance(instance)
        clean_phone = validate_phone(phone)
        async with self.session.begin():
            appointment = await self._get_owned_appointment(
                instance=clean_instance,
                phone=clean_phone,
                appointment_id=appointment_id,
            )
            if appointment.status != "scheduled":
                raise AppointmentNotScheduledError("Appointment is not scheduled.")
            await repo_cancel_appointment(
                self.session,
                appointment=appointment,
                cancelled_at=ensure_aware_utc(self.clock.now_utc()),
                reason=sanitize_cancellation_reason(reason),
            )
            snapshots = await list_appointment_service_snapshots(
                self.session,
                appointment_id=appointment.id,
            )
            return self._to_result(
                appointment=appointment,
                snapshots=snapshots,
                created=False,
                idempotent_replay=False,
            )

    async def reschedule_appointment(
        self,
        *,
        instance: str,
        phone: str,
        appointment_id: str,
        new_local_date: date,
        new_local_start_time: time,
        resource_key: str | None = None,
    ) -> AppointmentResult:
        clean_instance = validate_instance(instance)
        clean_phone = validate_phone(phone)
        try:
            async with self.session.begin():
                appointment = await self._get_owned_appointment(
                    instance=clean_instance,
                    phone=clean_phone,
                    appointment_id=appointment_id,
                )
                if appointment.status != "scheduled":
                    raise AppointmentNotScheduledError("Appointment is not scheduled.")
                target_resource_key = validate_resource_key(resource_key or appointment.resource_key)

                local_start = combine_local_datetime(
                    new_local_date,
                    new_local_start_time,
                    self.settings.barbershop_timezone,
                )
                local_end = local_start + timedelta(
                    minutes=appointment.total_duration_minutes
                )
                now_utc = ensure_aware_utc(self.clock.now_utc())
                validate_booking_window(
                    local_start=local_start,
                    now_utc=now_utc,
                    min_notice_minutes=self.settings.scheduling_min_notice_minutes,
                    max_days_ahead=self.settings.scheduling_max_days_ahead,
                    timezone_name=self.settings.barbershop_timezone,
                )
                intervals = await list_business_hours_for_weekday(
                    self.session,
                    instance=clean_instance,
                    resource_key=target_resource_key,
                    weekday=new_local_date.weekday(),
                )
                require_fits_business_hours(
                    local_start=local_start,
                    local_end=local_end,
                    intervals=intervals,
                )
                start_at = to_utc(local_start)
                end_at = to_utc(local_end)
                await self._ensure_slot_available(
                    instance=clean_instance,
                    resource_key=target_resource_key,
                    start_at=start_at,
                    end_at=end_at,
                    exclude_appointment_id=appointment.id,
                )
                appointment.resource_key = target_resource_key
                await repo_reschedule_appointment(
                    self.session,
                    appointment=appointment,
                    start_at=start_at,
                    end_at=end_at,
                    updated_at=now_utc,
                )
                snapshots = await list_appointment_service_snapshots(
                    self.session,
                    appointment_id=appointment.id,
                )
                return self._to_result(
                    appointment=appointment,
                    snapshots=snapshots,
                    created=False,
                    idempotent_replay=False,
                )
        except IntegrityError as error:
            await self.session.rollback()
            if _is_time_overlap_integrity_error(error):
                raise SlotUnavailableError("Requested slot is unavailable.") from error
            raise

    def _validate_service_count(self, service_ids: list[str]) -> None:
        if not service_ids:
            raise ServiceNotFoundError("At least one service is required.")
        if len(service_ids) > self.settings.scheduling_max_services_per_appointment:
            raise ServiceNotFoundError("Too many services were requested.")
        if len(set(service_ids)) != len(service_ids):
            raise ServiceNotFoundError("Duplicate service IDs are not allowed.")

    async def _ensure_slot_available(
        self,
        *,
        instance: str,
        resource_key: str,
        start_at,
        end_at,
        exclude_appointment_id: str | None = None,
    ) -> None:
        overlaps = await find_overlapping_appointments(
            self.session,
            instance=instance,
            resource_key=resource_key,
            start_at=start_at,
            end_at=end_at,
            exclude_appointment_id=exclude_appointment_id,
        )
        if overlaps:
            raise SlotUnavailableError("Requested slot is unavailable.")

    async def _new_confirmation_code(self) -> str:
        for _ in range(MAX_CONFIRMATION_CODE_ATTEMPTS):
            code = generate_confirmation_code(
                self.settings.scheduling_confirmation_code_length
            )
            existing = await get_appointment_by_confirmation_code(
                self.session,
                confirmation_code=code,
            )
            if existing is None:
                return code
        raise SlotUnavailableError("Could not generate a confirmation code.")

    async def _get_owned_appointment(
        self,
        *,
        instance: str,
        phone: str,
        appointment_id: str,
    ):
        appointment = await get_appointment_by_id(
            self.session,
            appointment_id=appointment_id,
        )
        if appointment is None or appointment.instance != instance:
            raise AppointmentNotFoundError("Appointment was not found.")
        customer = await get_customer_for_appointment(self.session, appointment=appointment)
        if customer is None or customer.phone != phone or customer.instance != instance:
            raise AppointmentOwnershipError("Appointment was not found.")
        return appointment

    async def _return_idempotent_replay(
        self,
        *,
        existing,
        instance: str,
        phone: str,
        service_ids: list[str],
        local_date: date,
        local_start_time: time,
        resource_key: str,
    ) -> AppointmentResult:
        customer = await get_customer_for_appointment(self.session, appointment=existing)
        snapshots = await list_appointment_service_snapshots(
            self.session,
            appointment_id=existing.id,
        )
        local_start = combine_local_datetime(
            local_date,
            local_start_time,
            self.settings.barbershop_timezone,
        )
        requested_service_ids = list(service_ids)
        existing_service_ids = [snapshot.service_id for snapshot in snapshots]
        if (
            customer is None
            or existing.instance != instance
            or existing.resource_key != resource_key
            or customer.phone != phone
            or to_utc(local_start) != ensure_aware_utc(existing.start_at)
            or requested_service_ids != existing_service_ids
        ):
            raise IdempotencyConflictError("Idempotency key was used for a different operation.")
        return self._to_result(
            appointment=existing,
            snapshots=snapshots,
            created=False,
            idempotent_replay=True,
        )

    def _to_result(
        self,
        *,
        appointment,
        snapshots: list[AppointmentServiceSnapshot],
        created: bool,
        idempotent_replay: bool,
    ) -> AppointmentResult:
        zone = get_timezone(self.settings.barbershop_timezone)
        local_start = ensure_aware_utc(appointment.start_at).astimezone(zone)
        local_end = ensure_aware_utc(appointment.end_at).astimezone(zone)
        return AppointmentResult(
            id=appointment.id,
            resource_key=appointment.resource_key,
            barber_name="Daniel" if appointment.resource_key == "daniel" else "Lucas",
            confirmation_code=appointment.confirmation_code,
            status=appointment.status,
            local_date=local_start.date(),
            local_start_time=local_start.timetz().replace(tzinfo=None),
            local_end_time=local_end.timetz().replace(tzinfo=None),
            timezone=self.settings.barbershop_timezone,
            services=snapshots,
            total_duration_minutes=appointment.total_duration_minutes,
            total_price_cents=appointment.total_price_cents,
            created=created,
            idempotent_replay=idempotent_replay,
        )


def _is_time_overlap_integrity_error(error: IntegrityError) -> bool:
    error_text = str(error)
    if POSTGRES_EXCLUSION_CONSTRAINT in error_text:
        return True
    current_error: BaseException | None = error
    while current_error is not None:
        constraint_name = getattr(current_error, "constraint_name", None)
        sqlstate = getattr(current_error, "sqlstate", None) or getattr(
            current_error,
            "pgcode",
            None,
        )
        if constraint_name == POSTGRES_EXCLUSION_CONSTRAINT or sqlstate == "23P01":
            return True
        current_error = current_error.__cause__
    return False
