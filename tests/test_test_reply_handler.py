import logging
from copy import copy

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import InboundMessage, OutboundMessage
from app.handlers.test_reply_handler import (
    TEST_REPLY_TEXT,
    MissingInboundPhoneError,
    TestReplyHandler,
)


@pytest.mark.anyio
async def test_handler_creates_idempotent_outbound_message(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    inbound = await _insert_inbound(session_maker)
    handler = TestReplyHandler(session_maker)

    await handler.handle(inbound)
    await handler.handle(inbound)
    records = await _list_outbound(session_maker)

    assert len(records) == 1
    assert records[0].instance == inbound.instance
    assert records[0].recipient == inbound.phone
    assert records[0].deduplication_key == f"inbound-reply:{inbound.id}"
    assert records[0].text == TEST_REPLY_TEXT


@pytest.mark.anyio
async def test_handler_does_not_alter_inbound_message(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    inbound = await _insert_inbound(session_maker)
    original = copy(inbound.__dict__)

    await TestReplyHandler(session_maker).handle(inbound)

    assert inbound.__dict__ == original


@pytest.mark.anyio
async def test_missing_phone_raises_safe_error(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    inbound = await _insert_inbound(session_maker, phone=None)

    with pytest.raises(MissingInboundPhoneError) as error:
        await TestReplyHandler(session_maker).handle(inbound)

    assert "5534999999999" not in str(error.value)
    assert "Mensagem" not in str(error.value)


@pytest.mark.anyio
async def test_handler_logs_do_not_include_phone_or_text(
    session_maker: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    inbound = await _insert_inbound(session_maker)

    with caplog.at_level(logging.INFO):
        await TestReplyHandler(session_maker).handle(inbound)

    assert "5534999999999" not in caplog.text
    assert TEST_REPLY_TEXT not in caplog.text


async def _insert_inbound(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    phone: str | None = "5534999999999",
) -> InboundMessage:
    async with session_maker() as session:
        record = InboundMessage(
            instance="turatti-barbe",
            message_id="ABC123",
            remote_jid="5534999999999@s.whatsapp.net",
            phone=phone,
            sender_name="Cliente Teste",
            message_type="text",
            text="ola",
            status="processing",
            attempts=1,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


async def _list_outbound(
    session_maker: async_sessionmaker[AsyncSession],
) -> list[OutboundMessage]:
    async with session_maker() as session:
        result = await session.execute(select(OutboundMessage))
        return list(result.scalars().all())
