import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import InboundMessage
from app.repositories.outbound_message_repository import enqueue_text_message

logger = logging.getLogger(__name__)

TEST_REPLY_TEXT = (
    "Mensagem recebida com sucesso. O atendimento inteligente ainda esta em "
    "configuracao."
)


class MissingInboundPhoneError(ValueError):
    pass


class TestReplyHandler:
    """Temporary handler that enqueues a fixed technical reply."""

    __test__ = False

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def handle(self, message: InboundMessage) -> None:
        if not message.phone:
            raise MissingInboundPhoneError("Inbound message does not have a phone.")

        async with self._session_factory() as session:
            result = await enqueue_text_message(
                session,
                inbound_message_id=message.id,
                deduplication_key=f"inbound-reply:{message.id}",
                instance=message.instance,
                recipient=message.phone,
                text=TEST_REPLY_TEXT,
            )

        logger.info(
            "Test reply enqueued: inbound_record_id=%s outbound_record_id=%s "
            "instance=%s created=%s duplicate=%s",
            message.id,
            result.record_id,
            message.instance,
            result.created,
            result.duplicate,
        )
