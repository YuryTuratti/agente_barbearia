from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.database.models import InboundMessage, OutboundMessage
from app.exceptions.handlers import PermanentMessageHandlingError
from app.services.inbound_message_processor import InboundMessageProcessor


class SuccessfulHandler:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def handle(self, message: InboundMessage) -> None:
        self.calls.append(message.id)


class FailingHandler:
    async def handle(self, message: InboundMessage) -> None:
        raise RuntimeError("simulated failure")


class FailsFirstHandler:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def handle(self, message: InboundMessage) -> None:
        self.calls.append(message.id)
        if len(self.calls) == 1:
            raise RuntimeError("simulated failure")


class PermanentlyFailingHandler:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def handle(self, message: InboundMessage) -> None:
        self.calls.append(message.id)
        raise PermanentMessageHandlingError("permanent safe failure")


class PermanentThenSuccessHandler:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def handle(self, message: InboundMessage) -> None:
        self.calls.append(message.id)
        if len(self.calls) == 1:
            raise PermanentMessageHandlingError("permanent safe failure")


@pytest.mark.anyio
async def test_successful_handler_marks_message_completed(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    record = await _insert_message(session_maker)
    handler = SuccessfulHandler()
    processor = InboundMessageProcessor(session_maker, handler, _settings())

    processed_count = await processor.process_once()
    updated_record = await _get_message(session_maker, record.id)

    assert processed_count == 1
    assert updated_record.status == "completed"
    assert updated_record.processed_at is not None
    assert updated_record.attempts == 1
    assert updated_record.locked_at is None
    assert handler.calls == [record.id]
    assert await _count_outbound(session_maker) == 0


@pytest.mark.anyio
async def test_failing_handler_returns_message_to_pending_before_max_attempts(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    record = await _insert_message(session_maker)
    processor = InboundMessageProcessor(session_maker, FailingHandler(), _settings())

    processed_count = await processor.process_once()
    updated_record = await _get_message(session_maker, record.id)

    assert processed_count == 1
    assert updated_record.status == "pending"
    assert updated_record.last_error == "simulated failure"
    assert updated_record.next_attempt_at is not None
    assert updated_record.locked_at is None


@pytest.mark.anyio
async def test_failing_handler_marks_failed_at_max_attempts(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    record = await _insert_message(session_maker, attempts=2)
    processor = InboundMessageProcessor(session_maker, FailingHandler(), _settings())

    await processor.process_once()
    updated_record = await _get_message(session_maker, record.id)

    assert updated_record.status == "failed"
    assert updated_record.next_attempt_at is None
    assert updated_record.locked_at is None


@pytest.mark.anyio
async def test_one_failed_message_does_not_prevent_next_message(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    first_record = await _insert_message(session_maker, message_id="FIRST")
    second_record = await _insert_message(session_maker, message_id="SECOND")
    handler = FailsFirstHandler()
    processor = InboundMessageProcessor(
        session_maker,
        handler,
        _settings(worker_batch_size=2),
    )

    processed_count = await processor.process_once()
    first_updated = await _get_message(session_maker, first_record.id)
    second_updated = await _get_message(session_maker, second_record.id)

    assert processed_count == 2
    assert first_updated.status == "pending"
    assert second_updated.status == "completed"
    assert handler.calls == [first_record.id, second_record.id]


@pytest.mark.anyio
async def test_permanent_handler_error_marks_failed_without_retry(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    record = await _insert_message(session_maker)
    handler = PermanentlyFailingHandler()

    processed_count = await InboundMessageProcessor(
        session_maker,
        handler,
        _settings(),
    ).process_once()
    updated = await _get_message(session_maker, record.id)

    assert processed_count == 1
    assert updated.status == "failed"
    assert updated.locked_at is None
    assert updated.next_attempt_at is None
    assert updated.last_error == "permanent safe failure"


@pytest.mark.anyio
async def test_permanent_failure_does_not_prevent_next_message(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    first = await _insert_message(session_maker, message_id="FIRST")
    second = await _insert_message(session_maker, message_id="SECOND")
    handler = PermanentThenSuccessHandler()

    await InboundMessageProcessor(
        session_maker,
        handler,
        _settings(worker_batch_size=2),
    ).process_once()

    assert (await _get_message(session_maker, first.id)).status == "failed"
    assert (await _get_message(session_maker, second.id)).status == "completed"


@pytest.mark.anyio
async def test_message_already_processing_is_not_delivered_to_processor(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _insert_message(session_maker, status="processing", locked_at=_now())
    handler = SuccessfulHandler()
    processor = InboundMessageProcessor(session_maker, handler, _settings())

    processed_count = await processor.process_once()

    assert processed_count == 0
    assert handler.calls == []


@pytest.mark.anyio
async def test_two_sequential_processors_do_not_process_same_message(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    record = await _insert_message(session_maker)
    first_handler = SuccessfulHandler()
    second_handler = SuccessfulHandler()

    first_count = await InboundMessageProcessor(
        session_maker,
        first_handler,
        _settings(),
    ).process_once()
    second_count = await InboundMessageProcessor(
        session_maker,
        second_handler,
        _settings(),
    ).process_once()

    assert first_count == 1
    assert second_count == 0
    assert first_handler.calls == [record.id]
    assert second_handler.calls == []


@pytest.mark.anyio
async def test_empty_allowlist_preserves_current_processing(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    record = await _insert_message(session_maker)
    handler = SuccessfulHandler()

    await InboundMessageProcessor(
        session_maker, handler, _settings(inbound_allowed_phones="")
    ).process_once()

    assert handler.calls == [record.id]


@pytest.mark.anyio
async def test_allowed_phone_is_processed_and_multiple_entries_are_supported(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    record = await _insert_message(session_maker)
    handler = SuccessfulHandler()

    await InboundMessageProcessor(
        session_maker,
        handler,
        _settings(inbound_allowed_phones="5534888888888, +55 (34) 99999-9999"),
    ).process_once()

    assert handler.calls == [record.id]


@pytest.mark.anyio
async def test_disallowed_phone_skips_handler_and_outbound_and_masks_log(
    session_maker: async_sessionmaker[AsyncSession], caplog
) -> None:
    caplog.set_level("INFO", logger="app.services.inbound_message_processor")
    record = await _insert_message(session_maker)
    handler = SuccessfulHandler()

    await InboundMessageProcessor(
        session_maker,
        handler,
        _settings(inbound_allowed_phones="5534888888888"),
    ).process_once()

    assert handler.calls == []
    assert await _count_outbound(session_maker) == 0
    assert (await _get_message(session_maker, record.id)).status == "completed"
    assert "5534999999999" not in caplog.text
    assert "55******9999" in caplog.text


async def _insert_message(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    message_id: str = "ABC123",
    status: str = "pending",
    attempts: int = 0,
    locked_at: datetime | None = None,
) -> InboundMessage:
    async with session_maker() as session:
        record = InboundMessage(
            instance="turatti-barbe",
            message_id=message_id,
            event="messages.upsert",
            remote_jid="5534999999999@s.whatsapp.net",
            phone="5534999999999",
            sender_name="Cliente Teste",
            message_type="text",
            text="Olá, gostaria de marcar um corte amanhã.",
            media_mimetype=None,
            message_timestamp=1_719_000_000,
            status=status,
            attempts=attempts,
            locked_at=locked_at,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)

        return record


async def _get_message(
    session_maker: async_sessionmaker[AsyncSession],
    record_id: str,
) -> InboundMessage:
    async with session_maker() as session:
        result = await session.execute(
            select(InboundMessage).where(InboundMessage.id == record_id)
        )

        return result.scalar_one()


def _settings(
    *, worker_batch_size: int = 1, inbound_allowed_phones: str = ""
) -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///test.db",
        worker_poll_interval_seconds=0.01,
        worker_max_attempts=3,
        worker_retry_delay_seconds=30,
        worker_processing_timeout_seconds=300,
        worker_batch_size=worker_batch_size,
        inbound_allowed_phones=inbound_allowed_phones,
    )


async def _count_outbound(session_maker: async_sessionmaker[AsyncSession]) -> int:
    async with session_maker() as session:
        result = await session.execute(select(OutboundMessage))
        return len(result.scalars().all())


def _now() -> datetime:
    return datetime.now(UTC)
