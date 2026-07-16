import pytest
import httpx

from app.clients.evolution_client import EvolutionClient
from app.exceptions.evolution import EvolutionPermanentError, EvolutionTemporaryError


@pytest.mark.anyio
async def test_send_text_posts_expected_request() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.raw_path.decode("ascii")
        seen["apikey"] = request.headers["apikey"]
        seen["body"] = request.read()
        return httpx.Response(200, json={"key": {"id": "external-1"}})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = _client(http_client)

    result = await client.send_text(
        instance="turatti barbe",
        recipient="5534999999999",
        text="ola",
    )

    assert seen["method"] == "POST"
    assert seen["path"] == "/message/sendText/turatti%20barbe"
    assert seen["apikey"] == "SECRET"
    assert b'"number":"5534999999999"' in seen["body"]
    assert b'"text":"ola"' in seen["body"]
    assert result.success is True
    assert result.external_message_id == "external-1"
    assert result.status_code == 200
    await http_client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"key": {"id": "key-id"}}, "key-id"),
        ({"messageId": "message-id"}, "message-id"),
        ({"id": "plain-id"}, "plain-id"),
        ({}, None),
    ],
)
async def test_extracts_external_id_variants(
    payload: dict[str, object],
    expected: str | None,
) -> None:
    client = _client(
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            )
        )
    )

    result = await client.send_text(
        instance="turatti",
        recipient="5534999999999",
        text="ola",
    )

    assert result.external_message_id == expected


@pytest.mark.anyio
async def test_successful_non_json_response_does_not_break() -> None:
    client = _client(
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text="ok")
            )
        )
    )

    result = await client.send_text(
        instance="turatti",
        recipient="5534999999999",
        text="ola",
    )

    assert result.external_message_id is None


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [408, 429, 500])
async def test_temporary_http_errors(status_code: int) -> None:
    client = _client(
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status_code, text="secret body")
            )
        )
    )

    with pytest.raises(EvolutionTemporaryError) as error:
        await client.send_text(
            instance="turatti",
            recipient="5534999999999",
            text="mensagem secreta",
        )

    assert "SECRET" not in str(error.value)
    assert "5534999999999" not in str(error.value)
    assert "mensagem secreta" not in str(error.value)


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [400, 401, 404])
async def test_permanent_http_errors(status_code: int) -> None:
    client = _client(
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status_code, text="secret body")
            )
        )
    )

    with pytest.raises(EvolutionPermanentError):
        await client.send_text(
            instance="turatti",
            recipient="5534999999999",
            text="ola",
        )


@pytest.mark.anyio
async def test_timeout_and_connection_errors_are_temporary() -> None:
    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    async def connect_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("failed")

    for handler in (timeout_handler, connect_handler):
        client = _client(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        with pytest.raises(EvolutionTemporaryError):
            await client.send_text(
                instance="turatti",
                recipient="5534999999999",
                text="ola",
            )


@pytest.mark.anyio
async def test_client_ownership_on_close() -> None:
    owned = EvolutionClient(
        base_url="http://evolution.test",
        api_key="SECRET",
        send_text_path="/message/sendText/{instance}",
        timeout_seconds=1,
    )
    await owned.close()

    external_http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    injected = _client(external_http_client)
    await injected.close()

    assert external_http_client.is_closed is False
    await external_http_client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("instance", "recipient", "text"),
    [
        (" ", "5534999999999", "ola"),
        ("turatti", "not-a-phone", "ola"),
        ("turatti", "5534999999999", " "),
    ],
)
async def test_invalid_input_is_permanent(
    instance: str,
    recipient: str,
    text: str,
) -> None:
    client = _client(
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        )
    )

    with pytest.raises(EvolutionPermanentError):
        await client.send_text(instance=instance, recipient=recipient, text=text)


def _client(http_client: httpx.AsyncClient) -> EvolutionClient:
    return EvolutionClient(
        base_url="http://evolution.test",
        api_key="SECRET",
        send_text_path="/message/sendText/{instance}",
        timeout_seconds=1,
        http_client=http_client,
    )
