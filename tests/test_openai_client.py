from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.clients.openai_client import OpenAIResponsesClient
from app.exceptions.openai import (
    OpenAIInvalidResponseError,
    OpenAIPermanentError,
    OpenAITemporaryError,
)
from app.schemas.conversation import ConversationMessage


class FakeResponses:
    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.response = response or SimpleNamespace(
            output_text=" Ola! ",
            id="resp_1",
            model="gpt-4o-mini",
        )
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeSDK:
    def __init__(self, responses: FakeResponses, chat_completions=None) -> None:
        self.responses = responses
        self.chat = SimpleNamespace(
            completions=chat_completions or FakeChatCompletions()
        )
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeOpenAIError(Exception):
    def __init__(self, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__("unsafe full error with SECRET 5534999999999 cliente text")


class FakeChatCompletions:
    def __init__(self, content: str | None = " Oi pelo Ollama! ") -> None:
        self.calls: list[dict[str, object]] = []
        self.response = SimpleNamespace(
            id="chat_1",
            model="llama3.1:8b",
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        )

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


@pytest.mark.anyio
async def test_responses_api_request_shape_and_output_text() -> None:
    responses = FakeResponses()
    sdk = FakeSDK(responses)
    client = _client(sdk)
    messages = [
        ConversationMessage(role="user", content="Ola", created_at=_now()),
        ConversationMessage(role="assistant", content="Oi!", created_at=_now()),
        ConversationMessage(role="user", content="Quero corte", created_at=_now()),
    ]

    result = await client.generate_text(instructions="system prompt", messages=messages)
    call = responses.calls[0]

    assert call["model"] == "gpt-4o-mini"
    assert call["instructions"] == "system prompt"
    assert call["input"] == [
        {"role": "user", "content": "Ola"},
        {"role": "assistant", "content": "Oi!"},
        {"role": "user", "content": "Quero corte"},
    ]
    assert call["store"] is False
    assert call["max_output_tokens"] == 300
    assert "previous_response_id" not in call
    assert "5534999999999" not in str(call["input"])
    assert "internal-id" not in str(call["input"])
    assert result.text == "Ola!"
    assert result.response_id == "resp_1"


@pytest.mark.anyio
async def test_chat_completions_mode_uses_system_user_and_assistant_roles() -> None:
    chat = FakeChatCompletions()
    sdk = FakeSDK(FakeResponses(), chat)
    client = _client(sdk, compat_mode="chat_completions")
    messages = [
        ConversationMessage(role="user", content="Ola", created_at=_now()),
        ConversationMessage(role="assistant", content="Oi", created_at=_now()),
    ]

    result = await client.generate_text(instructions="persona", messages=messages)

    assert sdk.responses.calls == []
    assert chat.calls[0]["messages"] == [
        {"role": "system", "content": "persona"},
        {"role": "user", "content": "Ola"},
        {"role": "assistant", "content": "Oi"},
    ]
    assert "developer" not in str(chat.calls[0]["messages"])
    assert result.text == "Oi pelo Ollama!"


@pytest.mark.anyio
async def test_empty_chat_completion_uses_safe_fallback() -> None:
    chat = FakeChatCompletions(content=" ")
    client = _client(FakeSDK(FakeResponses(), chat), compat_mode="chat_completions")

    result = await client.generate_text(instructions="persona", messages=_messages())

    assert result.text == "Desculpa, não consegui entender bem. Pode me mandar de novo?"


@pytest.mark.anyio
async def test_empty_response_is_temporary_error() -> None:
    client = _client(FakeSDK(FakeResponses(SimpleNamespace(output_text="  "))))

    with pytest.raises(OpenAIInvalidResponseError):
        await client.generate_text(instructions="safe", messages=_messages())


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [408, 409, 429, 500])
async def test_temporary_errors_are_sanitized(status_code: int) -> None:
    client = _client(FakeSDK(FakeResponses(error=FakeOpenAIError(status_code))))

    with pytest.raises(OpenAITemporaryError) as error:
        await client.generate_text(instructions="safe", messages=_messages())

    assert "SECRET" not in str(error.value)
    assert "5534999999999" not in str(error.value)
    assert "cliente text" not in str(error.value)


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
async def test_permanent_errors_are_sanitized(status_code: int) -> None:
    client = _client(FakeSDK(FakeResponses(error=FakeOpenAIError(status_code))))

    with pytest.raises(OpenAIPermanentError) as error:
        await client.generate_text(instructions="safe", messages=_messages())

    assert "SECRET" not in str(error.value)
    assert "5534999999999" not in str(error.value)


@pytest.mark.anyio
async def test_timeout_and_connection_errors_are_temporary() -> None:
    for error in (TimeoutError("secret"), ConnectionError("secret")):
        client = _client(FakeSDK(FakeResponses(error=error)))
        with pytest.raises(OpenAITemporaryError):
            await client.generate_text(instructions="safe", messages=_messages())


@pytest.mark.anyio
async def test_injected_client_is_not_closed() -> None:
    sdk = FakeSDK(FakeResponses())
    client = _client(sdk)

    await client.close()

    assert sdk.closed is False


def _client(
    sdk: FakeSDK, *, compat_mode: str = "responses"
) -> OpenAIResponsesClient:
    return OpenAIResponsesClient(
        api_key=SecretStr("SECRET"),
        model="gpt-4o-mini",
        timeout_seconds=30,
        max_output_tokens=300,
        compat_mode=compat_mode,
        sdk_client=sdk,
    )


def _messages() -> list[ConversationMessage]:
    return [ConversationMessage(role="user", content="cliente text", created_at=_now())]


def _now() -> datetime:
    return datetime.now(UTC)
