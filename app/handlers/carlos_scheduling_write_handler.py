import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import InboundMessage
from app.exceptions.handlers import PermanentMessageHandlingError
from app.exceptions.openai import OpenAIPermanentError
from app.handlers.carlos_ai_handler import UNSUPPORTED_MEDIA_REPLY
from app.repositories.outbound_message_repository import (
    enqueue_text_message,
    get_outbound_by_deduplication_key,
)
from app.services.carlos_scheduling_write_service import CarlosSchedulingWriteService

logger = logging.getLogger(__name__)


class CarlosSchedulingWriteHandler:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        response_service: CarlosSchedulingWriteService,
    ) -> None:
        self._session_factory = session_factory
        self._response_service = response_service

    async def handle(self, message: InboundMessage) -> None:
        deduplication_key = f"inbound-reply:{message.id}"
        async with self._session_factory() as session:
            existing = await get_outbound_by_deduplication_key(session, deduplication_key)
        if existing is not None:
            return

        if not message.phone:
            raise PermanentMessageHandlingError("Inbound message does not have a phone.")

        if message.message_type != "text" and not (message.text or "").strip():
            reply = UNSUPPORTED_MEDIA_REPLY
        else:
            if not (message.text or "").strip():
                raise PermanentMessageHandlingError("Inbound text message is empty.")
            try:
                reply = await self._response_service.generate_reply(message)
            except OpenAIPermanentError as error:
                raise PermanentMessageHandlingError(str(error)) from error

        async with self._session_factory() as session:
            result = await enqueue_text_message(
                session,
                inbound_message_id=message.id,
                deduplication_key=deduplication_key,
                instance=message.instance,
                recipient=message.phone,
                text=reply,
            )

        logger.info(
            "Carlos scheduling write reply enqueued: inbound_record_id=%s outbound_record_id=%s created=%s duplicate=%s",
            message.id,
            result.record_id,
            result.created,
            result.duplicate,
        )

    async def close(self) -> None:
        await self._response_service.close()
