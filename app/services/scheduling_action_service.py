from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.database.models import InboundMessage
from app.domain.barbershop_catalog import is_total_price_estimate
from app.domain.clock import Clock, SystemClock
from app.domain.confirmation import is_explicit_confirmation, is_explicit_rejection
from app.domain.scheduling import (
    add_minutes_to_time,
    combine_local_datetime,
    ensure_aware_utc,
    get_timezone,
    sanitize_cancellation_reason,
    to_utc,
    total_duration_minutes,
    total_price_cents,
    validate_instance,
    validate_phone,
    validate_resource_key,
)
from app.domain.scheduling_actions import confirmation_fingerprint
from app.exceptions.scheduling import (
    AppointmentNotFoundError,
    AppointmentNotScheduledError,
    AppointmentOwnershipError,
    BookingNoticeError,
    BookingTooFarAheadError,
    BusinessClosedError,
    InactiveServiceError,
    InvalidAppointmentTimeError,
    ServiceNotFoundError,
    SlotUnavailableError,
)
from app.exceptions.scheduling_actions import (
    ActionNotConfirmableError,
    ConfirmationDataChangedError,
    ConfirmationNotExplicitError,
    ConfirmationRequiresNewMessageError,
    NoPendingActionError,
    PendingActionExpiredError,
    RejectionNotExplicitError,
)
from app.repositories.appointment_repository import (
    find_overlapping_appointments,
    get_appointment_by_id,
    get_customer_for_appointment,
    list_appointment_service_snapshots,
)
from app.repositories.business_hours_repository import list_business_hours_for_weekday
from app.repositories.barbershop_resource_repository import get_booking_resource, resource_display_name
from app.repositories.pending_scheduling_action_repository import (
    create_pending_action,
    expire_pending_actions,
    get_pending_action_for_update,
    mark_pending_action_completed,
    mark_pending_action_failed,
    mark_pending_action_rejected,
    supersede_active_pending_action,
)
from app.repositories.service_repository import get_active_services_by_ids
from app.schemas.appointment import AppointmentResult
from app.schemas.scheduling_action import (
    CancelAppointmentActionPayload,
    CreateAppointmentActionPayload,
    PendingActionSummary,
    RescheduleAppointmentActionPayload,
    SchedulingActionExecutionResult,
)
from app.services.scheduling_service import SchedulingService
from app.services.message_text import get_confirmation_candidate_text


class SchedulingActionService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock or SystemClock()

    async def prepare_create(
        self,
        *,
        message: InboundMessage,
        payload: CreateAppointmentActionPayload,
    ) -> PendingActionSummary:
        instance, phone, _ = self._identity(message)
        resource_key = validate_resource_key(payload.resource_key)
        now = ensure_aware_utc(self._clock.now_utc())
        if len(payload.service_ids) > self._settings.scheduling_max_services_per_appointment:
            raise ServiceNotFoundError("Too many services.")
        async with self._session_factory() as session:
            if resource_key != self._settings.default_resource_key and await get_booking_resource(session, instance=instance, resource_key=resource_key) is None:
                raise ValueError("Barber unavailable")
            services = await get_active_services_by_ids(session, service_ids=payload.service_ids)
            duration = total_duration_minutes(services)
            local_start = combine_local_datetime(
                payload.local_date,
                payload.local_start_time,
                self._settings.barbershop_timezone,
            )
            local_end = local_start + timedelta(minutes=duration)
            await self._validate_slot(
                session,
                instance=instance,
                resource_key=resource_key,
                local_start=local_start,
                local_end=local_end,
            )
            preview = {
                "local_date": payload.local_date.isoformat(),
                "local_start_time": payload.local_start_time.strftime("%H:%M"),
                "local_end_time": local_end.strftime("%H:%M"),
                "timezone": self._settings.barbershop_timezone,
                "services": [
                    {
                        "service_id": service.id,
                        "name": service.name,
                        "duration_minutes": service.duration_minutes,
                        "price_cents": service.price_cents,
                    }
                    for service in services
                ],
                "total_duration_minutes": duration,
                "total_price_cents": total_price_cents(services),
                "total_price_display": _format_brl(total_price_cents(services)),
                "resource_key": resource_key,
                "barber": resource_display_name(resource_key),
            }
            if is_total_price_estimate([service.slug for service in services]):
                preview["total_price_is_estimate"] = True
            action = await self._store_action(
                session,
                message=message,
                instance=instance,
                phone=phone,
                resource_key=resource_key,
                now=now,
                action_type="create",
                payload={
                    "service_ids": payload.service_ids,
                    "local_date": payload.local_date.isoformat(),
                    "local_start_time": payload.local_start_time.strftime("%H:%M"),
                    "customer_name": payload.customer_name,
                    "resource_key": resource_key,
                },
                preview=preview,
            )
            await session.commit()
            return _summary(action.action_type, action.status, action.expires_at, preview)

    async def prepare_cancel(
        self,
        *,
        message: InboundMessage,
        payload: CancelAppointmentActionPayload,
    ) -> PendingActionSummary:
        instance, phone, resource_key = self._identity(message)
        now = ensure_aware_utc(self._clock.now_utc())
        async with self._session_factory() as session:
            appointment = await self._owned_appointment(session, instance, phone, payload.appointment_id)
            if appointment.status != "scheduled":
                raise AppointmentNotScheduledError("Appointment is not scheduled.")
            snapshots = await list_appointment_service_snapshots(session, appointment_id=appointment.id)
            preview = self._appointment_preview(appointment, snapshots)
            action = await self._store_action(
                session,
                message=message,
                instance=instance,
                phone=phone,
                resource_key=resource_key,
                now=now,
                action_type="cancel",
                payload={
                    "appointment_id": payload.appointment_id,
                    "reason": sanitize_cancellation_reason(payload.reason),
                },
                preview=preview,
            )
            await session.commit()
            return _summary(action.action_type, action.status, action.expires_at, preview)

    async def prepare_reschedule(
        self,
        *,
        message: InboundMessage,
        payload: RescheduleAppointmentActionPayload,
    ) -> PendingActionSummary:
        instance, phone, resource_key = self._identity(message)
        now = ensure_aware_utc(self._clock.now_utc())
        async with self._session_factory() as session:
            appointment = await self._owned_appointment(session, instance, phone, payload.appointment_id)
            if appointment.status != "scheduled":
                raise AppointmentNotScheduledError("Appointment is not scheduled.")
            local_start = combine_local_datetime(
                payload.new_local_date,
                payload.new_local_start_time,
                self._settings.barbershop_timezone,
            )
            local_end = local_start + timedelta(minutes=appointment.total_duration_minutes)
            target_resource_key = payload.resource_key or appointment.resource_key
            if target_resource_key != self._settings.default_resource_key and await get_booking_resource(session, instance=instance, resource_key=target_resource_key) is None:
                raise ValueError("Barber unavailable")
            await self._validate_slot(
                session,
                instance=instance,
                resource_key=target_resource_key,
                local_start=local_start,
                local_end=local_end,
                exclude_appointment_id=appointment.id,
            )
            snapshots = await list_appointment_service_snapshots(session, appointment_id=appointment.id)
            preview = self._appointment_preview(appointment, snapshots)
            preview.update(
                {
                    "new_local_date": payload.new_local_date.isoformat(),
                    "new_local_start_time": payload.new_local_start_time.strftime("%H:%M"),
                    "new_local_end_time": local_end.strftime("%H:%M"),
                    "new_resource_key": target_resource_key,
                    "new_barber": resource_display_name(target_resource_key),
                }
            )
            action = await self._store_action(
                session,
                message=message,
                instance=instance,
                phone=phone,
                resource_key=target_resource_key,
                now=now,
                action_type="reschedule",
                payload={
                    "appointment_id": payload.appointment_id,
                    "new_local_date": payload.new_local_date.isoformat(),
                    "new_local_start_time": payload.new_local_start_time.strftime("%H:%M"),
                    "resource_key": target_resource_key,
                },
                preview=preview,
            )
            await session.commit()
            return _summary(action.action_type, action.status, action.expires_at, preview)

    async def confirm_pending_action(self, *, message: InboundMessage) -> SchedulingActionExecutionResult:
        instance, phone, _ = self._identity(message)
        now = ensure_aware_utc(self._clock.now_utc())
        async with self._session_factory() as session:
            await expire_pending_actions(session, now=now, instance=instance, phone=phone)
            action = await get_pending_action_for_update(session, instance=instance, phone=phone)
            if action is None:
                raise NoPendingActionError("No pending action.")
            if ensure_aware_utc(action.expires_at) <= now:
                raise PendingActionExpiredError("Pending action expired.")
            if action.prepared_from_inbound_message_id == message.id:
                raise ConfirmationRequiresNewMessageError("Confirmation requires a new message.")
            if not is_explicit_confirmation(get_confirmation_candidate_text(message) or ""):
                raise ConfirmationNotExplicitError("Confirmation is not explicit.")
            if action.status != "awaiting_confirmation":
                raise ActionNotConfirmableError("Action is not confirmable.")
            if confirmation_fingerprint(action.preview) != action.confirmation_fingerprint:
                await mark_pending_action_failed(
                    session,
                    action=action,
                    error_message="Confirmation data changed.",
                    now=now,
                    max_error_length=self._settings.scheduling_pending_action_error_max_length,
                )
                await session.commit()
                raise ConfirmationDataChangedError("Confirmation data changed.")
            action.status = "executing"
            action.attempts += 1
            await session.commit()

        try:
            result = await self._execute_action(action_id=action.id, action_type=action.action_type, payload=action.payload, message=message)
        except Exception:
            async with self._session_factory() as session:
                locked = await get_pending_action_for_update(session, instance=instance, phone=phone)
                if locked is not None and locked.id == action.id:
                    await mark_pending_action_failed(
                        session,
                        action=locked,
                        error_message="Action execution failed.",
                        now=now,
                        max_error_length=self._settings.scheduling_pending_action_error_max_length,
                    )
                    await session.commit()
            raise

        async with self._session_factory() as session:
            fresh = await session.get(type(action), action.id)
            if fresh is None:
                raise NoPendingActionError("No pending action.")
            await mark_pending_action_completed(
                session,
                action=fresh,
                confirmed_by_inbound_message_id=message.id,
                appointment_id=result.id,
                now=ensure_aware_utc(self._clock.now_utc()),
            )
            await session.commit()
        return SchedulingActionExecutionResult(
            action_type=action.action_type,
            status="completed",
            appointment_id=result.id,
            summary=_result_summary(result),
        )

    async def discard_pending_action(self, *, message: InboundMessage) -> PendingActionSummary:
        instance, phone, _ = self._identity(message)
        now = ensure_aware_utc(self._clock.now_utc())
        if not is_explicit_rejection(get_confirmation_candidate_text(message) or ""):
            raise RejectionNotExplicitError("Rejection is not explicit.")
        async with self._session_factory() as session:
            await expire_pending_actions(session, now=now, instance=instance, phone=phone)
            action = await get_pending_action_for_update(session, instance=instance, phone=phone)
            if action is None:
                raise NoPendingActionError("No pending action.")
            if ensure_aware_utc(action.expires_at) <= now:
                raise PendingActionExpiredError("Pending action expired.")
            await mark_pending_action_rejected(session, action=action, now=now)
            await session.commit()
            return _summary(action.action_type, action.status, action.expires_at, action.preview)

    async def _execute_action(
        self,
        *,
        action_id: str,
        action_type: str,
        payload: dict[str, Any],
        message: InboundMessage,
    ) -> AppointmentResult:
        async with self._session_factory() as session:
            scheduler = SchedulingService(session, settings=self._settings, clock=self._clock)
            if action_type == "create":
                parsed = CreateAppointmentActionPayload.model_validate(payload)
                return await scheduler.create_appointment(
                    instance=message.instance,
                    phone=message.phone or "",
                    customer_name=parsed.customer_name,
                    service_ids=parsed.service_ids,
                    local_date=parsed.local_date,
                    local_start_time=parsed.local_start_time,
                    idempotency_key=f"pending-action:{action_id}",
                    resource_key=parsed.resource_key,
                )
            if action_type == "cancel":
                parsed = CancelAppointmentActionPayload.model_validate(payload)
                return await scheduler.cancel_appointment(
                    instance=message.instance,
                    phone=message.phone or "",
                    appointment_id=parsed.appointment_id,
                    reason=parsed.reason,
                )
            parsed = RescheduleAppointmentActionPayload.model_validate(payload)
            return await scheduler.reschedule_appointment(
                instance=message.instance,
                phone=message.phone or "",
                appointment_id=parsed.appointment_id,
                new_local_date=parsed.new_local_date,
                new_local_start_time=parsed.new_local_start_time,
                resource_key=parsed.resource_key,
            )

    async def _store_action(self, session: AsyncSession, **kwargs: Any):
        await expire_pending_actions(
            session,
            now=kwargs["now"],
            instance=kwargs["instance"],
            phone=kwargs["phone"],
        )
        await supersede_active_pending_action(
            session,
            instance=kwargs["instance"],
            phone=kwargs["phone"],
            now=kwargs["now"],
        )
        expires_at = kwargs["now"] + timedelta(minutes=self._settings.scheduling_confirmation_ttl_minutes)
        return await create_pending_action(
            session,
            instance=kwargs["instance"],
            phone=kwargs["phone"],
            resource_key=kwargs["resource_key"],
            action_type=kwargs["action_type"],
            payload=kwargs["payload"],
            preview=kwargs["preview"],
            confirmation_fingerprint=confirmation_fingerprint(kwargs["preview"]),
            prepared_from_inbound_message_id=kwargs["message"].id,
            expires_at=expires_at,
        )

    async def _validate_slot(
        self,
        session: AsyncSession,
        *,
        instance: str,
        resource_key: str,
        local_start,
        local_end,
        exclude_appointment_id: str | None = None,
    ) -> None:
        now = ensure_aware_utc(self._clock.now_utc())
        # Reuse the public domain rules already enforced by SchedulingService.
        from app.domain.scheduling import require_fits_business_hours, validate_booking_window

        validate_booking_window(
            local_start=local_start,
            now_utc=now,
            min_notice_minutes=self._settings.scheduling_min_notice_minutes,
            max_days_ahead=self._settings.scheduling_max_days_ahead,
            timezone_name=self._settings.barbershop_timezone,
        )
        intervals = await list_business_hours_for_weekday(
            session,
            instance=instance,
            resource_key=resource_key,
            weekday=local_start.date().weekday(),
        )
        require_fits_business_hours(local_start=local_start, local_end=local_end, intervals=intervals)
        overlaps = await find_overlapping_appointments(
            session,
            instance=instance,
            resource_key=resource_key,
            start_at=to_utc(local_start),
            end_at=to_utc(local_end),
            exclude_appointment_id=exclude_appointment_id,
        )
        if overlaps:
            raise SlotUnavailableError("Requested slot is unavailable.")

    async def _owned_appointment(self, session: AsyncSession, instance: str, phone: str, appointment_id: str):
        appointment = await get_appointment_by_id(session, appointment_id=appointment_id)
        if appointment is None or appointment.instance != instance:
            raise AppointmentNotFoundError("Appointment not found.")
        customer = await get_customer_for_appointment(session, appointment=appointment)
        if customer is None or customer.phone != phone or customer.instance != instance:
            raise AppointmentOwnershipError("Appointment not found.")
        return appointment

    def _identity(self, message: InboundMessage) -> tuple[str, str, str]:
        return (
            validate_instance(message.instance),
            validate_phone(message.phone or ""),
            validate_resource_key(self._settings.default_resource_key),
        )

    def _appointment_preview(self, appointment, snapshots) -> dict[str, Any]:
        zone = get_timezone(self._settings.barbershop_timezone)
        local_start = ensure_aware_utc(appointment.start_at).astimezone(zone)
        local_end = ensure_aware_utc(appointment.end_at).astimezone(zone)
        return {
            "appointment_id": appointment.id,
            "confirmation_code": appointment.confirmation_code,
            "status": appointment.status,
            "local_date": local_start.date().isoformat(),
            "local_start_time": local_start.strftime("%H:%M"),
            "local_end_time": local_end.strftime("%H:%M"),
            "timezone": self._settings.barbershop_timezone,
            "services": [snapshot.model_dump() for snapshot in snapshots],
            "total_duration_minutes": appointment.total_duration_minutes,
            "total_price_cents": appointment.total_price_cents,
            "resource_key": appointment.resource_key,
            "barber": resource_display_name(appointment.resource_key),
        }


def _summary(action_type: str, status: str, expires_at, preview: dict[str, Any]) -> PendingActionSummary:
    return PendingActionSummary(
        action_type=action_type,
        status=status,
        confirmation_required=status == "awaiting_confirmation",
        expires_at=expires_at,
        summary=preview,
    )


def _result_summary(result: AppointmentResult) -> dict[str, Any]:
    summary = {
        "appointment_id": result.id,
        "confirmation_code": result.confirmation_code,
        "status": result.status,
        "local_date": result.local_date.isoformat(),
        "local_start_time": result.local_start_time.strftime("%H:%M"),
        "local_end_time": result.local_end_time.strftime("%H:%M"),
        "timezone": result.timezone,
        "services": [snapshot.model_dump() for snapshot in result.services],
        "total_duration_minutes": result.total_duration_minutes,
        "total_price_cents": result.total_price_cents,
    }
    if any(snapshot.name == "Platinado / Luzes" for snapshot in result.services):
        summary["total_price_is_estimate"] = True
    return summary


def _format_brl(price_cents: int) -> str:
    reais, cents = divmod(price_cents, 100)
    return f"R$ {reais},{cents:02d}"
