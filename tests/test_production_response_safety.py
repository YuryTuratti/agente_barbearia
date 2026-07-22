from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.database.models import InboundMessage
from app.repositories.inbound_message_repository import claim_pending_messages
from app.repositories.conversation_history_repository import get_recent_conversation
from app.services.outbound_safety import OUTSIDE_WINDOW_REPLY, secure_outbound_text
from app.tools.scheduling_executor import SchedulingToolExecutor
from tests.scheduling_helpers import FakeClock, scheduling_settings


LEAK = '''{
  "tool": "check_availability",
  "arguments": {
    "resource_key": "main",
    "date": "2033-07-30",
    "period": "morning"
  }
}Disponível às 09:00 e 10:30. Qual horário você prefere?'''


def test_tool_payload_and_absurd_date_never_reach_customer() -> None:
    result = secure_outbound_text(LEAK, local_today=date(2026, 7, 21))

    assert result == OUTSIDE_WINDOW_REPLY
    for forbidden in ("{", '"tool"', "arguments", "resource_key", "check_availability"):
        assert forbidden not in result.lower()


@pytest.mark.anyio
async def test_buffer_resets_and_only_latest_fragment_is_claimed(db_session) -> None:
    started = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    first = InboundMessage(
        instance="o-original", message_id="one", phone="5534999999999",
        message_type="text", text="quero cortar", status="pending",
        process_after_at=started + timedelta(seconds=40), created_at=started,
    )
    second = InboundMessage(
        instance="o-original", message_id="two", phone="5534999999999",
        message_type="text", text="amanhã de manhã com Lucas", status="pending",
        process_after_at=started + timedelta(seconds=40),
        created_at=started + timedelta(seconds=10),
    )
    db_session.add_all([first, second])
    await db_session.commit()

    assert await claim_pending_messages(
        db_session, limit=10, now=started + timedelta(seconds=30)
    ) == []
    claimed = await claim_pending_messages(
        db_session, limit=10, now=started + timedelta(seconds=40)
    )

    assert [item.message_id for item in claimed] == ["two"]
    old_status = await db_session.scalar(
        select(InboundMessage.status).where(InboundMessage.message_id == "one")
    )
    assert old_status == "completed"
    history = await get_recent_conversation(
        db_session,
        instance="o-original",
        phone="5534999999999",
        current_inbound_message_id=claimed[0].id,
        limit=10,
    )
    assert [item.content for item in history] == ["quero cortar"]


@pytest.mark.anyio
async def test_executor_blocks_2033_before_availability_query(session_maker) -> None:
    executor = SchedulingToolExecutor(
        session_factory=session_maker,
        settings=scheduling_settings(),
        clock=FakeClock(datetime(2026, 7, 21, 15, 0, tzinfo=UTC)),
    )
    message = InboundMessage(
        id="current", instance="o-original", message_id="m1",
        phone="5534999999999", message_type="text", text="em 2033",
    )

    result = await executor.execute(
        tool_name="list_available_slots",
        arguments_json='{"local_date":"2033-07-30","service_ids":["svc"]}',
        message=message,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "outside_booking_window"
