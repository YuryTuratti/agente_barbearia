from typing import Protocol

from app.database.models import InboundMessage


class MessageHandler(Protocol):
    async def handle(self, message: InboundMessage) -> None:
        """Handle a claimed inbound message."""
