from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.database.models import OutboundMessage
from app.exceptions.evolution import EvolutionPermanentError, EvolutionTemporaryError
from app.schemas.outbound_message import EvolutionSendResult
from app.services.outbound_message_processor import OutboundMessageProcessor


class FakeSuccessClient:
    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession] | None = None,
        external_message_id: str | None = "external-1",
    ) -> None:
        self.sent_ids: list[str] = []
        self.session_maker = session_maker
        self.external_message_id = external_message_id

    async def send_text(self, *, instance: str, recipient: str, text: str):
        if self.session_maker is not None:
            async with self.session_maker() as session:
                result = await session.execute(
                    select(OutboundMessage.status).where(
                        OutboundMessage.deduplication_key == text
                    )
                )
                assert result.scalar_one() == "sending"
        self.sent_ids.append(text)
        return EvolutionSendResult(
            success=True,
            external_message_id=self.external_message_id,
            status_code=200,
        )


class FakeFailingClient:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def send_text(self, *, instance: str, recipient: str, text: str):
        self.calls += 1
        raise self.error


class FakeFailsFirstClient:
    def __init__(self) -> None:
        self.calls = 0

    async def send_text(self, *, instance: str, recipient: str, text: str):
        self.calls += 1
        if self.calls == 1:
            raise EvolutionTemporaryError("temporary")
        return EvolutionSendResult(
            success=True,
            external_message_id=None,
            status_code=200,
        )


@pytest.mark.anyio
async def test_successful_send_marks_sent_and_stores_external_id(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    record = await _insert_outbound(session_maker, deduplication_key="msg-1")
    client = FakeSuccessClient()
    processor = OutboundMessageProcessor(
        session_factory=session_maker,
        evolution_client=client,
        settings=_settings(),
    )

    claimed = await processor.process_once()
    updated = await _get_outbound(session_maker, record.id)

    assert claimed == 1
    assert updated.status == "sent"
    assert updated.external_message_id == "external-1"


@pytest.mark.anyio
async def test_success_without_external_id_is_sent(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    record = await _insert_outbound(session_maker)
    processor = OutboundMessageProcessor(
        session_factory=session_maker,
        evolution_client=FakeSuccessClient(external_message_id=None),
        settings=_settings(),
    )

    await processor.process_once()
    updated = await _get_outbound(session_maker, record.id)

    assert updated.status == "sent"
    assert updated.external_message_id is None


@pytest.mark.anyio
async def test_temporary_and_permanent_failures_update_status(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    temporary = await _insert_outbound(session_maker, deduplication_key="temporary")
    temporary_processor = OutboundMessageProcessor(
        session_factory=session_maker,
        evolution_client=FakeFailingClient(EvolutionTemporaryError("temporary")),
        settings=_settings(),
    )
    await temporary_processor.process_once()
    assert (await _get_outbound(session_maker, temporary.id)).status == "pending"

    permanent = await _insert_outbound(session_maker, deduplication_key="permanent")
    permanent_processor = OutboundMessageProcessor(
        session_factory=session_maker,
        evolution_client=FakeFailingClient(EvolutionPermanentError("permanent")),
        settings=_settings(),
    )
    await permanent_processor.process_once()
    assert (await _get_outbound(session_maker, permanent.id)).status == "failed"


@pytest.mark.anyio
async def test_one_failure_does_not_prevent_next_message(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    first = await _insert_outbound(session_maker, deduplication_key="first")
    second = await _insert_outbound(session_maker, deduplication_key="second")
    processor = OutboundMessageProcessor(
        session_factory=session_maker,
        evolution_client=FakeFailsFirstClient(),
        settings=_settings(outbound_worker_batch_size=2),
    )

    claimed = await processor.process_once()

    assert claimed == 2
    assert (await _get_outbound(session_maker, first.id)).status == "pending"
    assert (await _get_outbound(session_maker, second.id)).status == "sent"


@pytest.mark.anyio
async def test_http_happens_after_claim_commit_and_sent_is_not_resent(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_outbound(session_maker, deduplication_key="msg-1", text="msg-1")
    client = FakeSuccessClient(session_maker=session_maker)
    processor = OutboundMessageProcessor(
        session_factory=session_maker,
        evolution_client=client,
        settings=_settings(),
    )

    first = await processor.process_once()
    second = await processor.process_once()

    assert first == 1
    assert second == 0
    assert client.sent_ids == ["msg-1"]


@pytest.mark.anyio
async def test_stale_messages_are_recovered(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    record = await _insert_outbound(
        session_maker,
        status="sending",
        attempts=1,
        locked_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    processor = OutboundMessageProcessor(
        session_factory=session_maker,
        evolution_client=FakeSuccessClient(),
        settings=_settings(),
    )

    claimed = await processor.process_once()
    updated = await _get_outbound(session_maker, record.id)

    assert claimed == 1
    assert updated.status == "sent"


async def _insert_outbound(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    deduplication_key: str = "msg-1",
    text: str = "ok",
    status: str = "pending",
    attempts: int = 0,
    locked_at: datetime | None = None,
) -> OutboundMessage:
    async with session_maker() as session:
        record = OutboundMessage(
            deduplication_key=deduplication_key,
            instance="turatti-barbe",
            recipient="5534999999999",
            message_type="text",
            text=text,
            status=status,
            attempts=attempts,
            locked_at=locked_at,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


async def _get_outbound(
    session_maker: async_sessionmaker[AsyncSession],
    record_id: str,
) -> OutboundMessage:
    async with session_maker() as session:
        result = await session.execute(
            select(OutboundMessage).where(OutboundMessage.id == record_id)
        )
        return result.scalar_one()


def _settings(**overrides: object) -> Settings:
    values = {
        "database_url": "sqlite+aiosqlite:///test.db",
        "outbound_worker_poll_interval_seconds": 0.01,
        "outbound_worker_max_attempts": 3,
        "outbound_worker_retry_delay_seconds": 30,
        "outbound_worker_processing_timeout_seconds": 300,
        "outbound_worker_batch_size": 1,
    }
    values.update(overrides)
    return Settings(**values)
