import logging

from app.database.models import InboundMessage

logger = logging.getLogger(__name__)


class LoggingMessageHandler:
    """Temporary handler that only logs safe metadata and performs no action."""

    async def handle(self, message: InboundMessage) -> None:
        logger.info(
            "Temporary message handler processed metadata: record_id=%s "
            "message_id=%s instance=%s message_type=%s",
            message.id,
            message.message_id,
            message.instance,
            message.message_type,
        )
