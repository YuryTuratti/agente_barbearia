from datetime import UTC, datetime

import pytest

from app.database.models import InboundMessage
from app.schemas.openai_response import OpenAIResponseTurn
from app.services.carlos_scheduling_write_service import CarlosSchedulingWriteService
from tests.scheduling_helpers import FakeClock, scheduling_settings


class FakeOpenAI:
    def __init__(self) -> None:
        self.calls = []
        self.closed = False

    async def create_tool_turn(self, **kwargs):
        self.calls.append(kwargs)
        return OpenAIResponseTurn(output_text="Resposta final.", tool_calls=[], response_output_items=[])

    async def close(self) -> None:
        self.closed = True


class FakeExecutor:
    async def execute(self, **kwargs):
        raise AssertionError("No tool should be executed.")


@pytest.mark.anyio
async def test_write_service_sends_nine_tools_without_identity_in_input(session_maker):
    openai = FakeOpenAI()
    service = CarlosSchedulingWriteService(
        session_factory=session_maker,
        openai_client=openai,
        tool_executor=FakeExecutor(),
        settings=scheduling_settings(),
        clock=FakeClock(datetime(2026, 7, 10, 12, 0, tzinfo=UTC)),
    )

    reply = await service.generate_reply(
        InboundMessage(
            id="inbound-id",
            instance="turatti",
            message_id="message-id",
            phone="5534999999999",
            message_type="text",
            text="Oi",
            created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        )
    )

    assert reply == "Resposta final."
    assert len(openai.calls[0]["tools"]) == 9
    assert "5534999999999" not in str(openai.calls[0]["input_items"])
    assert "turatti" not in str(openai.calls[0]["input_items"])
    assert "pending-action" not in str(openai.calls[0])
