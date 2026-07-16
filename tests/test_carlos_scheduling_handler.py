from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.database.models import InboundMessage, OutboundMessage
from app.exceptions.handlers import PermanentMessageHandlingError
from app.handlers.carlos_scheduling_handler import CarlosSchedulingHandler


class FakeSchedulingResponseService:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    async def generate_reply(self, message: InboundMessage) -> str:
        self.calls += 1
        return "Resposta com agenda."

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_carlos_scheduling_handler_enqueues_text_reply_once(session_maker):
    service = FakeSchedulingResponseService()
    handler = CarlosSchedulingHandler(
        session_factory=session_maker,
        response_service=service,
    )
    message = _message()

    await handler.handle(message)
    await handler.handle(message)

    async with session_maker() as session:
        outbounds = list((await session.execute(select(OutboundMessage))).scalars().all())

    assert service.calls == 1
    assert len(outbounds) == 1
    assert outbounds[0].deduplication_key == "inbound-reply:inbound-id"
    assert outbounds[0].text == "Resposta com agenda."


@pytest.mark.anyio
async def test_carlos_scheduling_handler_media_does_not_call_openai(session_maker):
    service = FakeSchedulingResponseService()
    handler = CarlosSchedulingHandler(
        session_factory=session_maker,
        response_service=service,
    )
    message = _message(message_type="image", text=None)

    await handler.handle(message)

    async with session_maker() as session:
        outbound = (await session.execute(select(OutboundMessage))).scalar_one()

    assert service.calls == 0
    assert "mensagens de texto" in outbound.text


@pytest.mark.anyio
async def test_carlos_scheduling_handler_without_phone_is_permanent(session_maker):
    handler = CarlosSchedulingHandler(
        session_factory=session_maker,
        response_service=FakeSchedulingResponseService(),
    )

    with pytest.raises(PermanentMessageHandlingError):
        await handler.handle(_message(phone=None))


def _message(
    *,
    phone: str | None = "5534999999999",
    message_type: str = "text",
    text: str | None = "Quais serviços?",
) -> InboundMessage:
    return InboundMessage(
        id="inbound-id",
        instance="turatti",
        message_id="message-id",
        phone=phone,
        message_type=message_type,
        text=text,
        created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
    )
