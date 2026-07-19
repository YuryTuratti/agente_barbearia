import json
import logging
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from app.clients.ollama_cloud_client import CHAT_EMPTY_FALLBACK, OllamaCloudClient
from app.exceptions.openai import OpenAITemporaryError
from app.schemas.conversation import ConversationMessage


@pytest.mark.anyio
async def test_calls_direct_chat_api_and_converts_response() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"message": {"content": " Olá! "}})

    client = _client(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await client.generate_text(instructions="persona", messages=_messages())

    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://ollama.com/api/chat"
    assert request.headers["Authorization"] == "Bearer super-secret-token"
    assert request.headers["Content-Type"] == "application/json"
    assert body == {
        "model": "gpt-oss:120b",
        "messages": [
            {"role": "system", "content": "persona"},
            {"role": "user", "content": "quero cortar o cabelo"},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    assert result.text == "Olá!"
    assert result.model == "gpt-oss:120b"


@pytest.mark.anyio
async def test_empty_response_uses_fallback() -> None:
    client = _client(
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"message": {"content": " "}})
            )
        )
    )

    result = await client.generate_text(instructions="persona", messages=_messages())

    assert result.text == CHAT_EMPTY_FALLBACK


@pytest.mark.anyio
async def test_server_error_is_temporary_and_logs_are_sanitized(caplog) -> None:
    caplog.set_level(logging.INFO)
    client = _client(
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(503, text="super-secret-token 5534999999999 conversa")
            )
        )
    )

    with pytest.raises(OpenAITemporaryError) as error:
        await client.generate_text(instructions="segredo da conversa", messages=_messages())

    captured = caplog.text + str(error.value)
    assert "super-secret-token" not in captured
    assert "5534999999999" not in captured
    assert "segredo da conversa" not in captured
    assert "provider=ollama_cloud" in caplog.text
    assert "model=gpt-oss:120b" in caplog.text
    assert "timeout_seconds=120" in caplog.text


def _client(http_client: httpx.AsyncClient) -> OllamaCloudClient:
    return OllamaCloudClient(
        api_key=SecretStr("super-secret-token"),
        base_url="https://ollama.com/",
        model="gpt-oss:120b",
        timeout_seconds=120,
        http_client=http_client,
    )


def _messages() -> list[ConversationMessage]:
    return [
        ConversationMessage(
            role="user",
            content="quero cortar o cabelo",
            created_at=datetime.now(UTC),
        )
    ]
