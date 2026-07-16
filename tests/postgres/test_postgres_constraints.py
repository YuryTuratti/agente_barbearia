import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


async def test_exclusion_constraint_blocks_overlapping_scheduled_appointments(
    pg_session: AsyncSession,
) -> None:
    customer_id = await _seed_customer(pg_session)
    start_at = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

    await _insert_appointment(
        pg_session,
        customer_id=customer_id,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )

    with pytest.raises(IntegrityError):
        await _insert_appointment(
            pg_session,
            customer_id=customer_id,
            start_at=start_at + timedelta(minutes=10),
            end_at=start_at + timedelta(minutes=40),
        )


async def test_adjacent_scheduled_appointments_are_allowed(
    pg_session: AsyncSession,
) -> None:
    customer_id = await _seed_customer(pg_session)
    start_at = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

    await _insert_appointment(
        pg_session,
        customer_id=customer_id,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _insert_appointment(
        pg_session,
        customer_id=customer_id,
        start_at=start_at + timedelta(minutes=30),
        end_at=start_at + timedelta(minutes=60),
    )


async def test_partial_unique_pending_action_blocks_second_active_action(
    pg_session: AsyncSession,
) -> None:
    inbound_id = await _seed_inbound(pg_session)
    await _insert_pending_action(pg_session, inbound_id=inbound_id)

    with pytest.raises(IntegrityError):
        await _insert_pending_action(pg_session, inbound_id=inbound_id)


async def test_partial_unique_pending_action_allows_completed_action(
    pg_session: AsyncSession,
) -> None:
    inbound_id = await _seed_inbound(pg_session)
    await _insert_pending_action(pg_session, inbound_id=inbound_id, status="completed")
    await _insert_pending_action(pg_session, inbound_id=inbound_id)


async def test_inbound_and_outbound_deduplication_constraints(
    pg_session: AsyncSession,
) -> None:
    inbound_id = await _seed_inbound(pg_session, message_id="duplicate-id")

    with pytest.raises(IntegrityError):
        await _seed_inbound(pg_session, message_id="duplicate-id")

    await pg_session.rollback()
    await pg_session.execute(
        text(
            """
            INSERT INTO outbound_messages (
                id, inbound_message_id, deduplication_key, instance, recipient,
                message_type, text, status, attempts
            )
            VALUES (
                :id, :inbound_id, 'dedup-key', 'test-instance', '5500000000000',
                'text', 'reply', 'pending', 0
            )
            """
        ),
        {"id": str(uuid4()), "inbound_id": inbound_id},
    )
    await pg_session.commit()

    with pytest.raises(IntegrityError):
        await pg_session.execute(
            text(
                """
                INSERT INTO outbound_messages (
                    id, inbound_message_id, deduplication_key, instance, recipient,
                    message_type, text, status, attempts
                )
                VALUES (
                    :id, :inbound_id, 'dedup-key', 'test-instance', '5500000000000',
                    'text', 'reply', 'pending', 0
                )
                """
            ),
            {"id": str(uuid4()), "inbound_id": inbound_id},
        )
        await pg_session.commit()


async def test_json_and_timezone_timestamps_round_trip(pg_session: AsyncSession) -> None:
    inbound_id = await _seed_inbound(pg_session)
    await pg_session.execute(
        text(
            """
            INSERT INTO inbound_media (
                id, inbound_message_id, media_type, status, attempts, source,
                media_locator, analysis_kind, analysis_data
            )
            VALUES (
                :id, :inbound_id, 'image', 'completed', 0, 'evolution_api',
                CAST(:media_locator AS json), 'haircut_reference', CAST(:analysis_data AS json)
            )
            """
        ),
        {
            "id": str(uuid4()),
            "inbound_id": inbound_id,
            "media_locator": json.dumps({"kind": "test"}),
            "analysis_data": json.dumps({"features": ["fade"], "confidence": 0.9}),
        },
    )
    await pg_session.commit()

    result = await pg_session.execute(
        text(
            """
            SELECT analysis_data, created_at
            FROM inbound_media
            WHERE inbound_message_id = :inbound_id
            """
        ),
        {"inbound_id": inbound_id},
    )
    analysis_data, created_at = result.one()
    assert analysis_data["features"] == ["fade"]
    assert created_at.tzinfo is not None


async def _seed_customer(session: AsyncSession) -> str:
    customer_id = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO customers (id, instance, phone, name)
            VALUES (:id, 'test-instance', '5500000000000', 'Test Customer')
            """
        ),
        {"id": customer_id},
    )
    await session.commit()
    return customer_id


async def _seed_inbound(
    session: AsyncSession,
    *,
    message_id: str | None = None,
) -> str:
    inbound_id = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO inbound_messages (
                id, instance, message_id, message_type, status, attempts
            )
            VALUES (:id, 'test-instance', :message_id, 'text', 'pending', 0)
            """
        ),
        {"id": inbound_id, "message_id": message_id or str(uuid4())},
    )
    await session.commit()
    return inbound_id


async def _insert_appointment(
    session: AsyncSession,
    *,
    customer_id: str,
    start_at: datetime,
    end_at: datetime,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO appointments (
                id, instance, resource_key, customer_id, confirmation_code,
                idempotency_key, status, start_at, end_at,
                total_duration_minutes, total_price_cents
            )
            VALUES (
                :id, 'test-instance', 'main', :customer_id, :confirmation_code,
                :idempotency_key, 'scheduled', :start_at, :end_at, 30, 5000
            )
            """
        ),
        {
            "id": str(uuid4()),
            "customer_id": customer_id,
            "confirmation_code": str(uuid4()).replace("-", ""),
            "idempotency_key": str(uuid4()),
            "start_at": start_at,
            "end_at": end_at,
        },
    )
    await session.commit()


async def _insert_pending_action(
    session: AsyncSession,
    *,
    inbound_id: str,
    status: str = "awaiting_confirmation",
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO pending_scheduling_actions (
                id, instance, phone, resource_key, action_type, status,
                payload, preview, confirmation_fingerprint,
                prepared_from_inbound_message_id, expires_at
            )
            VALUES (
                :id, 'test-instance', '5500000000000', 'main', 'create', :status,
                CAST(:payload AS json), CAST(:preview AS json), :fingerprint,
                :inbound_id, :expires_at
            )
            """
        ),
        {
            "id": str(uuid4()),
            "status": status,
            "payload": json.dumps({"kind": "create"}),
            "preview": json.dumps({"summary": "test"}),
            "fingerprint": str(uuid4()).replace("-", ""),
            "inbound_id": inbound_id,
            "expires_at": datetime(2026, 7, 6, 13, 0, tzinfo=UTC),
        },
    )
    await session.commit()
