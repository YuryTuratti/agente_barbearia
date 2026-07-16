from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import select

from app.database.models import InboundMessage
from app.tools.scheduling_definitions import (
    LIST_AVAILABLE_SLOTS_TOOL_NAME,
    LIST_MY_APPOINTMENTS_TOOL_NAME,
    LIST_SERVICES_TOOL_NAME,
)
from app.tools.scheduling_executor import SchedulingToolExecutor
from tests.scheduling_helpers import FakeClock, add_hours, add_service, scheduling_settings


@pytest.mark.anyio
async def test_executor_list_services_returns_active_services_in_cents(session_maker):
    async with session_maker() as session:
        await add_service(session, slug="ativo", price_cents=3500)
        await add_service(session, slug="inativo", active=False, price_cents=9999)

    executor = _executor(session_maker)
    result = await executor.execute(
        tool_name=LIST_SERVICES_TOOL_NAME,
        arguments_json="{}",
        message=_message(),
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data["services"] == [
        {
            "id": result.data["services"][0]["id"],
            "slug": "ativo",
            "name": "Corte",
            "description": None,
            "duration_minutes": 30,
            "duration_configured": True,
            "booking_enabled": True,
            "price_type": "fixed",
            "price_cents": 3500,
            "price_display": "R$ 35,00",
            "requires_quote": False,
        }
    ]


@pytest.mark.anyio
async def test_executor_rejects_identity_fields_and_invalid_arguments(session_maker):
    async with session_maker() as session:
        service = await add_service(session)
        service_id = service.id

    executor = _executor(session_maker)

    for payload in (
        '{"phone": "5534000000000"}',
        '{"instance": "other"}',
        '{"local_date": "amanha", "service_ids": ["x"]}',
        '{"local_date": "2026-07-10", "service_ids": []}',
        f'{{"local_date": "2026-07-10", "service_ids": ["{service_id}", "{service_id}"]}}',
    ):
        result = await executor.execute(
            tool_name=LIST_AVAILABLE_SLOTS_TOOL_NAME,
            arguments_json=payload,
            message=_message(),
        )
        assert result.ok is False
        assert result.error is not None
        assert result.error.code in {"invalid_arguments", "invalid_date"}


@pytest.mark.anyio
async def test_executor_list_available_slots_injects_instance_and_resource_key(session_maker):
    async with session_maker() as session:
        service = await add_service(session)
        service_id = service.id
        await add_hours(
            session,
            instance="backend-instance",
            resource_key="main",
            weekday=4,
            opens_at=time(8, 0),
            closes_at=time(9, 0),
        )

    executor = _executor(session_maker)
    result = await executor.execute(
        tool_name=LIST_AVAILABLE_SLOTS_TOOL_NAME,
        arguments_json=f'{{"local_date": "2026-07-10", "service_ids": ["{service_id}"]}}',
        message=_message(instance="backend-instance"),
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data["slots"] != []
    assert "5534999999999" not in result.model_dump_json()


@pytest.mark.anyio
async def test_executor_list_available_slots_returns_safe_errors(session_maker):
    executor = _executor(session_maker)
    result = await executor.execute(
        tool_name=LIST_AVAILABLE_SLOTS_TOOL_NAME,
        arguments_json='{"local_date": "2026-07-10", "service_ids": ["missing"]}',
        message=_message(),
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "service_not_found"
    assert "SQL" not in result.model_dump_json()
    assert "5534999999999" not in result.model_dump_json()


@pytest.mark.anyio
async def test_executor_list_my_appointments_uses_current_phone_only(session_maker):
    async with session_maker() as session:
        service = await add_service(session)
        service_id = service.id
        await add_hours(session)
    from app.services.scheduling_service import SchedulingService

    async with session_maker() as session:
        scheduler = SchedulingService(
            session,
            settings=scheduling_settings(),
            clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
        )
        await scheduler.create_appointment(
            instance="turatti",
            phone="5534999999999",
            customer_name=None,
            service_ids=[service_id],
            local_date=date(2026, 7, 10),
            local_start_time=time(8, 0),
        )

    executor = _executor(session_maker)
    result = await executor.execute(
        tool_name=LIST_MY_APPOINTMENTS_TOOL_NAME,
        arguments_json="{}",
        message=_message(phone="5534999999999"),
    )
    other = await executor.execute(
        tool_name=LIST_MY_APPOINTMENTS_TOOL_NAME,
        arguments_json="{}",
        message=_message(phone="5534888888888"),
    )

    assert result.ok is True
    assert result.data is not None
    assert len(result.data["appointments"]) == 1
    assert other.data == {"appointments": []}


@pytest.mark.anyio
async def test_executor_rejects_unknown_json_and_missing_phone(session_maker):
    executor = _executor(session_maker)
    unknown = await executor.execute(tool_name="drop_table", arguments_json="{}", message=_message())
    invalid_json = await executor.execute(
        tool_name=LIST_SERVICES_TOOL_NAME,
        arguments_json="{",
        message=_message(),
    )
    no_phone = await executor.execute(
        tool_name=LIST_MY_APPOINTMENTS_TOOL_NAME,
        arguments_json="{}",
        message=_message(phone=None),
    )

    assert unknown.ok is False
    assert invalid_json.ok is False
    assert no_phone.ok is False
    assert no_phone.error is not None
    assert no_phone.error.code == "customer_not_found"


def _executor(session_maker) -> SchedulingToolExecutor:
    return SchedulingToolExecutor(
        session_factory=session_maker,
        settings=scheduling_settings(),
        clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
    )


def _message(
    *,
    instance: str = "turatti",
    phone: str | None = "5534999999999",
) -> InboundMessage:
    return InboundMessage(
        id="inbound-id",
        instance=instance,
        message_id="message-id",
        phone=phone,
        message_type="text",
        text="Oi",
    )
