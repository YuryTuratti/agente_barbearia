from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import InboundMessage, OutboundMessage
from app.repositories.outbound_message_repository import (
    OutboundMessageStateError,
    claim_pending_outbound_messages,
    enqueue_text_message,
    mark_outbound_message_permanent_error,
    mark_outbound_message_sent,
    mark_outbound_message_temporary_error,
    release_stale_outbound_messages,
)


@pytest.mark.anyio
async def test_enqueue_creates_pending_message(db_session: AsyncSession) -> None:
    result = await enqueue_text_message(
        db_session,
        inbound_message_id=None,
        deduplication_key="reply:1",
        instance="turatti-barbe",
        recipient="5534999999999",
        text=" ok ",
    )
    record = await _get_outbound(db_session, result.record_id)

    assert result.created is True
    assert result.duplicate is False
    assert record.status == "pending"
    assert record.attempts == 0
    assert record.text == "ok"
    assert isinstance(record.recipient, str)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("text", " "),
        ("recipient", "5534abc"),
        ("instance", " "),
        ("deduplication_key", " "),
    ],
)
async def test_enqueue_rejects_invalid_fields(
    db_session: AsyncSession,
    field: str,
    value: str,
) -> None:
    payload = {
        "inbound_message_id": None,
        "deduplication_key": "reply:1",
        "instance": "turatti-barbe",
        "recipient": "5534999999999",
        "text": "ok",
    }
    payload[field] = value

    with pytest.raises(ValueError):
        await enqueue_text_message(db_session, **payload)


@pytest.mark.anyio
async def test_duplicate_key_returns_existing_id_and_session_remains_usable(
    db_session: AsyncSession,
) -> None:
    first = await enqueue_text_message(
        db_session,
        inbound_message_id=None,
        deduplication_key="reply:1",
        instance="turatti-barbe",
        recipient="5534999999999",
        text="ok",
    )
    second = await enqueue_text_message(
        db_session,
        inbound_message_id=None,
        deduplication_key="reply:1",
        instance="turatti-barbe",
        recipient="5534999999999",
        text="ok",
    )
    count = await _count_outbound(db_session)
    third = await enqueue_text_message(
        db_session,
        inbound_message_id=None,
        deduplication_key="reply:2",
        instance="turatti-barbe",
        recipient="5534999999999",
        text="ok",
    )

    assert first.created is True
    assert second.created is False
    assert second.duplicate is True
    assert second.record_id == first.record_id
    assert count == 1
    assert third.created is True


@pytest.mark.anyio
async def test_message_can_reference_inbound_and_fk_is_configured(
    db_session: AsyncSession,
) -> None:
    inbound = await _insert_inbound(db_session)
    result = await enqueue_text_message(
        db_session,
        inbound_message_id=inbound.id,
        deduplication_key=f"inbound-reply:{inbound.id}",
        instance=inbound.instance,
        recipient=inbound.phone or "",
        text="ok",
    )
    record = await _get_outbound(db_session, result.record_id)

    assert record.inbound_message_id == inbound.id
    fk = next(
        fk
        for fk in inspect(OutboundMessage).local_table.foreign_keys
        if fk.parent.name == "inbound_message_id"
    )
    assert fk.ondelete == "SET NULL"


@pytest.mark.anyio
async def test_claim_and_status_transitions(db_session: AsyncSession) -> None:
    pending = await _insert_outbound(db_session)
    await _insert_outbound(
        db_session,
        deduplication_key="future",
        next_attempt_at=_now() + timedelta(minutes=5),
    )
    await _insert_outbound(db_session, deduplication_key="sent", status="sent")
    await _insert_outbound(db_session, deduplication_key="failed", status="failed")
    await _insert_outbound(db_session, deduplication_key="sending", status="sending")

    claimed = await claim_pending_outbound_messages(db_session, limit=10, now=_now())
    updated = await _get_outbound(db_session, pending.id)

    assert [message.id for message in claimed] == [pending.id]
    assert updated.status == "sending"
    assert updated.attempts == 1
    assert updated.locked_at is not None

    sent_at = _now()
    await mark_outbound_message_sent(
        db_session,
        pending.id,
        sent_at=sent_at,
        external_message_id="external-1",
    )
    sent = await _get_outbound(db_session, pending.id)
    assert sent.status == "sent"
    assert sent.sent_at is not None
    assert sent.external_message_id == "external-1"
    assert sent.last_error is None
    assert sent.locked_at is None


@pytest.mark.anyio
async def test_temporary_permanent_and_stale_failures(
    db_session: AsyncSession,
) -> None:
    temporary = await _insert_outbound(
        db_session,
        deduplication_key="temporary",
        status="sending",
        attempts=1,
        locked_at=_now(),
    )
    await mark_outbound_message_temporary_error(
        db_session,
        temporary.id,
        error_message="timeout",
        failed_at=_now(),
        max_attempts=3,
        retry_delay_seconds=30,
    )
    temporary = await _get_outbound(db_session, temporary.id)
    assert temporary.status == "pending"
    assert temporary.next_attempt_at is not None

    at_limit = await _insert_outbound(
        db_session,
        deduplication_key="limit",
        status="sending",
        attempts=3,
        locked_at=_now(),
    )
    await mark_outbound_message_temporary_error(
        db_session,
        at_limit.id,
        error_message="timeout",
        failed_at=_now(),
        max_attempts=3,
        retry_delay_seconds=30,
    )
    assert (await _get_outbound(db_session, at_limit.id)).status == "failed"

    permanent = await _insert_outbound(
        db_session,
        deduplication_key="permanent",
        status="sending",
        attempts=1,
        locked_at=_now(),
    )
    await mark_outbound_message_permanent_error(
        db_session,
        permanent.id,
        error_message="HTTP 401",
        failed_at=_now(),
    )
    assert (await _get_outbound(db_session, permanent.id)).status == "failed"

    stale = await _insert_outbound(
        db_session,
        deduplication_key="stale",
        status="sending",
        attempts=1,
        locked_at=_now() - timedelta(minutes=10),
    )
    fresh = await _insert_outbound(
        db_session,
        deduplication_key="fresh",
        status="sending",
        attempts=1,
        locked_at=_now(),
    )
    released = await release_stale_outbound_messages(
        db_session,
        stale_before=_now() - timedelta(minutes=5),
        now=_now(),
        max_attempts=3,
    )
    assert released == 1
    assert (await _get_outbound(db_session, stale.id)).status == "pending"
    assert (await _get_outbound(db_session, fresh.id)).status == "sending"


@pytest.mark.anyio
async def test_mark_sent_requires_sending(db_session: AsyncSession) -> None:
    record = await _insert_outbound(db_session)

    with pytest.raises(OutboundMessageStateError):
        await mark_outbound_message_sent(
            db_session,
            record.id,
            sent_at=_now(),
            external_message_id=None,
        )


async def _insert_inbound(session: AsyncSession) -> InboundMessage:
    record = InboundMessage(
        instance="turatti-barbe",
        message_id="ABC123",
        remote_jid="5534999999999@s.whatsapp.net",
        phone="5534999999999",
        message_type="text",
        status="pending",
        attempts=0,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def _insert_outbound(
    session: AsyncSession,
    *,
    deduplication_key: str = "reply:1",
    status: str = "pending",
    attempts: int = 0,
    locked_at: datetime | None = None,
    next_attempt_at: datetime | None = None,
) -> OutboundMessage:
    record = OutboundMessage(
        deduplication_key=deduplication_key,
        instance="turatti-barbe",
        recipient="5534999999999",
        message_type="text",
        text="ok",
        status=status,
        attempts=attempts,
        locked_at=locked_at,
        next_attempt_at=next_attempt_at,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def _get_outbound(session: AsyncSession, record_id: str | None) -> OutboundMessage:
    result = await session.execute(
        select(OutboundMessage).where(OutboundMessage.id == record_id)
    )
    return result.scalar_one()


async def _count_outbound(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(OutboundMessage))
    return result.scalar_one()


def _now() -> datetime:
    return datetime.now(UTC)
