from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import select

from app.database.models import Appointment, InboundMessage, PendingSchedulingAction
from app.services.scheduling_action_service import SchedulingActionService
from app.tools.scheduling_executor import SchedulingToolExecutor
from app.tools.scheduling_write_definitions import (
    CONFIRM_PENDING_ACTION_TOOL_NAME,
    PREPARE_CREATE_APPOINTMENT_TOOL_NAME,
)
from app.tools.scheduling_write_executor import SchedulingWriteToolExecutor
from tests.scheduling_helpers import FakeClock, add_hours, add_service, scheduling_settings


@pytest.mark.anyio
async def test_write_executor_prepare_does_not_create_appointment_and_confirm_requires_new_inbound(session_maker):
    async with session_maker() as session:
        service = await add_service(session)
        service_id = service.id
        await add_hours(session)
        prepare = _inbound("prepare", text="quero marcar")
        confirm = _inbound("confirm", text="sim")
        session.add_all([prepare, confirm])
        await session.commit()

    executor = _executor(session_maker)
    prepared = await executor.execute(
        tool_name=PREPARE_CREATE_APPOINTMENT_TOOL_NAME,
        arguments_json=(
            f'{{"service_ids": ["{service_id}"], "local_date": "2026-07-10", '
                '"local_start_time": "08:00", "customer_name": null, "barber": "lucas"}'
        ),
        message=prepare,
    )
    same_message_confirm = await executor.execute(
        tool_name=CONFIRM_PENDING_ACTION_TOOL_NAME,
        arguments_json="{}",
        message=prepare,
    )
    confirmed = await executor.execute(
        tool_name=CONFIRM_PENDING_ACTION_TOOL_NAME,
        arguments_json="{}",
        message=confirm,
    )

    async with session_maker() as session:
        appointments = list((await session.execute(select(Appointment))).scalars().all())
        action = (await session.execute(select(PendingSchedulingAction))).scalar_one()

    assert prepared.ok is True
    assert same_message_confirm.ok is False
    assert same_message_confirm.error.code == "confirmation_requires_new_message"
    assert confirmed.ok is True
    assert len(appointments) == 1
    assert action.status == "completed"
    assert "5534999999999" not in prepared.model_dump_json()


@pytest.mark.anyio
async def test_write_executor_rejects_phone_and_instance_arguments(session_maker):
    async with session_maker() as session:
        inbound = _inbound("prepare")
        session.add(inbound)
        await session.commit()
    executor = _executor(session_maker)

    result = await executor.execute(
        tool_name=PREPARE_CREATE_APPOINTMENT_TOOL_NAME,
        arguments_json=(
            '{"service_ids": ["x"], "local_date": "2026-07-10", '
            '"local_start_time": "08:00", "customer_name": null, '
            '"phone": "5534000000000", "instance": "other"}'
        ),
        message=inbound,
    )

    assert result.ok is False
    assert result.error.code == "invalid_arguments"


def _executor(session_maker) -> SchedulingWriteToolExecutor:
    settings = scheduling_settings()
    clock = FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC))
    return SchedulingWriteToolExecutor(
        read_executor=SchedulingToolExecutor(
            session_factory=session_maker,
            settings=settings,
            clock=clock,
        ),
        action_service=SchedulingActionService(
            session_factory=session_maker,
            settings=settings,
            clock=clock,
        ),
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
