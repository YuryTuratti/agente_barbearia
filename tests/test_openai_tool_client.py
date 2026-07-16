from types import SimpleNamespace

import pytest

from app.exceptions.openai import OpenAITemporaryError
from app.schemas.openai_response import OpenAIResponseTurn
from tests.test_openai_client import FakeOpenAIError, FakeResponses, FakeSDK, _client


@pytest.mark.anyio
async def test_openai_tool_turn_uses_responses_api_with_required_tool_options():
    response = SimpleNamespace(
        output_text=None,
        output=[
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "list_services",
                "arguments": "{}",
            }
        ],
    )
    responses = FakeResponses(response=response)
    client = _client(FakeSDK(responses))

    result = await client.create_tool_turn(
        instructions="safe prompt",
        input_items=[{"role": "user", "content": "Quais serviços?"}],
        tools=[{"type": "function", "name": "list_services"}],
    )
    call = responses.calls[0]

    assert isinstance(result, OpenAIResponseTurn)
    assert call["tools"] == [{"type": "function", "name": "list_services"}]
    assert call["store"] is False
    assert call["parallel_tool_calls"] is False
    assert call["tool_choice"] == "auto"
    assert call["max_output_tokens"] == 300
    assert "previous_response_id" not in call
    assert "5534999999999" not in str(call)
    assert result.tool_calls[0].call_id == "call_1"
    assert result.tool_calls[0].name == "list_services"
    assert result.tool_calls[0].arguments == "{}"


@pytest.mark.anyio
async def test_openai_tool_turn_extracts_final_text():
    client = _client(FakeSDK(FakeResponses(SimpleNamespace(output_text=" Final ", output=[]))))

    result = await client.create_tool_turn(
        instructions="safe prompt",
        input_items=[{"role": "user", "content": "Oi"}],
        tools=[],
    )

    assert result.output_text == "Final"
    assert result.tool_calls == []


@pytest.mark.anyio
async def test_openai_tool_turn_maps_timeout_as_temporary_error():
    client = _client(FakeSDK(FakeResponses(error=TimeoutError("secret"))))

    with pytest.raises(OpenAITemporaryError):
        await client.create_tool_turn(
            instructions="safe prompt",
            input_items=[{"role": "user", "content": "Oi"}],
            tools=[],
        )


@pytest.mark.anyio
async def test_openai_tool_turn_maps_server_error_as_temporary_error():
    client = _client(FakeSDK(FakeResponses(error=FakeOpenAIError(500))))

    with pytest.raises(OpenAITemporaryError):
        await client.create_tool_turn(
            instructions="safe prompt",
            input_items=[{"role": "user", "content": "Oi"}],
            tools=[],
        )
