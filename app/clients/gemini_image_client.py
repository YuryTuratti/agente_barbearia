import inspect
import json
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr, ValidationError

from app.exceptions.gemini import (
    GeminiInvalidResponseError,
    GeminiPermanentError,
    GeminiSafetyBlockedError,
    GeminiTemporaryError,
)
from app.prompts.image_analysis import IMAGE_ANALYSIS_PROMPT
from app.schemas.image_analysis import ImageAnalysisResult
from app.schemas.media import DownloadedMedia

if TYPE_CHECKING:
    from google.genai import Client


class GeminiImageClient:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float,
        max_output_tokens: int,
        temperature: float,
        sdk_client: "Client | None" = None,
    ) -> None:
        if not api_key.get_secret_value().strip():
            raise GeminiPermanentError("Gemini API key is required.")
        if not model.strip():
            raise GeminiPermanentError("Gemini image model is required.")
        if timeout_seconds <= 0:
            raise GeminiPermanentError("Gemini image timeout must be greater than zero.")
        if max_output_tokens <= 0:
            raise GeminiPermanentError("Gemini max output tokens must be greater than zero.")
        if temperature < 0 or temperature > 1:
            raise GeminiPermanentError("Gemini temperature must be between 0 and 1.")

        self._model = model.strip()
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._owns_client = sdk_client is None
        if sdk_client is None:
            try:
                from google import genai
            except ImportError as error:
                raise GeminiPermanentError("google-genai SDK is not installed.") from error
            sdk_client = genai.Client(api_key=api_key.get_secret_value())
        self._sdk_client = sdk_client

    async def analyze(self, *, image: DownloadedMedia) -> ImageAnalysisResult:
        types = None
        if self._owns_client:
            try:
                from google.genai import types as google_types
            except ImportError as error:
                raise GeminiPermanentError("google-genai SDK is not installed.") from error
            types = google_types

        try:
            if types is None:
                contents: list[object] = [
                    {"text": IMAGE_ANALYSIS_PROMPT},
                    {
                        "data": image.content,
                        "mime_type": image.mimetype or "application/octet-stream",
                    },
                ]
                config: object = {
                    "response_mime_type": "application/json",
                    "response_schema": ImageAnalysisResult,
                    "max_output_tokens": self._max_output_tokens,
                    "temperature": self._temperature,
                }
            else:
                contents = [
                    types.Part.from_text(text=IMAGE_ANALYSIS_PROMPT),
                    types.Part.from_bytes(
                        data=image.content,
                        mime_type=image.mimetype or "application/octet-stream",
                    ),
                ]
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ImageAnalysisResult,
                    max_output_tokens=self._max_output_tokens,
                    temperature=self._temperature,
                )
            response = await self._sdk_client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
        except Exception as error:
            raise _map_gemini_error(error) from error

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, ImageAnalysisResult):
            return parsed
        if parsed is not None:
            try:
                return ImageAnalysisResult.model_validate(parsed)
            except ValidationError as error:
                raise GeminiInvalidResponseError("Gemini response did not match schema.") from error

        text = _response_text(response)
        if not text:
            raise GeminiInvalidResponseError("Gemini returned an empty response.")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise GeminiInvalidResponseError("Gemini returned invalid JSON.") from error
        try:
            return ImageAnalysisResult.model_validate(payload)
        except ValidationError as error:
            raise GeminiInvalidResponseError("Gemini response did not match schema.") from error

    async def close(self) -> None:
        if not self._owns_client:
            return
        aio = getattr(self._sdk_client, "aio", None)
        close_method = (
            getattr(aio, "close", None)
            or getattr(aio, "aclose", None)
            or getattr(self._sdk_client, "close", None)
            or getattr(self._sdk_client, "aclose", None)
        )
        if close_method is None:
            return
        result = close_method()
        if inspect.isawaitable(result):
            await result


def _response_text(response: object) -> str | None:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    candidates = getattr(response, "candidates", None)
    if candidates:
        finish_reason = getattr(candidates[0], "finish_reason", None)
        if str(finish_reason).lower().find("safety") >= 0:
            raise GeminiSafetyBlockedError("Gemini image analysis was blocked.")
    return None


def _map_gemini_error(error: Exception) -> Exception:
    status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
    if status_code in {408, 409, 429} or (
        isinstance(status_code, int) and 500 <= status_code <= 599
    ):
        return GeminiTemporaryError(f"Gemini returned HTTP {status_code}.")
    if status_code in {400, 401, 403, 404}:
        return GeminiPermanentError(f"Gemini returned HTTP {status_code}.")
    name = error.__class__.__name__.lower()
    if "safety" in name or "blocked" in name:
        return GeminiSafetyBlockedError("Gemini image analysis was blocked.")
    if "timeout" in name or "connection" in name or "connect" in name or "ratelimit" in name:
        return GeminiTemporaryError("Gemini request failed temporarily.")
    if "authentication" in name or "permission" in name or "notfound" in name:
        return GeminiPermanentError("Gemini request configuration is invalid.")
    return GeminiTemporaryError("Gemini request failed.")
