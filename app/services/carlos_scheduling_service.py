import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.openai_client import OpenAIResponsesClient
from app.core.config import Settings
from app.database.models import InboundMessage
from app.domain.clock import Clock, SystemClock
from app.domain.scheduling import get_timezone, validate_phone
from app.exceptions.handlers import PermanentMessageHandlingError
from app.exceptions.openai import OpenAIInvalidResponseError, OpenAITemporaryError
from app.exceptions.scheduling import InvalidPhoneError
from app.prompts.carlos_scheduling import CARLOS_SCHEDULING_SYSTEM_PROMPT
from app.repositories.conversation_history_repository import get_recent_conversation
from app.schemas.conversation import ConversationMessage
from app.services.carlos_response_service import normalize_carlos_reply
from app.services.outbound_safety import secure_outbound_text
from app.services.outbound_safety import OUTSIDE_WINDOW_REPLY
from app.tools.scheduling_definitions import get_scheduling_tool_definitions
from app.tools.scheduling_executor import SchedulingToolExecutor

logger = logging.getLogger(__name__)


class CarlosSchedulingService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        openai_client: OpenAIResponsesClient,
        tool_executor: SchedulingToolExecutor,
        settings: Settings,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._openai_client = openai_client
        self._tool_executor = tool_executor
        self._settings = settings
        self._clock = clock or SystemClock()

    async def generate_reply(self, message: InboundMessage) -> str:
        try:
            validate_phone(message.phone or "")
        except InvalidPhoneError as error:
            raise PermanentMessageHandlingError(
                "Inbound message does not have a valid phone."
            ) from error
        current_text = (message.text or "").strip()
        if not current_text:
            raise PermanentMessageHandlingError("Inbound text message is empty.")

        async with self._session_factory() as session:
            history = await get_recent_conversation(
                session,
                instance=message.instance,
                phone=message.phone or "",
                current_inbound_message_id=message.id,
                limit=self._settings.openai_history_limit,
            )

        input_items: list[object] = [
            *_conversation_to_input(history),
            {
                "role": "user",
                "content": current_text,
            },
        ]
        instructions = self._build_instructions()
        tools = get_scheduling_tool_definitions()

        for round_index in range(self._settings.openai_max_tool_rounds + 1):
            turn = await self._openai_client.create_tool_turn(
                instructions=instructions,
                input_items=input_items,
                tools=tools,
            )
            if len(turn.tool_calls) > 1:
                raise OpenAITemporaryError("OpenAI returned multiple tool calls.")
            if not turn.tool_calls:
                if not turn.output_text:
                    raise OpenAIInvalidResponseError("OpenAI returned an empty response.")
                local_today = self._clock.now_utc().astimezone(
                    get_timezone(self._settings.barbershop_timezone)
                ).date()
                return normalize_carlos_reply(
                    secure_outbound_text(
                        turn.output_text,
                        local_today=local_today,
                        max_days_ahead=self._settings.scheduling_max_days_ahead,
                    ),
                    max_characters=self._settings.openai_max_reply_characters,
                )
            if round_index >= self._settings.openai_max_tool_rounds:
                raise OpenAITemporaryError("OpenAI tool execution limit reached.")

            tool_call = turn.tool_calls[0]
            logger.info(
                "Executing Carlos scheduling tool: inbound_record_id=%s tool_name=%s round=%s",
                message.id,
                tool_call.name,
                round_index + 1,
            )
            tool_result = await self._tool_executor.execute(
                tool_name=tool_call.name,
                arguments_json=tool_call.arguments,
                message=message,
            )
            if (
                not tool_result.ok
                and tool_result.error is not None
                and tool_result.error.code == "outside_booking_window"
            ):
                return OUTSIDE_WINDOW_REPLY
            input_items = [
                *input_items,
                *turn.response_output_items,
                {
                    "type": "function_call_output",
                    "call_id": tool_call.call_id,
                    "output": tool_result.model_dump_json(),
                },
            ]

        raise OpenAITemporaryError("OpenAI tool execution limit reached.")

    async def close(self) -> None:
        await self._openai_client.close()

    def _build_instructions(self) -> str:
        now_local = self._clock.now_utc().astimezone(
            get_timezone(self._settings.barbershop_timezone)
        )
        context = (
            f"Data local atual da barbearia: {now_local.date().isoformat()}\n"
            f"Horário local atual: {now_local.strftime('%H:%M')}\n"
            f"Timezone: {self._settings.barbershop_timezone}"
        )
        return f"{CARLOS_SCHEDULING_SYSTEM_PROMPT}\n\n{context}"


def _conversation_to_input(messages: list[ConversationMessage]) -> list[dict[str, str]]:
    return [
        {
            "role": message.role,
            "content": message.content,
        }
        for message in messages
    ]
