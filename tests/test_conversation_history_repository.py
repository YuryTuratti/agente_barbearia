from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import InboundMessage, OutboundMessage
from app.repositories.conversation_history_repository import get_recent_conversation


@pytest.mark.anyio
async def test_recent_conversation_filters_orders_and_limits(
    db_session: AsyncSession,
) -> None:
    base = datetime.now(UTC)
    current = await _inbound(db_session, "current", created_at=base)
    await _inbound(db_session, "old", text="ola", created_at=base - timedelta(minutes=6))
    await _outbound(db_session, "sent", text="oi", created_at=base - timedelta(minutes=5))
    await _inbound(db_session, "other-phone", phone="5534888888888")
    await _inbound(db_session, "other-instance", instance="outra")
    await _inbound(db_session, "pending", status="pending")
    await _inbound(db_session, "processing", status="processing")
    await _inbound(db_session, "failed", status="failed")
    await _inbound(db_session, "blank", text=" ")
    await _outbound(db_session, "out-pending", status="pending")
    await _outbound(db_session, "out-sending", status="sending")
    await _outbound(db_session, "out-failed", status="failed")

    history = await get_recent_conversation(
        db_session,
        instance="turatti-barbe",
        phone="5534999999999",
        current_inbound_message_id=current.id,
        limit=2,
    )

    assert [(item.role, item.content) for item in history] == [
        ("user", "ola"),
        ("assistant", "oi"),
    ]


@pytest.mark.anyio
async def test_repository_does_not_modify_orm_objects(db_session: AsyncSession) -> None:
    record = await _inbound(db_session, "one", text="ola")
    original_status = record.status

    await get_recent_conversation(
        db_session,
        instance="turatti-barbe",
        phone="5534999999999",
        current_inbound_message_id="current",
        limit=12,
    )
    refreshed = (
        await db_session.execute(select(InboundMessage).where(InboundMessage.id == record.id))
    ).scalar_one()

    assert refreshed.status == original_status


async def _inbound(
    session: AsyncSession,
    message_id: str,
    *,
    instance: str = "turatti-barbe",
    phone: str = "5534999999999",
    status: str = "completed",
    text: str = "ok",
    created_at: datetime | None = None,
) -> InboundMessage:
    record = InboundMessage(
        instance=instance,
        message_id=message_id,
        remote_jid=f"{phone}@s.whatsapp.net",
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


async def _outbound(
    session: AsyncSession,
    deduplication_key: str,
    *,
    status: str = "sent",
    text: str = "ok",
    created_at: datetime | None = None,
) -> OutboundMessage:
    record = OutboundMessage(
        deduplication_key=deduplication_key,
        instance="turatti-barbe",
        recipient="5534999999999",
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
