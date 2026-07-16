from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PendingSchedulingAction


async def expire_pending_actions(
    session: AsyncSession,
    *,
    now: datetime,
    instance: str,
    phone: str,
) -> int:
    result = await session.execute(
        update(PendingSchedulingAction)
        .where(
            PendingSchedulingAction.instance == instance,
            PendingSchedulingAction.phone == phone,
            PendingSchedulingAction.status == "awaiting_confirmation",
            PendingSchedulingAction.expires_at <= now,
        )
        .values(status="expired", updated_at=now)
    )
    return result.rowcount or 0


async def get_active_pending_action(
    session: AsyncSession,
    *,
    instance: str,
    phone: str,
) -> PendingSchedulingAction | None:
    result = await session.execute(
        select(PendingSchedulingAction)
        .where(
            PendingSchedulingAction.instance == instance,
            PendingSchedulingAction.phone == phone,
            PendingSchedulingAction.status == "awaiting_confirmation",
        )
        .order_by(PendingSchedulingAction.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_pending_action_for_update(
    session: AsyncSession,
    *,
    instance: str,
    phone: str,
) -> PendingSchedulingAction | None:
    statement = (
        select(PendingSchedulingAction)
        .where(
            PendingSchedulingAction.instance == instance,
            PendingSchedulingAction.phone == phone,
            PendingSchedulingAction.status == "awaiting_confirmation",
        )
        .order_by(PendingSchedulingAction.created_at.desc())
        .limit(1)
    )
    if session.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def supersede_active_pending_action(
    session: AsyncSession,
    *,
    instance: str,
    phone: str,
    now: datetime,
) -> int:
    result = await session.execute(
        update(PendingSchedulingAction)
        .where(
            PendingSchedulingAction.instance == instance,
            PendingSchedulingAction.phone == phone,
            PendingSchedulingAction.status == "awaiting_confirmation",
        )
        .values(status="superseded", updated_at=now)
    )
    return result.rowcount or 0


async def create_pending_action(
    session: AsyncSession,
    *,
    instance: str,
    phone: str,
    resource_key: str,
    action_type: str,
    payload: dict[str, Any],
    preview: dict[str, Any],
    confirmation_fingerprint: str,
    prepared_from_inbound_message_id: str,
    expires_at: datetime,
) -> PendingSchedulingAction:
    record = PendingSchedulingAction(
        instance=instance,
        phone=phone,
        resource_key=resource_key,
        action_type=action_type,
        status="awaiting_confirmation",
        payload=payload,
        preview=preview,
        confirmation_fingerprint=confirmation_fingerprint,
        prepared_from_inbound_message_id=prepared_from_inbound_message_id,
        expires_at=expires_at,
    )
    session.add(record)
    await session.flush()
    return record


async def mark_pending_action_completed(
    session: AsyncSession,
    *,
    action: PendingSchedulingAction,
    confirmed_by_inbound_message_id: str,
    appointment_id: str | None,
    now: datetime,
) -> None:
    action.status = "completed"
    action.confirmed_by_inbound_message_id = confirmed_by_inbound_message_id
    action.confirmed_at = now
    action.completed_at = now
    action.result_appointment_id = appointment_id
    action.updated_at = now
    await session.flush()


async def mark_pending_action_rejected(
    session: AsyncSession,
    *,
    action: PendingSchedulingAction,
    now: datetime,
) -> None:
    action.status = "rejected"
    action.updated_at = now
    await session.flush()


async def mark_pending_action_failed(
    session: AsyncSession,
    *,
    action: PendingSchedulingAction,
    error_message: str,
    now: datetime,
    max_error_length: int,
) -> None:
    action.status = "failed"
    action.last_error = error_message[:max_error_length]
    action.updated_at = now
    await session.flush()
