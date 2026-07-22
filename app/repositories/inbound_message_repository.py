from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import InboundMessage
from app.schemas.inbound_message import InboundMessageRegistrationResult
from app.schemas.normalized_message import NormalizedMessage

UNIQUE_CONSTRAINT_NAME = "uq_inbound_messages_instance_message_id"
MAX_STORED_ERROR_LENGTH = 500


class InboundMessageStateError(RuntimeError):
    """Raised when an inbound message cannot transition from its current state."""


async def register_message(
    session: AsyncSession,
    message: NormalizedMessage,
    buffer_seconds: int = 0,
) -> InboundMessageRegistrationResult:
    """Persist a processable inbound message and treat unique duplicates safely."""
    if not message.processable:
        raise ValueError("Only processable messages can be registered.")
    if message.message_id is None:
        raise ValueError("A message_id is required to register an inbound message.")

    if buffer_seconds < 0:
        raise ValueError("buffer_seconds must be greater than or equal to zero.")
    process_after_at = datetime.now(UTC) + timedelta(seconds=buffer_seconds)
    record = InboundMessage(
        instance=message.instance or "",
        message_id=message.message_id,
        event=message.event,
        remote_jid=message.remote_jid,
        phone=message.phone,
        sender_name=message.sender_name,
        message_type=message.message_type,
        text=message.text,
        media_mimetype=message.media_mimetype,
        message_timestamp=message.timestamp,
        status="pending",
        attempts=0,
        process_after_at=process_after_at,
    )

    session.add(record)

    try:
        # Every pending fragment in this conversation receives the same deadline.
        # Thus a new fragment resets the quiet-period clock transactionally.
        if message.phone and hasattr(session, "execute"):
            await session.execute(
                update(InboundMessage)
                .where(
                    InboundMessage.instance == (message.instance or ""),
                    InboundMessage.phone == message.phone,
                    InboundMessage.status == "pending",
                )
                .values(process_after_at=process_after_at)
            )
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        if not _is_duplicate_message_integrity_error(error):
            raise error

        duplicate_id = await _find_duplicate_record_id(
            session=session,
            instance=message.instance or "",
            message_id=message.message_id,
        )
        if duplicate_id is None:
            raise error

        return InboundMessageRegistrationResult(
            created=False,
            duplicate=True,
            record_id=duplicate_id,
        )

    await session.refresh(record)

    return InboundMessageRegistrationResult(
        created=True,
        duplicate=False,
        record_id=record.id,
    )


async def _find_duplicate_record_id(
    session: AsyncSession,
    instance: str,
    message_id: str,
) -> str | None:
    statement = select(InboundMessage.id).where(
        InboundMessage.instance == instance,
        InboundMessage.message_id == message_id,
    )
    result = await session.execute(statement)

    return result.scalar_one_or_none()


def _is_duplicate_message_integrity_error(error: IntegrityError) -> bool:
    error_text = str(error)
    if UNIQUE_CONSTRAINT_NAME in error_text:
        return True

    sqlite_unique_message = (
        "UNIQUE constraint failed: inbound_messages.instance, "
        "inbound_messages.message_id"
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


async def claim_pending_messages(
    session: AsyncSession,
    *,
    limit: int,
    now: datetime,
) -> list[InboundMessage]:
    """Claim pending messages for processing.

    PostgreSQL uses SELECT FOR UPDATE SKIP LOCKED. SQLite does not support the
    same row-locking semantics; tests use the same state transition but cannot
    fully reproduce PostgreSQL multi-worker locking behavior.
    """
    statement = _pending_messages_statement(limit=limit, now=now)
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)

    result = await session.execute(statement)
    messages = list(result.scalars().all())

    for message in messages:
        # Older fragments become conversation history and never produce their own
        # reply. The newest fragment is the sole representative handled by the IA.
        if message.phone and message.process_after_at is not None:
            older_result = await session.execute(
                select(InboundMessage).where(
                    InboundMessage.instance == message.instance,
                    InboundMessage.phone == message.phone,
                    InboundMessage.status == "pending",
                    InboundMessage.id != message.id,
                    InboundMessage.created_at <= message.created_at,
                )
            )
            for older in older_result.scalars().all():
                older.status = "completed"
                older.processed_at = now
                older.updated_at = now
        message.status = "processing"
        message.locked_at = now
        message.attempts += 1
        message.updated_at = now

    await session.commit()

    return messages


async def mark_message_completed(
    session: AsyncSession,
    message_id: str,
    *,
    completed_at: datetime,
) -> None:
    message = await _get_message_by_record_id(session, message_id)
    if message is None or message.status != "processing":
        raise InboundMessageStateError("Message is not currently processing.")

    message.status = "completed"
    message.processed_at = completed_at
    message.locked_at = None
    message.last_error = None
    message.next_attempt_at = None
    message.updated_at = completed_at

    await session.commit()


async def mark_message_failed(
    session: AsyncSession,
    message_id: str,
    *,
    error_message: str,
    failed_at: datetime,
    max_attempts: int,
    retry_delay_seconds: int,
) -> None:
    message = await _get_message_by_record_id(session, message_id)
    if message is None or message.status != "processing":
        raise InboundMessageStateError("Message is not currently processing.")

    message.locked_at = None
    message.processed_at = None
    message.last_error = sanitize_error_message(error_message)
    message.updated_at = failed_at

    if message.attempts < max_attempts:
        message.status = "pending"
        message.next_attempt_at = failed_at + timedelta(seconds=retry_delay_seconds)
    else:
        message.status = "failed"
        message.next_attempt_at = None

    await session.commit()


async def mark_message_permanently_failed(
    session: AsyncSession,
    message_id: str,
    *,
    error_message: str,
    failed_at: datetime,
) -> None:
    message = await _get_message_by_record_id(session, message_id)
    if message is None or message.status != "processing":
        raise InboundMessageStateError("Message is not currently processing.")

    message.status = "failed"
    message.locked_at = None
    message.processed_at = None
    message.next_attempt_at = None
    message.last_error = sanitize_error_message(error_message)
    message.updated_at = failed_at

    await session.commit()


async def release_stale_processing_messages(
    session: AsyncSession,
    *,
    stale_before: datetime,
    now: datetime,
    max_attempts: int,
) -> int:
    statement = (
        select(InboundMessage)
        .where(
            InboundMessage.status == "processing",
            InboundMessage.locked_at.is_not(None),
            InboundMessage.locked_at < stale_before,
        )
        .order_by(InboundMessage.locked_at.asc())
    )
    result = await session.execute(statement)
    messages = list(result.scalars().all())

    for message in messages:
        message.locked_at = None
        message.processed_at = None
        message.last_error = "Processing timeout."
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
        sanitized = "Unexpected processing error."

    return sanitized[:MAX_STORED_ERROR_LENGTH]


def _pending_messages_statement(*, limit: int, now: datetime) -> Select[tuple[InboundMessage]]:
    newer = InboundMessage.__table__.alias("newer_inbound")
    return (
        select(InboundMessage)
        .where(
            InboundMessage.status == "pending",
            (
                InboundMessage.process_after_at.is_(None)
                | (InboundMessage.process_after_at <= now)
            ),
            (
                InboundMessage.next_attempt_at.is_(None)
                | (InboundMessage.next_attempt_at <= now)
            ),
            ~exists(
                select(1).select_from(newer).where(
                    InboundMessage.process_after_at.is_not(None),
                    newer.c.instance == InboundMessage.instance,
                    newer.c.phone == InboundMessage.phone,
                    newer.c.status == "pending",
                    newer.c.created_at > InboundMessage.created_at,
                )
            ),
        )
        .order_by(InboundMessage.created_at.asc())
        .limit(limit)
    )


async def _get_message_by_record_id(
    session: AsyncSession,
    record_id: str,
) -> InboundMessage | None:
    result = await session.execute(
        select(InboundMessage).where(InboundMessage.id == record_id)
    )

    return result.scalar_one_or_none()
