import base64
import hashlib
import json

import httpx
import pytest

from app.clients.evolution_media_client import EvolutionMediaClient
from app.core.config import Settings
from app.exceptions.media import InvalidMediaError, MediaTemporaryError, MediaTooLargeError
from app.exceptions.media import UnsupportedMediaTypeError


@pytest.mark.anyio
async def test_evolution_media_client_uses_inline_base64_first() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"base64": base64.b64encode(b"http").decode()})

    client = EvolutionMediaClient(
        settings=_settings(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    media = await client.get_media_bytes(
        instance="turatti",
        media_locator={"message_id": "AUDIO1"},
        inline_base64=base64.b64encode(b"inline").decode(),
        expected_mimetype="audio/ogg",
    )

    assert called is False
    assert media.content == b"inline"
    assert media.source == "inline_base64"
    assert media.sha256 == hashlib.sha256(b"inline").hexdigest()


@pytest.mark.anyio
async def test_evolution_media_client_downloads_base64_from_configured_endpoint() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers["apikey"]
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"data": {"base64": "data:audio/ogg;base64," + base64.b64encode(b"audio").decode()}},
        )

    client = EvolutionMediaClient(
        settings=_settings(),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://evolution.local",
        ),
    )

    media = await client.get_media_bytes(
        instance="main",
        media_locator={"message_id": "AUDIO2"},
        inline_base64=None,
        expected_mimetype="audio/ogg; codecs=opus",
    )

    assert seen["url"] == "http://evolution.local/chat/getBase64FromMediaMessage/main"
    assert seen["apikey"] == "test-key"
    assert seen["body"] == {"message": {"message_id": "AUDIO2"}}
    assert media.content == b"audio"
    assert media.source == "evolution_api"


@pytest.mark.anyio
async def test_evolution_media_client_rejects_invalid_empty_and_large_media() -> None:
    client = EvolutionMediaClient(
        settings=_settings(media_max_audio_bytes=3),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
    )

    with pytest.raises(InvalidMediaError):
        await client.get_media_bytes(
            instance="main",
            media_locator={},
            inline_base64="not-base64",
            expected_mimetype="audio/ogg",
        )

    with pytest.raises(InvalidMediaError):
        await client.get_media_bytes(
            instance="main",
            media_locator={},
            inline_base64="data:audio/ogg;base64,",
            expected_mimetype="audio/ogg",
        )

    with pytest.raises(MediaTooLargeError):
        await client.get_media_bytes(
            instance="main",
            media_locator={},
            inline_base64=base64.b64encode(b"toolarge").decode(),
            expected_mimetype="audio/ogg",
        )


@pytest.mark.anyio
async def test_evolution_media_client_maps_http_errors_safely() -> None:
    temporary = EvolutionMediaClient(
        settings=_settings(),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(429)),
            base_url="http://evolution.local",
        ),
    )
    permanent = EvolutionMediaClient(
        settings=_settings(),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(400)),
            base_url="http://evolution.local",
        ),
    )

    with pytest.raises(MediaTemporaryError) as temporary_error:
        await temporary.get_media_bytes(
            instance="main",
            media_locator={},
            inline_base64=None,
            expected_mimetype="audio/ogg",
        )
    with pytest.raises(InvalidMediaError) as permanent_error:
        await permanent.get_media_bytes(
            instance="main",
            media_locator={},
            inline_base64=None,
            expected_mimetype="audio/ogg",
        )

    assert "test-key" not in str(temporary_error.value)
    assert "test-key" not in str(permanent_error.value)


def _settings(**overrides: object) -> Settings:
    values = {
        "evolution_api_base_url": "http://evolution.local",
        "evolution_api_key": "test-key",
        **overrides,
    }
    return Settings(**values)


@pytest.mark.anyio
async def test_evolution_media_client_validates_image_mimetypes_and_limits() -> None:
    client = EvolutionMediaClient(
        settings=_settings(media_max_audio_bytes=3, media_max_image_bytes=10),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
    )

    jpeg = await client.get_media_bytes(
        instance="main",
        media_locator={},
        inline_base64=base64.b64encode(b"image").decode(),
        expected_mimetype="image/jpg; charset=binary",
        allowed_mimetypes={"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"},
        max_bytes=10,
    )

    assert jpeg.mimetype == "image/jpeg"
    assert jpeg.content == b"image"

    with pytest.raises(UnsupportedMediaTypeError):
        await client.get_media_bytes(
            instance="main",
            media_locator={},
            inline_base64=base64.b64encode(b"svg").decode(),
            expected_mimetype="image/svg+xml",
            allowed_mimetypes={"image/jpeg", "image/png"},
            max_bytes=10,
        )

    with pytest.raises(MediaTooLargeError):
        await client.get_media_bytes(
            instance="main",
            media_locator={},
            inline_base64=base64.b64encode(b"large-image").decode(),
            expected_mimetype="image/png",
            allowed_mimetypes={"image/png"},
            max_bytes=5,
        )
