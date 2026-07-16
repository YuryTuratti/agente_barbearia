from sqlalchemy import func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import InboundMedia, InboundMessage, OutboundMessage
from app.schemas.conversation import ConversationMessage


async def get_recent_conversation(
    session: AsyncSession,
    *,
    instance: str,
    phone: str,
    current_inbound_message_id: str,
    limit: int,
) -> list[ConversationMessage]:
    inbound = (
        select(
            literal("user").label("role"),
            InboundMessage.text.label("content"),
            InboundMessage.created_at.label("created_at"),
        )
        .where(
            InboundMessage.instance == instance,
            InboundMessage.phone == phone,
            InboundMessage.id != current_inbound_message_id,
            InboundMessage.message_type == "text",
            InboundMessage.status == "completed",
            InboundMessage.text.is_not(None),
            func.trim(InboundMessage.text) != "",
        )
    )
    inbound_audio = (
        select(
            literal("user").label("role"),
            InboundMedia.extracted_text.label("content"),
            InboundMessage.created_at.label("created_at"),
        )
        .join(InboundMedia, InboundMedia.inbound_message_id == InboundMessage.id)
        .where(
            InboundMessage.instance == instance,
            InboundMessage.phone == phone,
            InboundMessage.id != current_inbound_message_id,
            InboundMessage.message_type == "audio",
            InboundMessage.status == "completed",
            InboundMedia.status == "completed",
            InboundMedia.extracted_text.is_not(None),
            func.trim(InboundMedia.extracted_text) != "",
        )
    )
    inbound_image = (
        select(
            literal("user").label("role"),
            InboundMedia.extracted_text.label("content"),
            InboundMessage.created_at.label("created_at"),
        )
        .join(InboundMedia, InboundMedia.inbound_message_id == InboundMessage.id)
        .where(
            InboundMessage.instance == instance,
            InboundMessage.phone == phone,
            InboundMessage.id != current_inbound_message_id,
            InboundMessage.message_type == "image",
            InboundMessage.status == "completed",
            InboundMedia.status == "completed",
            InboundMedia.extracted_text.is_not(None),
            func.trim(InboundMedia.extracted_text) != "",
        )
    )
    outbound = (
        select(
            literal("assistant").label("role"),
            OutboundMessage.text.label("content"),
            OutboundMessage.created_at.label("created_at"),
        )
        .where(
            OutboundMessage.instance == instance,
            OutboundMessage.recipient == phone,
            OutboundMessage.message_type == "text",
            OutboundMessage.status == "sent",
            func.trim(OutboundMessage.text) != "",
        )
    )
    combined = union_all(inbound, inbound_audio, inbound_image, outbound).subquery()
    statement = (
        select(combined.c.role, combined.c.content, combined.c.created_at)
        .order_by(combined.c.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(statement)
    rows = list(result.all())

    return [
        ConversationMessage(
            role=row.role,
            content=row.content,
            created_at=row.created_at,
        )
        for row in reversed(rows)
        if row.content.strip()
    ]
