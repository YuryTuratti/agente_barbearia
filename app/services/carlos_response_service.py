import logging
import re
from datetime import UTC, date, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.database.models import InboundMessage
from app.exceptions.handlers import PermanentMessageHandlingError
from app.exceptions.openai import OpenAIInvalidResponseError
from app.prompts.carlos import CARLOS_SYSTEM_PROMPT
from app.schemas.conversation import ConversationMessage
from app.domain.scheduling import get_timezone
from app.services.outbound_safety import secure_outbound_text
from app.services.carlos_conversation_context import prepare_carlos_context, record_carlos_reply

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
        if not (message.text or "").strip():
            raise PermanentMessageHandlingError("Inbound text message is empty.")
        context = await prepare_carlos_context(self._session_factory, message, self._settings)
        history, current_text = context.history, context.current_text

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
            instructions=f"{CARLOS_SYSTEM_PROMPT}\n\n{context.instructions_context}",
            messages=conversation,
        )
        if not (result.text or "").replace("\x00", "").strip():
            raise OpenAIInvalidResponseError("OpenAI returned an empty response.")

        local_today = datetime_now_local_date(self._settings)
        reply = normalize_carlos_reply(
            secure_outbound_text(
                result.text,
                local_today=local_today,
                max_days_ahead=self._settings.scheduling_max_days_ahead,
            ),
            max_characters=self._settings.openai_max_reply_characters,
        )
        await record_carlos_reply(self._session_factory, message, reply)
        return reply

    async def close(self) -> None:
        await self._openai_client.close()


def normalize_carlos_reply(text: str, *, max_characters: int) -> str:
    normalized = text.replace("\x00", "").strip()
    if not normalized:
        raise OpenAIInvalidResponseError("OpenAI returned an empty response.")

    normalized = sanitize_carlos_reply(normalized)

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


def sanitize_carlos_reply(text: str) -> str:
    """Remove construcoes proibidas mesmo quando o modelo ignora o prompt."""
    replacements = (
        (r"qual dia da manh[ãa](?:\s+voc[êe]|\s+vc)?(?:\s+pretende)?(?:\s+marcar)?\??", "Beleza, de manhã. Para qual dia?"),
        (r"qual dia da tarde(?:\s+voc[êe]|\s+vc)?(?:\s+pretende)?(?:\s+marcar)?\??", "Beleza, à tarde. Para qual dia?"),
        (r"qual dia da noite(?:\s+voc[êe]|\s+vc)?(?:\s+pretende)?(?:\s+marcar)?\??", "Beleza, à noite. Para qual dia?"),
        (r"(?:que|qual) dia (?:voc[êe]|vc) pretende marcar\??", "Para qual dia você quer marcar?"),
        (r"onde pretende se encontrar\??", "O atendimento é na O Original Barbershop."),
        (r"pretende marcar", "quer marcar"),
    )
    sanitized = text
    for pattern, replacement in replacements:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    return sanitized.strip()


def datetime_now_local_date(settings: Settings) -> date:
    return datetime.now(UTC).astimezone(get_timezone(settings.barbershop_timezone)).date()
