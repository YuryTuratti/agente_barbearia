from datetime import UTC, datetime

import pytest

from app.database.models import InboundMessage
from app.exceptions.openai import OpenAITemporaryError
from app.schemas.openai_response import OpenAIResponseTurn, OpenAIToolCall
from app.schemas.tooling import ToolExecutionResult
from app.services.carlos_scheduling_service import CarlosSchedulingService
from tests.scheduling_helpers import FakeClock, scheduling_settings


class FakeToolOpenAIClient:
    def __init__(self, turns: list[OpenAIResponseTurn]) -> None:
        self.turns = turns
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def create_tool_turn(self, **kwargs):
        self.calls.append(kwargs)
        return self.turns.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return ToolExecutionResult(
            ok=True,
            tool_name=kwargs["tool_name"],
            data={"services": []},
        )


@pytest.mark.anyio
async def test_carlos_scheduling_service_executes_tool_and_returns_final_text(session_maker):
    openai = FakeToolOpenAIClient(
        [
            OpenAIResponseTurn(
                output_text=None,
                tool_calls=[
                    OpenAIToolCall(call_id="call_1", name="list_services", arguments="{}")
                ],
                response_output_items=[
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "list_services",
                        "arguments": "{}",
                    }
                ],
            ),
            OpenAIResponseTurn(
                output_text="Temos estes serviços cadastrados.",
                tool_calls=[],
                response_output_items=[],
            ),
        ]
    )
    executor = FakeExecutor()

    result = await _service(session_maker, openai, executor).generate_reply(_message())

    assert result == "Temos estes serviços cadastrados."
    assert len(openai.calls) == 2
    assert len(executor.calls) == 1
    assert executor.calls[0]["tool_name"] == "list_services"
    second_input = openai.calls[1]["input_items"]
    assert {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": executor.calls and ToolExecutionResult(
            ok=True,
            tool_name="list_services",
            data={"services": []},
        ).model_dump_json(),
    } in second_input
    assert "5534999999999" not in str(openai.calls)
    assert "turatti" not in str(openai.calls[0]["input_items"])


@pytest.mark.anyio
async def test_carlos_scheduling_service_supports_multiple_sequential_tool_rounds(session_maker):
    openai = FakeToolOpenAIClient(
        [
            _tool_turn("call_1", "list_services", "{}"),
            _tool_turn(
                "call_2",
                "list_available_slots",
                '{"local_date": "2026-07-10", "service_ids": ["svc"]}',
            ),
            OpenAIResponseTurn(output_text="Há horários.", tool_calls=[], response_output_items=[]),
        ]
    )
    executor = FakeExecutor()

    result = await _service(session_maker, openai, executor).generate_reply(_message())

    assert result == "Há horários."
    assert [call["tool_name"] for call in executor.calls] == [
        "list_services",
        "list_available_slots",
    ]


@pytest.mark.anyio
async def test_carlos_scheduling_service_limits_tool_rounds(session_maker):
    openai = FakeToolOpenAIClient([_tool_turn(f"call_{index}", "list_services", "{}") for index in range(3)])
    executor = FakeExecutor()

    with pytest.raises(OpenAITemporaryError):
        await _service(
            session_maker,
            openai,
            executor,
            openai_max_tool_rounds=1,
        ).generate_reply(_message())


@pytest.mark.anyio
async def test_carlos_scheduling_service_rejects_multiple_tool_calls(session_maker):
    openai = FakeToolOpenAIClient(
        [
            OpenAIResponseTurn(
                output_text=None,
                tool_calls=[
                    OpenAIToolCall(call_id="call_1", name="list_services", arguments="{}"),
                    OpenAIToolCall(call_id="call_2", name="list_my_appointments", arguments="{}"),
                ],
                response_output_items=[],
            )
        ]
    )

    with pytest.raises(OpenAITemporaryError):
        await _service(session_maker, openai, FakeExecutor()).generate_reply(_message())


def _service(session_maker, openai, executor, **settings_overrides) -> CarlosSchedulingService:
    return CarlosSchedulingService(
        session_factory=session_maker,
        openai_client=openai,
        tool_executor=executor,
        settings=scheduling_settings(**settings_overrides),
        clock=FakeClock(datetime(2026, 7, 10, 12, 0, tzinfo=UTC)),
    )


def _message() -> InboundMessage:
    return InboundMessage(
        id="inbound-id",
        instance="turatti",
        message_id="message-id",
        phone="5534999999999",
        message_type="text",
        text="Quais serviços?",
        created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
    )


def _tool_turn(call_id: str, name: str, arguments: str) -> OpenAIResponseTurn:
    return OpenAIResponseTurn(
        output_text=None,
        tool_calls=[OpenAIToolCall(call_id=call_id, name=name, arguments=arguments)],
        response_output_items=[
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
            }
        ],
    )
