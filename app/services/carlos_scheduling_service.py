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
from app.schemas.conversation import ConversationMessage
from app.services.carlos_response_service import normalize_carlos_reply
from app.services.outbound_safety import secure_outbound_text
from app.services.outbound_safety import OUTSIDE_WINDOW_REPLY
from app.services.carlos_conversation_context import prepare_carlos_context, record_carlos_reply
from app.tools.scheduling_definitions import get_scheduling_tool_definitions
from app.tools.scheduling_definitions import LIST_AVAILABLE_SLOTS_TOOL_NAME
from app.tools.scheduling_executor import SchedulingToolExecutor
from app.services.availability_request_guard import (
    AVAILABILITY_FAILURE_REPLY,
    PAST_DATE_REPLY,
    format_available_slots,
    is_informational_request,
    validate_availability_request,
)

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
        if not (message.text or "").strip():
            raise PermanentMessageHandlingError("Inbound text message is empty.")
        now_utc = self._clock.now_utc()
        context = await prepare_carlos_context(
            self._session_factory, message, self._settings, now_utc=now_utc
        )
        history, current_text = context.history, context.current_text
        local_today = now_utc.astimezone(
            get_timezone(self._settings.barbershop_timezone)
        ).date()
        availability_decision = validate_availability_request(
            context.state,
            today=local_today,
            max_days_ahead=self._settings.scheduling_max_days_ahead,
        )
        if (
            context.state.get("scheduling_intent")
            and not is_informational_request(current_text)
            and not availability_decision.can_check
        ):
            return availability_decision.safe_reply or AVAILABILITY_FAILURE_REPLY

        input_items: list[object] = [
            *_conversation_to_input(history),
            {
                "role": "user",
                "content": current_text,
            },
        ]
        instructions = f"{self._build_instructions()}\n\n{context.instructions_context}"
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
                if _only_promises_availability(turn.output_text):
                    return AVAILABILITY_FAILURE_REPLY
                reply = normalize_carlos_reply(
                    secure_outbound_text(
                        turn.output_text,
                        local_today=local_today,
                        max_days_ahead=self._settings.scheduling_max_days_ahead,
                    ),
                    max_characters=self._settings.openai_max_reply_characters,
                )
                await record_carlos_reply(self._session_factory, message, reply)
                return reply
            if round_index >= self._settings.openai_max_tool_rounds:
                raise OpenAITemporaryError("OpenAI tool execution limit reached.")

            tool_call = turn.tool_calls[0]
            if tool_call.name == LIST_AVAILABLE_SLOTS_TOOL_NAME:
                decision = validate_availability_request(
                    context.state,
                    today=local_today,
                    max_days_ahead=self._settings.scheduling_max_days_ahead,
                )
                if not decision.can_check:
                    return decision.safe_reply or AVAILABILITY_FAILURE_REPLY
            logger.info(
                "Executing Carlos scheduling tool: inbound_record_id=%s tool_name=%s round=%s",
                message.id,
                tool_call.name,
                round_index + 1,
            )
            try:
                tool_result = await self._tool_executor.execute(
                    tool_name=tool_call.name,
                    arguments_json=tool_call.arguments,
                    message=message,
                )
            except Exception:
                if tool_call.name == LIST_AVAILABLE_SLOTS_TOOL_NAME:
                    logger.exception("Availability tool failed before returning a result.")
                    return AVAILABILITY_FAILURE_REPLY
                raise
            if tool_call.name == LIST_AVAILABLE_SLOTS_TOOL_NAME:
                if not tool_result.ok:
                    if tool_result.error and tool_result.error.code == "outside_booking_window":
                        return OUTSIDE_WINDOW_REPLY
                    if tool_result.error and tool_result.error.code == "date_in_past":
                        return PAST_DATE_REPLY
                    return AVAILABILITY_FAILURE_REPLY
                slots = list((tool_result.data or {}).get("slots", []))
                return format_available_slots(context.state, slots)
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


def _only_promises_availability(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in (
        "vou verificar", "vou consultar", "já verifico", "ja verifico",
    ))
