from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.database.models import InboundMessage
from app.exceptions.handlers import PermanentMessageHandlingError
from app.exceptions.openai import OpenAIInvalidResponseError
from app.schemas.openai_response import OpenAITextResult
from app.services.carlos_response_service import CarlosResponseService


class FakeOpenAIClient:
    def __init__(self, text: str = "  Olá, tudo bem?  ") -> None:
        self.text = text
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def generate_text(self, *, instructions: str, messages: list[object]):
        self.calls.append({"instructions": instructions, "messages": messages})
        return OpenAITextResult(text=self.text, response_id="resp", model="fake")

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_service_loads_history_appends_current_and_normalizes(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    current = await _insert_inbound(session_maker, "current", text=" Quero cortar ")
    await _insert_inbound(
        session_maker,
        "previous",
        text="Ola",
        status="completed",
        created_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    client = FakeOpenAIClient()
    service = CarlosResponseService(
        session_factory=session_maker,
        openai_client=client,
        settings=_settings(),
    )

    reply = await service.generate_reply(current)
    messages = client.calls[0]["messages"]

    assert reply == "Olá, tudo bem?"
    assert [message.content for message in messages] == ["Ola", "Quero cortar"]
    assert messages[-1].role == "user"
    assert current.phone not in str(messages)
    assert current.instance not in str(messages)
    assert current.id not in str(messages)


@pytest.mark.anyio
async def test_openai_is_called_without_database_transaction(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    current = await _insert_inbound(session_maker, "current")

    class InspectingClient(FakeOpenAIClient):
        async def generate_text(self, *, instructions: str, messages: list[object]):
            async with session_maker() as session:
                result = await session.execute(select(InboundMessage.id))
                assert result.scalars().all()
            return await super().generate_text(
                instructions=instructions,
                messages=messages,
            )

    await CarlosResponseService(
        session_factory=session_maker,
        openai_client=InspectingClient(),
        settings=_settings(),
    ).generate_reply(current)


@pytest.mark.anyio
async def test_service_rejects_invalid_inbound_without_openai_call(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    empty = await _insert_inbound(session_maker, "empty", text=" ")
    no_phone = await _insert_inbound(session_maker, "no-phone", phone=None)
    client = FakeOpenAIClient()
    service = CarlosResponseService(
        session_factory=session_maker,
        openai_client=client,
        settings=_settings(),
    )

    with pytest.raises(PermanentMessageHandlingError):
        await service.generate_reply(empty)
    with pytest.raises(PermanentMessageHandlingError):
        await service.generate_reply(no_phone)

    assert client.calls == []


@pytest.mark.anyio
async def test_service_limits_characters_and_preserves_unicode(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    current = await _insert_inbound(session_maker, "current")
    service = CarlosResponseService(
        session_factory=session_maker,
        openai_client=FakeOpenAIClient("Olá cliente. Segunda frase muito longa."),
        settings=_settings(openai_max_reply_characters=12),
    )

    assert await service.generate_reply(current) == "Olá cliente."


@pytest.mark.anyio
async def test_service_rejects_empty_openai_reply(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    current = await _insert_inbound(session_maker, "current")
    service = CarlosResponseService(
        session_factory=session_maker,
        openai_client=FakeOpenAIClient("\x00   "),
        settings=_settings(),
    )

    with pytest.raises(OpenAIInvalidResponseError):
        await service.generate_reply(current)


async def _insert_inbound(
    session_maker: async_sessionmaker[AsyncSession],
    message_id: str,
    *,
    text: str = "Ola",
    phone: str | None = "5534999999999",
    status: str = "processing",
    created_at: datetime | None = None,
) -> InboundMessage:
    async with session_maker() as session:
        record = InboundMessage(
            instance="turatti-barbe",
            message_id=message_id,
            remote_jid="5534999999999@s.whatsapp.net",
            phone=phone,
            message_type="text",
            text=text,
            status=status,
            attempts=1,
            created_at=created_at or datetime.now(UTC),
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


def _settings(**overrides: object) -> Settings:
    values = {
        "database_url": "sqlite+aiosqlite:///test.db",
        "openai_history_limit": 12,
        "openai_max_reply_characters": 1200,
    }
    values.update(overrides)
    return Settings(**values)
