from copy import copy
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import InboundMessage, OutboundMessage
from app.exceptions.handlers import PermanentMessageHandlingError
from app.exceptions.openai import OpenAIPermanentError, OpenAITemporaryError
from app.handlers.carlos_ai_handler import CarlosAIHandler, UNSUPPORTED_MEDIA_REPLY


class FakeResponseService:
    def __init__(self, reply: str = "Resposta do Carlos", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls = 0

    async def generate_reply(self, message: InboundMessage) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.reply

    async def close(self) -> None:
        return None


@pytest.mark.anyio
async def test_text_message_creates_outbound_idempotently(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    inbound = await _insert_inbound(session_maker)
    service = FakeResponseService("Claro, posso ajudar.")
    handler = CarlosAIHandler(session_factory=session_maker, response_service=service)

    original = copy(inbound.__dict__)
    await handler.handle(inbound)
    await handler.handle(inbound)
    records = await _outbound(session_maker)

    assert len(records) == 1
    assert records[0].recipient == inbound.phone
    assert records[0].instance == inbound.instance
    assert records[0].text == "Claro, posso ajudar."
    assert records[0].deduplication_key == f"inbound-reply:{inbound.id}"
    assert service.calls == 1
    assert inbound.__dict__ == original


@pytest.mark.anyio
@pytest.mark.parametrize("message_type", ["audio", "image", "video", "document"])
async def test_media_creates_fixed_reply_without_openai(
    session_maker: async_sessionmaker[AsyncSession],
    message_type: str,
) -> None:
    inbound = await _insert_inbound(session_maker, message_type=message_type, text=None)
    service = FakeResponseService()
    await CarlosAIHandler(session_factory=session_maker, response_service=service).handle(
        inbound
    )
    records = await _outbound(session_maker)

    assert service.calls == 0
    assert records[0].text == UNSUPPORTED_MEDIA_REPLY


@pytest.mark.anyio
async def test_invalid_text_and_missing_phone_are_permanent(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    empty = await _insert_inbound(session_maker, message_id="empty", text=" ")
    no_phone = await _insert_inbound(session_maker, message_id="no-phone", phone=None)
    handler = CarlosAIHandler(
        session_factory=session_maker,
        response_service=FakeResponseService(),
    )

    with pytest.raises(PermanentMessageHandlingError):
        await handler.handle(empty)
    with pytest.raises(PermanentMessageHandlingError):
        await handler.handle(no_phone)


@pytest.mark.anyio
async def test_openai_errors_are_mapped_or_propagated(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    temporary = await _insert_inbound(session_maker, message_id="temporary")
    permanent = await _insert_inbound(session_maker, message_id="permanent")

    with pytest.raises(OpenAITemporaryError):
        await CarlosAIHandler(
            session_factory=session_maker,
            response_service=FakeResponseService(error=OpenAITemporaryError("temp")),
        ).handle(temporary)

    with pytest.raises(PermanentMessageHandlingError):
        await CarlosAIHandler(
            session_factory=session_maker,
            response_service=FakeResponseService(error=OpenAIPermanentError("perm")),
        ).handle(permanent)


async def _insert_inbound(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    message_id: str = "ABC123",
    phone: str | None = "5534999999999",
    text: str | None = "Ola",
    message_type: str = "text",
) -> InboundMessage:
    async with session_maker() as session:
        record = InboundMessage(
            instance="turatti-barbe",
            message_id=message_id,
            remote_jid="5534999999999@s.whatsapp.net",
            phone=phone,
            message_type=message_type,
            text=text,
            status="processing",
            attempts=1,
            created_at=datetime.now(UTC),
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


async def _outbound(
    session_maker: async_sessionmaker[AsyncSession],
) -> list[OutboundMessage]:
    async with session_maker() as session:
        result = await session.execute(select(OutboundMessage))
        return list(result.scalars().all())
