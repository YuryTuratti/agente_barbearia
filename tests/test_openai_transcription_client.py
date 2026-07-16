from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.clients.openai_transcription_client import OpenAITranscriptionClient
from app.core.config import Settings
from app.exceptions.media import MediaPermanentError, MediaTemporaryError
from app.schemas.media import DownloadedMedia


@pytest.mark.anyio
async def test_openai_transcription_client_calls_audio_transcriptions_create() -> None:
    sdk = FakeOpenAITranscriptionSdk(text="  olá   mundo  ")
    client = OpenAITranscriptionClient(
        api_key=SecretStr("test-key"),
        settings=_settings(openai_transcription_prompt="contexto"),
        sdk_client=sdk,
    )

    result = await client.transcribe(audio=_audio())

    assert result.text == "olá mundo"
    assert result.provider == "openai"
    assert result.model == "gpt-test-transcribe"
    assert sdk.calls[0]["model"] == "gpt-test-transcribe"
    assert sdk.calls[0]["language"] == "pt"
    assert sdk.calls[0]["prompt"] == "contexto"
    file_name, file_obj, mimetype = sdk.calls[0]["file"]
    assert file_name == "clip.ogg"
    assert file_obj.read() == b"audio"
    assert mimetype == "audio/ogg"
    assert "phone" not in sdk.calls[0]
    assert "instance" not in sdk.calls[0]


@pytest.mark.anyio
async def test_openai_transcription_client_omits_optional_language_and_prompt() -> None:
    sdk = FakeOpenAITranscriptionSdk(text="texto")
    client = OpenAITranscriptionClient(
        api_key=SecretStr("test-key"),
        settings=_settings(
            openai_transcription_language="",
            openai_transcription_prompt="",
        ),
        sdk_client=sdk,
    )

    await client.transcribe(audio=_audio())

    assert "language" not in sdk.calls[0]
    assert "prompt" not in sdk.calls[0]


@pytest.mark.anyio
async def test_openai_transcription_client_empty_text_is_temporary() -> None:
    sdk = FakeOpenAITranscriptionSdk(text=" \x00 ")
    client = OpenAITranscriptionClient(
        api_key=SecretStr("test-key"),
        settings=_settings(),
        sdk_client=sdk,
    )

    with pytest.raises(MediaTemporaryError):
        await client.transcribe(audio=_audio())


@pytest.mark.anyio
async def test_openai_transcription_client_maps_temporary_and_permanent_errors() -> None:
    temporary_client = OpenAITranscriptionClient(
        api_key=SecretStr("test-key"),
        settings=_settings(),
        sdk_client=FakeOpenAITranscriptionSdk(error=StatusError(429)),
    )
    permanent_client = OpenAITranscriptionClient(
        api_key=SecretStr("test-key"),
        settings=_settings(),
        sdk_client=FakeOpenAITranscriptionSdk(error=StatusError(401)),
    )

    with pytest.raises(MediaTemporaryError) as temporary:
        await temporary_client.transcribe(audio=_audio())
    with pytest.raises(MediaPermanentError) as permanent:
        await permanent_client.transcribe(audio=_audio())

    assert "test-key" not in str(temporary.value)
    assert "test-key" not in str(permanent.value)


@pytest.mark.anyio
async def test_openai_transcription_client_does_not_close_injected_sdk() -> None:
    sdk = FakeOpenAITranscriptionSdk(text="texto")
    client = OpenAITranscriptionClient(
        api_key=SecretStr("test-key"),
        settings=_settings(),
        sdk_client=sdk,
    )

    await client.close()

    assert sdk.closed is False


class FakeTranscriptions:
    def __init__(self, owner: "FakeOpenAITranscriptionSdk") -> None:
        self._owner = owner

    async def create(self, **kwargs):
        self._owner.calls.append(kwargs)
        if self._owner.error is not None:
            raise self._owner.error
        return SimpleNamespace(text=self._owner.text)


class FakeAudio:
    def __init__(self, owner: "FakeOpenAITranscriptionSdk") -> None:
        self.transcriptions = FakeTranscriptions(owner)


class FakeOpenAITranscriptionSdk:
    def __init__(self, *, text: str | None = None, error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[dict[str, object]] = []
        self.closed = False
        self.audio = FakeAudio(self)

    async def close(self) -> None:
        self.closed = True


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def _audio() -> DownloadedMedia:
    return DownloadedMedia(
        content=b"audio",
        mimetype="audio/ogg",
        file_name="clip.ogg",
        size_bytes=5,
        sha256="hash",
        source="inline_base64",
    )


def _settings(**overrides: object) -> Settings:
    values = {
        "openai_transcription_model": "gpt-test-transcribe",
        **overrides,
    }
    return Settings(**values)
