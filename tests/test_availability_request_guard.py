from datetime import UTC, date, datetime

import pytest

from app.database.models import CarlosConversationState, InboundMessage
from app.schemas.openai_response import OpenAIResponseTurn, OpenAIToolCall
from app.schemas.tooling import ToolExecutionResult
from app.services.availability_request_guard import (
    AVAILABILITY_FAILURE_REPLY,
    validate_availability_request,
)
from app.services.carlos_scheduling_service import CarlosSchedulingService
from tests.scheduling_helpers import FakeClock, scheduling_settings


TODAY = date(2026, 7, 10)
BASE = {
    "requested_service": "Corte Social",
    "requested_professional": "Lucas",
    "resource_key": "main",
    "requested_date": "2026-07-11",
    "requested_period": "morning",
}


@pytest.mark.parametrize(
    ("changes", "reason", "reply"),
    [
        ({"requested_date": "2033-07-30"}, "date_too_far", "próximos 90 dias"),
        ({"requested_date": "2026-07-09"}, "date_in_past", "Essa data já passou"),
        ({"requested_service": None}, "missing_service", "Qual serviço"),
        ({"requested_professional": None}, "missing_professional", "Lucas ou Daniel"),
        ({"requested_date": None}, "missing_date", "Para qual dia"),
        ({"requested_period": None}, "missing_period", "manhã ou à tarde"),
    ],
)
def test_guard_rejects_invalid_or_incomplete_state(changes, reason, reply) -> None:
    decision = validate_availability_request({**BASE, **changes}, today=TODAY)
    assert decision.can_check is False
    assert decision.reason == reason
    assert reply in (decision.safe_reply or "")


class ToolClient:
    def __init__(self, turns):
        self.turns = list(turns)

    async def create_tool_turn(self, **kwargs):
        return self.turns.pop(0)

    async def close(self):
        pass


class AvailabilityExecutor:
    def __init__(self, error=None, slots=None):
        self.calls = []
        self.error = error
        self.slots = slots

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return ToolExecutionResult(
            ok=True, tool_name=kwargs["tool_name"],
            data={"slots": self.slots if self.slots is not None else [
                {"start_time": "09:00", "end_time": "09:30", "barber": "Lucas"},
                {"start_time": "10:30", "end_time": "11:00", "barber": "Lucas"},
            ]},
        )


def _availability_turn():
    return OpenAIResponseTurn(
        output_text=None,
        tool_calls=[OpenAIToolCall(
            call_id="availability", name="list_available_slots",
            arguments='{"local_date":"2026-07-11","service_ids":["svc"],"barber":"lucas"}',
        )],
        response_output_items=[],
    )


async def _seed_state(session_maker):
    async with session_maker() as session:
        session.add(CarlosConversationState(
            instance="shop", phone="5534999999999",
            state={**BASE, "scheduling_intent": True},
        ))
        await session.commit()


def _message(text="corte com Lucas amanhã de manhã"):
    return InboundMessage(
        id="guard-message", instance="shop", message_id="guard-message",
        phone="5534999999999", message_type="text", text=text,
        created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
    )


def _service(session_maker, client, executor):
    return CarlosSchedulingService(
        session_factory=session_maker, openai_client=client,
        tool_executor=executor, settings=scheduling_settings(),
        clock=FakeClock(datetime(2026, 7, 10, 12, 0, tzinfo=UTC)),
    )


@pytest.mark.anyio
async def test_valid_request_executes_tool_and_returns_slots_directly(session_maker):
    await _seed_state(session_maker)
    executor = AvailabilityExecutor()
    reply = await _service(
        session_maker, ToolClient([_availability_turn()]), executor
    ).generate_reply(_message())
    assert len(executor.calls) == 1
    assert "09:00" in reply and "10:30" in reply
    assert "vou verificar" not in reply.lower()


@pytest.mark.anyio
async def test_tool_exception_returns_friendly_reply(session_maker):
    await _seed_state(session_maker)
    executor = AvailabilityExecutor(TimeoutError("timeout"))
    reply = await _service(
        session_maker, ToolClient([_availability_turn()]), executor
    ).generate_reply(_message())
    assert reply == AVAILABILITY_FAILURE_REPLY
    assert len(executor.calls) == 1


@pytest.mark.anyio
async def test_no_slots_returns_barber_specific_alternative(session_maker):
    await _seed_state(session_maker)
    executor = AvailabilityExecutor(slots=[])
    reply = await _service(
        session_maker, ToolClient([_availability_turn()]), executor
    ).generate_reply(_message())
    assert "Não encontrei horário com Lucas" in reply
    assert "Daniel" in reply


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("quanto é o corte?", "O Corte Social custa R$ 30,00."),
        ("onde fica?", "Ficamos no endereço cadastrado da O Original Barbershop."),
    ],
)
async def test_information_questions_do_not_call_availability(
    session_maker, question, answer
):
    client = ToolClient([
        OpenAIResponseTurn(output_text=answer, tool_calls=[], response_output_items=[])
    ])
    executor = AvailabilityExecutor()
    reply = await _service(session_maker, client, executor).generate_reply(
        _message(question)
    )
    assert reply == answer
    assert executor.calls == []
