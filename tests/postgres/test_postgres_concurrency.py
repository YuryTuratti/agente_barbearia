import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import InboundMessage, OutboundMessage, PendingSchedulingAction
from app.repositories.inbound_message_repository import (
    claim_pending_messages,
    mark_message_completed,
    release_stale_processing_messages,
)
from app.repositories.outbound_message_repository import (
    claim_pending_outbound_messages,
    mark_outbound_message_sent,
    release_stale_outbound_messages,
)
from app.repositories.pending_scheduling_action_repository import (
    get_pending_action_for_update,
    mark_pending_action_completed,
)


pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


async def test_inbound_claim_uses_skip_locked(
    pg_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    first_id = await _seed_inbound(pg_session_maker, message_id="lock-first")
    second_id = await _seed_inbound(pg_session_maker, message_id="lock-second")
    now = datetime.now(UTC)

    async with pg_session_maker() as lock_session:
        await lock_session.begin()
        await lock_session.execute(
            select(InboundMessage)
            .where(InboundMessage.id == first_id)
            .with_for_update()
        )

        async with pg_session_maker() as claim_session:
            claimed = await claim_pending_messages(
                claim_session,
                limit=10,
                now=now,
            )

        assert [message.id for message in claimed] == [second_id]
        await lock_session.rollback()


async def test_outbound_claim_uses_skip_locked(
    pg_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    first_id = await _seed_outbound(pg_session_maker, deduplication_key="lock-first")
    second_id = await _seed_outbound(pg_session_maker, deduplication_key="lock-second")
    now = datetime.now(UTC)

    async with pg_session_maker() as lock_session:
        await lock_session.begin()
        await lock_session.execute(
            select(OutboundMessage)
            .where(OutboundMessage.id == first_id)
            .with_for_update()
        )

        async with pg_session_maker() as claim_session:
            claimed = await claim_pending_outbound_messages(
                claim_session,
                limit=10,
                now=now,
            )

        assert [message.id for message in claimed] == [second_id]
        await lock_session.rollback()


async def test_concurrent_inbound_claims_do_not_process_same_message(
    pg_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    expected_ids = {
        await _seed_inbound(pg_session_maker, message_id="parallel-a"),
        await _seed_inbound(pg_session_maker, message_id="parallel-b"),
    }
    now = datetime.now(UTC)

    async def claim_one() -> str:
        async with pg_session_maker() as session:
            claimed = await claim_pending_messages(session, limit=1, now=now)
            return claimed[0].id

    claimed_ids = set(await asyncio.gather(claim_one(), claim_one()))

    assert claimed_ids == expected_ids


async def test_inbound_state_transitions_and_stale_recovery(
    pg_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    message_id = await _seed_inbound(pg_session_maker, message_id="transition")
    now = datetime.now(UTC)

    async with pg_session_maker() as session:
        claimed = await claim_pending_messages(session, limit=1, now=now)
        assert claimed[0].id == message_id
        await mark_message_completed(session, message_id, completed_at=now)

    stale_id = await _seed_inbound(pg_session_maker, message_id="stale")
    async with pg_session_maker() as session:
        claimed = await claim_pending_messages(session, limit=1, now=now)
        assert claimed[0].id == stale_id
        released = await release_stale_processing_messages(
            session,
            stale_before=now + timedelta(seconds=1),
            now=now + timedelta(seconds=2),
            max_attempts=3,
        )
        assert released == 1


async def test_outbound_state_transitions_and_stale_recovery(
    pg_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    outbound_id = await _seed_outbound(pg_session_maker, deduplication_key="transition")
    now = datetime.now(UTC)

    async with pg_session_maker() as session:
        claimed = await claim_pending_outbound_messages(session, limit=1, now=now)
        assert claimed[0].id == outbound_id
        await mark_outbound_message_sent(
            session,
            outbound_id,
            sent_at=now,
            external_message_id="fake-external-id",
        )

    stale_id = await _seed_outbound(pg_session_maker, deduplication_key="stale")
    async with pg_session_maker() as session:
        claimed = await claim_pending_outbound_messages(session, limit=1, now=now)
        assert claimed[0].id == stale_id
        released = await release_stale_outbound_messages(
            session,
            stale_before=now + timedelta(seconds=1),
            now=now + timedelta(seconds=2),
            max_attempts=3,
        )
        assert released == 1


async def test_concurrent_confirmation_locks_single_pending_action(
    pg_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    inbound_id = await _seed_inbound(pg_session_maker, message_id="confirm")
    action_id = await _seed_pending_action(pg_session_maker, inbound_id=inbound_id)
    now = datetime.now(UTC)

    async with pg_session_maker() as first_session:
        await first_session.begin()
        action = await get_pending_action_for_update(
            first_session,
            instance="test-instance",
            phone="5500000000000",
        )
        assert action is not None
        assert action.id == action_id
        await mark_pending_action_completed(
            first_session,
            action=action,
            confirmed_by_inbound_message_id=inbound_id,
            appointment_id=None,
            now=now,
        )
        await first_session.commit()

    async with pg_session_maker() as second_session:
        action = await get_pending_action_for_update(
            second_session,
            instance="test-instance",
            phone="5500000000000",
        )
        assert action is None


async def _seed_inbound(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    message_id: str,
) -> str:
    record_id = str(uuid4())
    async with session_maker() as session:
        await session.execute(
            text(
                """
                INSERT INTO inbound_messages (
                    id, instance, message_id, message_type, status, attempts
                )
                VALUES (:id, 'test-instance', :message_id, 'text', 'pending', 0)
                """
            ),
            {"id": record_id, "message_id": message_id},
        )
        await session.commit()
    return record_id


async def _seed_outbound(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    deduplication_key: str,
) -> str:
    inbound_id = await _seed_inbound(
        session_maker,
        message_id=f"inbound-for-{deduplication_key}",
    )
    record_id = str(uuid4())
    async with session_maker() as session:
        await session.execute(
            text(
                """
                INSERT INTO outbound_messages (
                    id, inbound_message_id, deduplication_key, instance, recipient,
                    message_type, text, status, attempts
                )
                VALUES (
                    :id, :inbound_id, :deduplication_key, 'test-instance',
                    '5500000000000', 'text', 'reply', 'pending', 0
                )
                """
            ),
            {
                "id": record_id,
                "inbound_id": inbound_id,
                "deduplication_key": deduplication_key,
            },
        )
        await session.commit()
    return record_id


async def _seed_pending_action(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    inbound_id: str,
) -> str:
    action_id = str(uuid4())
    async with session_maker() as session:
        await session.execute(
            text(
                """
                INSERT INTO pending_scheduling_actions (
                    id, instance, phone, resource_key, action_type, status,
                    payload, preview, confirmation_fingerprint,
                    prepared_from_inbound_message_id, expires_at
                )
                VALUES (
                    :id, 'test-instance', '5500000000000', 'main', 'create',
                    'awaiting_confirmation', CAST(:payload AS json),
                    CAST(:preview AS json), :fingerprint, :inbound_id, :expires_at
                )
                """
            ),
            {
                "id": action_id,
                "payload": json.dumps({"kind": "create"}),
                "preview": json.dumps({"summary": "test"}),
                "fingerprint": str(uuid4()).replace("-", ""),
                "inbound_id": inbound_id,
                "expires_at": datetime(2026, 7, 6, 13, 0, tzinfo=UTC),
            },
        )
        await session.commit()
    return action_id
