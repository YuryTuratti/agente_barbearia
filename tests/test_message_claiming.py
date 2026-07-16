from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import InboundMessage
from app.repositories.inbound_message_repository import (
    InboundMessageStateError,
    claim_pending_messages,
    mark_message_completed,
    mark_message_failed,
    release_stale_processing_messages,
    sanitize_error_message,
)


@pytest.mark.anyio
async def test_pending_message_can_be_claimed(db_session: AsyncSession) -> None:
    record = await _insert_message(db_session)

    claimed = await claim_pending_messages(db_session, limit=1, now=_now())

    assert [message.id for message in claimed] == [record.id]


@pytest.mark.anyio
async def test_claim_sets_processing_attempts_and_locked_at(
    db_session: AsyncSession,
) -> None:
    record = await _insert_message(db_session)
    now = _now()

    await claim_pending_messages(db_session, limit=1, now=now)
    updated_record = await _get_message(db_session, record.id)

    assert updated_record.status == "processing"
    assert updated_record.attempts == 1
    assert updated_record.locked_at is not None


@pytest.mark.anyio
async def test_future_next_attempt_is_not_claimed(db_session: AsyncSession) -> None:
    await _insert_message(
        db_session,
        next_attempt_at=_now() + timedelta(minutes=5),
    )

    claimed = await claim_pending_messages(db_session, limit=1, now=_now())

    assert claimed == []


@pytest.mark.anyio
async def test_past_next_attempt_is_claimed(db_session: AsyncSession) -> None:
    record = await _insert_message(
        db_session,
        next_attempt_at=_now() - timedelta(minutes=5),
    )

    claimed = await claim_pending_messages(db_session, limit=1, now=_now())

    assert [message.id for message in claimed] == [record.id]


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["completed", "failed", "processing"])
async def test_non_pending_messages_are_not_claimed(
    db_session: AsyncSession,
    status: str,
) -> None:
    await _insert_message(db_session, status=status)

    claimed = await claim_pending_messages(db_session, limit=1, now=_now())

    assert claimed == []


@pytest.mark.anyio
async def test_mark_message_completed_updates_expected_fields(
    db_session: AsyncSession,
) -> None:
    record = await _insert_message(
        db_session,
        status="processing",
        locked_at=_now(),
        last_error="old error",
        next_attempt_at=_now(),
    )
    completed_at = _now()

    await mark_message_completed(db_session, record.id, completed_at=completed_at)
    updated_record = await _get_message(db_session, record.id)

    assert updated_record.status == "completed"
    assert updated_record.processed_at is not None
    assert updated_record.locked_at is None
    assert updated_record.last_error is None
    assert updated_record.next_attempt_at is None


@pytest.mark.anyio
async def test_mark_completed_requires_processing_status(
    db_session: AsyncSession,
) -> None:
    record = await _insert_message(db_session, status="pending")

    with pytest.raises(InboundMessageStateError):
        await mark_message_completed(db_session, record.id, completed_at=_now())


@pytest.mark.anyio
async def test_mark_failed_before_max_returns_to_pending_with_retry(
    db_session: AsyncSession,
) -> None:
    record = await _insert_message(
        db_session,
        status="processing",
        attempts=1,
        locked_at=_now(),
    )
    failed_at = _now()

    await mark_message_failed(
        db_session,
        record.id,
        error_message="simulated failure",
        failed_at=failed_at,
        max_attempts=3,
        retry_delay_seconds=30,
    )
    updated_record = await _get_message(db_session, record.id)

    assert updated_record.status == "pending"
    assert updated_record.locked_at is None
    assert updated_record.processed_at is None
    assert updated_record.last_error == "simulated failure"
    assert updated_record.next_attempt_at is not None


@pytest.mark.anyio
async def test_mark_failed_at_limit_becomes_failed(db_session: AsyncSession) -> None:
    record = await _insert_message(
        db_session,
        status="processing",
        attempts=3,
        locked_at=_now(),
    )

    await mark_message_failed(
        db_session,
        record.id,
        error_message="simulated failure",
        failed_at=_now(),
        max_attempts=3,
        retry_delay_seconds=30,
    )
    updated_record = await _get_message(db_session, record.id)

    assert updated_record.status == "failed"
    assert updated_record.locked_at is None
    assert updated_record.next_attempt_at is None


def test_sanitize_error_message_limits_size_and_handles_blank() -> None:
    assert len(sanitize_error_message("x" * 600)) == 500
    assert sanitize_error_message("   ") == "Unexpected processing error."


@pytest.mark.anyio
async def test_stale_processing_message_is_released(
    db_session: AsyncSession,
) -> None:
    record = await _insert_message(
        db_session,
        status="processing",
        attempts=1,
        locked_at=_now() - timedelta(minutes=10),
    )

    released = await release_stale_processing_messages(
        db_session,
        stale_before=_now() - timedelta(minutes=5),
        now=_now(),
        max_attempts=3,
    )
    updated_record = await _get_message(db_session, record.id)

    assert released == 1
    assert updated_record.status == "pending"
    assert updated_record.locked_at is None
    assert updated_record.next_attempt_at is not None
    assert updated_record.last_error == "Processing timeout."


@pytest.mark.anyio
async def test_non_stale_processing_message_is_not_changed(
    db_session: AsyncSession,
) -> None:
    record = await _insert_message(
        db_session,
        status="processing",
        attempts=1,
        locked_at=_now(),
    )

    released = await release_stale_processing_messages(
        db_session,
        stale_before=_now() - timedelta(minutes=5),
        now=_now(),
        max_attempts=3,
    )
    updated_record = await _get_message(db_session, record.id)

    assert released == 0
    assert updated_record.status == "processing"


@pytest.mark.anyio
async def test_stale_processing_message_at_limit_becomes_failed(
    db_session: AsyncSession,
) -> None:
    record = await _insert_message(
        db_session,
        status="processing",
        attempts=3,
        locked_at=_now() - timedelta(minutes=10),
    )

    released = await release_stale_processing_messages(
        db_session,
        stale_before=_now() - timedelta(minutes=5),
        now=_now(),
        max_attempts=3,
    )
    updated_record = await _get_message(db_session, record.id)

    assert released == 1
    assert updated_record.status == "failed"
    assert updated_record.locked_at is None
    assert updated_record.next_attempt_at is None


@pytest.mark.anyio
async def test_sequential_claims_do_not_deliver_same_message_twice(
    db_session: AsyncSession,
) -> None:
    await _insert_message(db_session)

    first_claim = await claim_pending_messages(db_session, limit=1, now=_now())
    second_claim = await claim_pending_messages(db_session, limit=1, now=_now())

    assert len(first_claim) == 1
    assert second_claim == []


async def _insert_message(
    session: AsyncSession,
    *,
    status: str = "pending",
    message_id: str = "ABC123",
    attempts: int = 0,
    locked_at: datetime | None = None,
    last_error: str | None = None,
    next_attempt_at: datetime | None = None,
) -> InboundMessage:
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
        last_error=last_error,
        next_attempt_at=next_attempt_at,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)

    return record


async def _get_message(session: AsyncSession, record_id: str) -> InboundMessage:
    result = await session.execute(
        select(InboundMessage).where(InboundMessage.id == record_id)
    )

    return result.scalar_one()


def _now() -> datetime:
    return datetime.now(UTC)
