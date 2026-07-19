import logging
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.database.models import InboundMessage
from app.exceptions.handlers import PermanentMessageHandlingError
from app.exceptions.openai import OpenAIInvalidResponseError
from app.prompts.carlos import CARLOS_SYSTEM_PROMPT
from app.repositories.conversation_history_repository import get_recent_conversation
from app.schemas.conversation import ConversationMessage

logger = logging.getLogger(__name__)


class TextGenerationClient(Protocol):
    async def generate_text(
        self, *, instructions: str, messages: list[ConversationMessage]
    ) -> object: ...

    async def close(self) -> None: ...


class CarlosResponseService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        openai_client: TextGenerationClient,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._openai_client = openai_client
        self._settings = settings

    async def generate_reply(self, message: InboundMessage) -> str:
        if not message.phone:
            raise PermanentMessageHandlingError("Inbound message does not have a phone.")
        current_text = (message.text or "").strip()
        if not current_text:
            raise PermanentMessageHandlingError("Inbound text message is empty.")

        async with self._session_factory() as session:
            history = await get_recent_conversation(
                session,
                instance=message.instance,
                phone=message.phone,
                current_inbound_message_id=message.id,
                limit=self._settings.openai_history_limit,
            )

        conversation = [
            *history,
            ConversationMessage(
                role="user",
                content=current_text,
                created_at=message.created_at,
            ),
        ]
        logger.info(
            "Generating Carlos reply: inbound_record_id=%s model=%s history_count=%s",
            message.id,
            (
                self._settings.ollama_model
                if self._settings.llm_provider == "ollama_cloud"
                else self._settings.openai_model
            ),
            len(history),
        )
        result = await self._openai_client.generate_text(
            instructions=CARLOS_SYSTEM_PROMPT,
            messages=conversation,
        )

        return normalize_carlos_reply(
            result.text,
            max_characters=self._settings.openai_max_reply_characters,
        )

    async def close(self) -> None:
        await self._openai_client.close()


def normalize_carlos_reply(text: str, *, max_characters: int) -> str:
    normalized = text.replace("\x00", "").strip()
    if not normalized:
        raise OpenAIInvalidResponseError("OpenAI returned an empty response.")

    if len(normalized) <= max_characters:
        return normalized

    limited = normalized[:max_characters]
    for separator in ("\n", ". ", "! ", "? "):
        index = limited.rfind(separator)
        if index > 0:
            end = index + (1 if separator == "\n" else 1)
            candidate = limited[:end].strip()
            if candidate:
                return candidate

    return limited.strip()
