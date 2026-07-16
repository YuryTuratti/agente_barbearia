import inspect
import re
from io import BytesIO
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from app.core.config import Settings
from app.exceptions.media import InvalidMediaError, MediaPermanentError, MediaTemporaryError
from app.schemas.media import DownloadedMedia, TranscriptionResult

if TYPE_CHECKING:
    from openai import AsyncOpenAI


class OpenAITranscriptionClient:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        settings: Settings,
        sdk_client: "AsyncOpenAI | None" = None,
    ) -> None:
        if not api_key.get_secret_value().strip():
            raise MediaPermanentError("OpenAI API key is required.")
        self._settings = settings
        self._owns_client = sdk_client is None
        if sdk_client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as error:
                raise MediaPermanentError("OpenAI SDK is not installed.") from error
            sdk_client = AsyncOpenAI(
                api_key=api_key.get_secret_value(),
                timeout=settings.openai_transcription_timeout_seconds,
            )
        self._sdk_client = sdk_client

    async def transcribe(self, *, audio: DownloadedMedia) -> TranscriptionResult:
        file_name = audio.file_name or "audio"
        file_obj = BytesIO(audio.content)
        file_obj.name = file_name
        kwargs: dict[str, Any] = {
            "model": self._settings.openai_transcription_model,
            "file": (file_name, file_obj, audio.mimetype or "application/octet-stream"),
        }
        if self._settings.openai_transcription_language is not None:
            kwargs["language"] = self._settings.openai_transcription_language
        if self._settings.openai_transcription_prompt is not None:
            kwargs["prompt"] = self._settings.openai_transcription_prompt
        try:
            response = await self._sdk_client.audio.transcriptions.create(**kwargs)
        except Exception as error:
            raise _map_openai_transcription_error(error) from error
        text = _normalize_transcription_text(getattr(response, "text", None))
        if len(text) > self._settings.openai_transcription_max_characters:
            text = text[: self._settings.openai_transcription_max_characters].strip()
        return TranscriptionResult(
            text=text,
            provider="openai",
            model=self._settings.openai_transcription_model,
        )

    async def close(self) -> None:
        if not self._owns_client:
            return
        close_method = getattr(self._sdk_client, "close", None) or getattr(self._sdk_client, "aclose", None)
        if close_method is None:
            return
        result = close_method()
        if inspect.isawaitable(result):
            await result


def _normalize_transcription_text(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidMediaError("Transcription response did not include text.")
    text = re.sub(r"\s+", " ", value.replace("\x00", "")).strip()
    if not text:
        raise MediaTemporaryError("Transcription response was empty.")
    return text


def _map_openai_transcription_error(error: Exception) -> Exception:
    status_code = getattr(error, "status_code", None)
    if status_code in {408, 409, 429} or (isinstance(status_code, int) and 500 <= status_code <= 599):
        return MediaTemporaryError(f"OpenAI transcription returned HTTP {status_code}.")
    if status_code in {400, 401, 403, 404}:
        return MediaPermanentError(f"OpenAI transcription returned HTTP {status_code}.")
    name = error.__class__.__name__.lower()
    if "timeout" in name or "connection" in name or "connect" in name or "ratelimit" in name:
        return MediaTemporaryError("OpenAI transcription failed temporarily.")
    if "authentication" in name or "permission" in name:
        return MediaPermanentError("OpenAI transcription authentication failed.")
    return MediaTemporaryError("OpenAI transcription failed.")
