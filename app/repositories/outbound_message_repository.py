from datetime import datetime, timedelta

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import OutboundMessage
from app.schemas.outbound_message import OutboundMessageRegistrationResult
from app.services.outbound_safety import secure_outbound_text
from app.services.carlos_response_service import sanitize_carlos_reply

UNIQUE_CONSTRAINT_NAME = "uq_outbound_messages_deduplication_key"
MAX_STORED_ERROR_LENGTH = 500


class OutboundMessageStateError(RuntimeError):
    """Raised when an outbound message cannot transition from its current state."""


async def enqueue_text_message(
    session: AsyncSession,
    *,
    inbound_message_id: str | None,
    deduplication_key: str,
    instance: str,
    recipient: str,
    text: str,
) -> OutboundMessageRegistrationResult:
    clean_deduplication_key = _require_not_blank(
        deduplication_key,
        "deduplication_key",
    )
    clean_instance = _require_not_blank(instance, "instance")
    clean_recipient = _validate_recipient(recipient)
    clean_text = secure_outbound_text(sanitize_carlos_reply(_require_not_blank(text, "text")))

    record = OutboundMessage(
        inbound_message_id=inbound_message_id,
        deduplication_key=clean_deduplication_key,
        instance=clean_instance,
        recipient=clean_recipient,
        message_type="text",
        text=clean_text,
        status="pending",
        attempts=0,
    )
    session.add(record)

    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        if not _is_duplicate_message_integrity_error(error):
            raise error

        duplicate_id = await _find_duplicate_record_id(
            session=session,
            deduplication_key=clean_deduplication_key,
        )
        if duplicate_id is None:
            raise error

        return OutboundMessageRegistrationResult(
            created=False,
            duplicate=True,
            record_id=duplicate_id,
        )

    await session.refresh(record)

    return OutboundMessageRegistrationResult(
        created=True,
        duplicate=False,
        record_id=record.id,
    )


async def get_outbound_by_deduplication_key(
    session: AsyncSession,
    deduplication_key: str,
) -> OutboundMessage | None:
    result = await session.execute(
        select(OutboundMessage).where(
            OutboundMessage.deduplication_key == deduplication_key
        )
    )

    return result.scalar_one_or_none()


async def claim_pending_outbound_messages(
    session: AsyncSession,
    *,
    limit: int,
    now: datetime,
) -> list[OutboundMessage]:
    statement = _pending_messages_statement(limit=limit, now=now)
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)

    result = await session.execute(statement)
    messages = list(result.scalars().all())

    for message in messages:
        message.status = "sending"
        message.locked_at = now
        message.attempts += 1
        message.updated_at = now

    await session.commit()

    return messages


async def mark_outbound_message_sent(
    session: AsyncSession,
    record_id: str,
    *,
    sent_at: datetime,
    external_message_id: str | None,
) -> None:
    message = await _get_message_by_record_id(session, record_id)
    if message is None or message.status != "sending":
        raise OutboundMessageStateError("Outbound message is not currently sending.")

    message.status = "sent"
    message.sent_at = sent_at
    message.external_message_id = external_message_id
    message.locked_at = None
    message.next_attempt_at = None
    message.last_error = None
    message.updated_at = sent_at

    await session.commit()


async def mark_outbound_message_temporary_error(
    session: AsyncSession,
    record_id: str,
    *,
    error_message: str,
    failed_at: datetime,
    max_attempts: int,
    retry_delay_seconds: int,
) -> None:
    message = await _get_message_by_record_id(session, record_id)
    if message is None or message.status != "sending":
        raise OutboundMessageStateError("Outbound message is not currently sending.")

    message.locked_at = None
    message.last_error = sanitize_error_message(error_message)
    message.updated_at = failed_at

    if message.attempts < max_attempts:
        message.status = "pending"
        message.next_attempt_at = failed_at + timedelta(seconds=retry_delay_seconds)
    else:
        message.status = "failed"
        message.next_attempt_at = None

    await session.commit()


async def mark_outbound_message_permanent_error(
    session: AsyncSession,
    record_id: str,
    *,
    error_message: str,
    failed_at: datetime,
) -> None:
    message = await _get_message_by_record_id(session, record_id)
    if message is None or message.status != "sending":
        raise OutboundMessageStateError("Outbound message is not currently sending.")

    message.status = "failed"
    message.locked_at = None
    message.next_attempt_at = None
    message.last_error = sanitize_error_message(error_message)
    message.updated_at = failed_at

    await session.commit()


async def release_stale_outbound_messages(
    session: AsyncSession,
    *,
    stale_before: datetime,
    now: datetime,
    max_attempts: int,
) -> int:
    statement = (
        select(OutboundMessage)
        .where(
            OutboundMessage.status == "sending",
            OutboundMessage.locked_at.is_not(None),
            OutboundMessage.locked_at < stale_before,
        )
        .order_by(OutboundMessage.locked_at.asc())
    )
    result = await session.execute(statement)
    messages = list(result.scalars().all())

    for message in messages:
        message.locked_at = None
        message.last_error = "Sending timeout."
        message.updated_at = now

        if message.attempts < max_attempts:
            message.status = "pending"
            message.next_attempt_at = now
        else:
            message.status = "failed"
            message.next_attempt_at = None

    await session.commit()

    return len(messages)


def sanitize_error_message(error_message: str) -> str:
    sanitized = error_message.strip()
    if not sanitized:
        sanitized = "Unexpected sending error."

    return sanitized[:MAX_STORED_ERROR_LENGTH]


async def _find_duplicate_record_id(
    session: AsyncSession,
    deduplication_key: str,
) -> str | None:
    statement = select(OutboundMessage.id).where(
        OutboundMessage.deduplication_key == deduplication_key,
    )
    result = await session.execute(statement)

    return result.scalar_one_or_none()


def _is_duplicate_message_integrity_error(error: IntegrityError) -> bool:
    error_text = str(error)
    if UNIQUE_CONSTRAINT_NAME in error_text:
        return True

    sqlite_unique_message = (
        "UNIQUE constraint failed: outbound_messages.deduplication_key"
    )
    if sqlite_unique_message in error_text:
        return True

    current_error: BaseException | None = error
    while current_error is not None:
        constraint_name = getattr(current_error, "constraint_name", None)
        if constraint_name == UNIQUE_CONSTRAINT_NAME:
            return True
        current_error = current_error.__cause__

    return False


def _pending_messages_statement(
    *,
    limit: int,
    now: datetime,
) -> Select[tuple[OutboundMessage]]:
    return (
        select(OutboundMessage)
        .where(
            OutboundMessage.status == "pending",
            (
                OutboundMessage.next_attempt_at.is_(None)
                | (OutboundMessage.next_attempt_at <= now)
            ),
        )
        .order_by(OutboundMessage.created_at.asc())
        .limit(limit)
    )


async def _get_message_by_record_id(
    session: AsyncSession,
    record_id: str,
) -> OutboundMessage | None:
    result = await session.execute(
        select(OutboundMessage).where(OutboundMessage.id == record_id)
    )

    return result.scalar_one_or_none()


def _require_not_blank(value: str, field_name: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise ValueError(f"{field_name} is required.")

    return clean_value


def _validate_recipient(value: str) -> str:
    clean_value = value.strip()
    if not clean_value or not clean_value.isdigit():
        raise ValueError("recipient must contain only digits.")

    return clean_value
