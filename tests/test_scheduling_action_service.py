from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.database.models import Appointment, InboundMessage, PendingSchedulingAction
from app.exceptions.scheduling_actions import ConfirmationRequiresNewMessageError, NoPendingActionError
from app.schemas.scheduling_action import (
    CancelAppointmentActionPayload,
    CreateAppointmentActionPayload,
    RescheduleAppointmentActionPayload,
)
from app.services.scheduling_action_service import SchedulingActionService
from app.services.scheduling_service import SchedulingService
from tests.scheduling_helpers import FakeClock, add_hours, add_service, scheduling_settings


@pytest.mark.anyio
async def test_prepare_create_creates_pending_action_without_appointment_or_customer(session_maker):
    async with session_maker() as session:
        service = await add_service(session)
        service_id = service.id
        await add_hours(session)
        inbound = _inbound("prepare-1")
        session.add(inbound)
        await session.commit()

    action_service = _service(session_maker)
    result = await action_service.prepare_create(
        message=inbound,
        payload=CreateAppointmentActionPayload(
            service_ids=[service_id],
            local_date=date(2026, 7, 10),
            local_start_time=time(8, 0),
            customer_name="Cliente",
        ),
    )

    async with session_maker() as session:
        actions = list((await session.execute(select(PendingSchedulingAction))).scalars().all())
        appointments = list((await session.execute(select(Appointment))).scalars().all())

    assert result.confirmation_required is True
    assert result.summary["total_duration_minutes"] == 30
    assert result.summary["total_price_cents"] == 3500
    assert len(actions) == 1
    assert actions[0].phone == "5534999999999"
    assert actions[0].instance == "turatti"
    assert actions[0].confirmation_fingerprint
    assert appointments == []


@pytest.mark.anyio
async def test_new_prepare_supersedes_previous_action(session_maker):
    async with session_maker() as session:
        service = await add_service(session)
        service_id = service.id
        await add_hours(session)
        first = _inbound("prepare-1")
        second = _inbound("prepare-2")
        session.add_all([first, second])
        await session.commit()

    action_service = _service(session_maker)
    payload = CreateAppointmentActionPayload(
        service_ids=[service_id],
        local_date=date(2026, 7, 10),
        local_start_time=time(8, 0),
        customer_name=None,
    )
    await action_service.prepare_create(message=first, payload=payload)
    await action_service.prepare_create(
        message=second,
        payload=CreateAppointmentActionPayload(
            service_ids=[service_id],
            local_date=date(2026, 7, 10),
            local_start_time=time(8, 30),
            customer_name=None,
        ),
    )

    async with session_maker() as session:
        statuses = [row.status for row in (await session.execute(select(PendingSchedulingAction).order_by(PendingSchedulingAction.created_at))).scalars().all()]
    assert statuses == ["superseded", "awaiting_confirmation"]


@pytest.mark.anyio
async def test_confirm_create_requires_new_message_and_then_creates_once(session_maker):
    async with session_maker() as session:
        service = await add_service(session)
        service_id = service.id
        await add_hours(session)
        prepare = _inbound("prepare-1", text="Quero marcar")
        confirm = _inbound("confirm-1", text="sim")
        session.add_all([prepare, confirm])
        await session.commit()

    action_service = _service(session_maker)
    await action_service.prepare_create(
        message=prepare,
        payload=CreateAppointmentActionPayload(
            service_ids=[service_id],
            local_date=date(2026, 7, 10),
            local_start_time=time(8, 0),
            customer_name=None,
        ),
    )
    with pytest.raises(ConfirmationRequiresNewMessageError):
        await action_service.confirm_pending_action(message=prepare)

    result = await action_service.confirm_pending_action(message=confirm)

    async with session_maker() as session:
        appointments = list((await session.execute(select(Appointment))).scalars().all())
        action = (await session.execute(select(PendingSchedulingAction))).scalar_one()

    assert result.status == "completed"
    assert len(appointments) == 1
    assert appointments[0].idempotency_key == f"pending-action:{action.id}"
    assert action.status == "completed"
    assert action.confirmed_by_inbound_message_id == "confirm-1"
    assert action.result_appointment_id == appointments[0].id


@pytest.mark.anyio
async def test_prepare_cancel_and_confirm_soft_deletes_only_after_confirmation(session_maker):
    appointment_id = await _create_existing_appointment(session_maker)
    async with session_maker() as session:
        prepare = _inbound("prepare-cancel", text="Cancelar")
        confirm = _inbound("confirm-cancel", text="pode cancelar")
        session.add_all([prepare, confirm])
        await session.commit()

    action_service = _service(session_maker)
    await action_service.prepare_cancel(
        message=prepare,
        payload=CancelAppointmentActionPayload(appointment_id=appointment_id, reason="Cliente pediu"),
    )
    async with session_maker() as session:
        assert (await session.get(Appointment, appointment_id)).status == "scheduled"

    await action_service.confirm_pending_action(message=confirm)

    async with session_maker() as session:
        assert (await session.get(Appointment, appointment_id)).status == "cancelled"


@pytest.mark.anyio
async def test_prepare_reschedule_changes_time_only_after_confirmation(session_maker):
    appointment_id = await _create_existing_appointment(session_maker)
    async with session_maker() as session:
        prepare = _inbound("prepare-reschedule", text="Mudar")
        confirm = _inbound("confirm-reschedule", text="confirmo")
        session.add_all([prepare, confirm])
        await session.commit()

    action_service = _service(session_maker)
    await action_service.prepare_reschedule(
        message=prepare,
        payload=RescheduleAppointmentActionPayload(
            appointment_id=appointment_id,
            new_local_date=date(2026, 7, 10),
            new_local_start_time=time(8, 30),
        ),
    )
    async with session_maker() as session:
        assert (await session.get(Appointment, appointment_id)).start_at.hour == 11

    await action_service.confirm_pending_action(message=confirm)

    async with session_maker() as session:
        appointment = await session.get(Appointment, appointment_id)
        assert appointment.id == appointment_id
        assert appointment.start_at.hour == 11
        assert appointment.start_at.minute == 30


@pytest.mark.anyio
async def test_discard_rejects_action_without_modifying_agenda(session_maker):
    async with session_maker() as session:
        service = await add_service(session)
        service_id = service.id
        await add_hours(session)
        prepare = _inbound("prepare-discard")
        reject = _inbound("reject-discard", text="deixa para lá")
        session.add_all([prepare, reject])
        await session.commit()

    action_service = _service(session_maker)
    await action_service.prepare_create(
        message=prepare,
        payload=CreateAppointmentActionPayload(
            service_ids=[service_id],
            local_date=date(2026, 7, 10),
            local_start_time=time(8, 0),
            customer_name=None,
        ),
    )
    result = await action_service.discard_pending_action(message=reject)

    async with session_maker() as session:
        assert (await session.execute(select(Appointment))).scalars().all() == []
        action = (await session.execute(select(PendingSchedulingAction))).scalar_one()
    assert result.status == "rejected"
    assert action.status == "rejected"


@pytest.mark.anyio
async def test_expired_action_cannot_be_confirmed(session_maker):
    async with session_maker() as session:
        service = await add_service(session)
        service_id = service.id
        await add_hours(session)
        prepare = _inbound("prepare-expire")
        confirm = _inbound("confirm-expire", text="sim")
        session.add_all([prepare, confirm])
        await session.commit()

    action_service = _service(
        session_maker,
        now=datetime(2026, 7, 10, 6, 0, tzinfo=UTC),
        scheduling_confirmation_ttl_minutes=1,
    )
    await action_service.prepare_create(
        message=prepare,
        payload=CreateAppointmentActionPayload(
            service_ids=[service_id],
            local_date=date(2026, 7, 10),
            local_start_time=time(8, 0),
            customer_name=None,
        ),
    )
    expired_service = _service(
        session_maker,
        now=datetime(2026, 7, 10, 6, 2, tzinfo=UTC),
        scheduling_confirmation_ttl_minutes=1,
    )

    with pytest.raises(NoPendingActionError):
        await expired_service.confirm_pending_action(message=confirm)


async def _create_existing_appointment(session_maker) -> str:
    async with session_maker() as session:
        service = await add_service(session)
        service_id = service.id
        await add_hours(session)
        scheduler = SchedulingService(
            session,
            settings=scheduling_settings(),
            clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
        )
        result = await scheduler.create_appointment(
            instance="turatti",
            phone="5534999999999",
            customer_name=None,
            service_ids=[service_id],
            local_date=date(2026, 7, 10),
            local_start_time=time(8, 0),
        )
        return result.id


def _service(session_maker, *, now: datetime | None = None, **settings_overrides) -> SchedulingActionService:
    return SchedulingActionService(
        session_factory=session_maker,
        settings=scheduling_settings(**settings_overrides),
        clock=FakeClock(now or datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
    )


def _inbound(message_id: str, *, text: str = "texto") -> InboundMessage:
    return InboundMessage(
        id=message_id,
        instance="turatti",
        message_id=message_id,
        phone="5534999999999",
        message_type="text",
        text=text,
        created_at=datetime(2026, 7, 10, 6, 0, tzinfo=UTC),
    )
