from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import InboundMedia
from app.schemas.normalized_message import NormalizedMedia


async def register_inbound_media(
    session: AsyncSession,
    *,
    inbound_message_id: str,
    media: NormalizedMedia,
) -> InboundMedia:
    existing = await get_inbound_media_by_inbound_id(
        session,
        inbound_message_id=inbound_message_id,
    )
    if existing is not None:
        return existing
    record = InboundMedia(
        inbound_message_id=inbound_message_id,
        media_type=media.media_type,
        mimetype=media.mimetype,
        file_name=media.file_name,
        file_size_bytes=media.file_size_bytes,
        status="pending",
        source="inline_base64" if media.inline_base64 else "unknown",
        media_locator=media.locator,
        inline_base64=media.inline_base64,
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await get_inbound_media_by_inbound_id(
            session,
            inbound_message_id=inbound_message_id,
        )
        if existing is None:
            raise
        return existing
    await session.refresh(record)
    return record


async def get_inbound_media_by_inbound_id(
    session: AsyncSession,
    *,
    inbound_message_id: str,
) -> InboundMedia | None:
    result = await session.execute(
        select(InboundMedia).where(InboundMedia.inbound_message_id == inbound_message_id)
    )
    return result.scalar_one_or_none()


async def claim_inbound_media(
    session: AsyncSession,
    *,
    inbound_message_id: str,
    now: datetime,
) -> InboundMedia | None:
    media = await get_inbound_media_by_inbound_id(session, inbound_message_id=inbound_message_id)
    if media is None:
        return None
    if media.status == "completed":
        return media
    if media.status == "processing":
        return media
    if media.status != "pending":
        return media
    media.status = "processing"
    media.locked_at = now
    media.attempts += 1
    media.updated_at = now
    await session.commit()
    await session.refresh(media)
    return media


async def mark_media_completed(
    session: AsyncSession,
    *,
    media: InboundMedia,
    extracted_text: str,
    content_sha256: str,
    size_bytes: int,
    provider: str,
    model: str,
    now: datetime,
    analysis_kind: str | None = None,
    analysis_data: dict[str, object] | None = None,
) -> None:
    media.status = "completed"
    media.extracted_text = extracted_text
    media.content_sha256 = content_sha256
    media.file_size_bytes = size_bytes
    media.provider = provider
    media.model = model
    media.analysis_kind = analysis_kind
    media.analysis_data = analysis_data
    media.inline_base64 = None
    media.locked_at = None
    media.next_attempt_at = None
    media.processed_at = now
    media.updated_at = now
    media.last_error = None
    await session.commit()


async def mark_media_failed(
    session: AsyncSession,
    *,
    media: InboundMedia,
    error_message: str,
    now: datetime,
) -> None:
    media.status = "failed"
    media.inline_base64 = None
    media.locked_at = None
    media.last_error = error_message[:500]
    media.updated_at = now
    await session.commit()


async def mark_media_retry(
    session: AsyncSession,
    *,
    media: InboundMedia,
    error_message: str,
    now: datetime,
    retry_delay_seconds: int,
) -> None:
    media.status = "pending"
    media.locked_at = None
    media.next_attempt_at = now + timedelta(seconds=retry_delay_seconds)
    media.last_error = error_message[:500]
    media.updated_at = now
    await session.commit()
