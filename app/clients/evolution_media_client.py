import base64
import hashlib
import inspect
from typing import Any

import httpx

from app.core.config import Settings
from app.exceptions.media import (
    InvalidMediaError,
    MediaTemporaryError,
    MediaTooLargeError,
    UnsupportedMediaTypeError,
)
from app.schemas.media import DownloadedMedia


def build_media_request_body(media_locator: dict[str, object]) -> dict[str, object]:
    return {"message": dict(media_locator)}


class EvolutionMediaClient:
    def __init__(
        self,
        *,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            base_url=settings.evolution_api_base_url,
            timeout=settings.media_download_timeout_seconds,
            follow_redirects=False,
            max_redirects=settings.media_max_download_redirects,
        )

    async def get_media_bytes(
        self,
        *,
        instance: str,
        media_locator: dict[str, object],
        inline_base64: str | None,
        expected_mimetype: str | None,
        allowed_mimetypes: set[str] | None = None,
        max_bytes: int | None = None,
    ) -> DownloadedMedia:
        normalized_mimetype = normalize_mimetype(expected_mimetype)
        if allowed_mimetypes is not None:
            _validate_mimetype(normalized_mimetype, allowed_mimetypes)
        byte_limit = max_bytes or self._settings.media_max_audio_bytes
        if inline_base64:
            return _decode_media(
                inline_base64,
                mimetype=normalized_mimetype,
                file_name=None,
                source="inline_base64",
                max_bytes=byte_limit,
            )
        path = self._settings.evolution_media_base64_path.format(instance=instance)
        try:
            response = await self._http_client.post(
                path,
                headers={
                    "apikey": self._settings.evolution_api_key,
                    "Content-Type": "application/json",
                },
                json=build_media_request_body(media_locator),
            )
        except (TimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.TransportError) as error:
            raise MediaTemporaryError("Media download failed temporarily.") from error
        if response.status_code in {408, 429} or 500 <= response.status_code <= 599:
            raise MediaTemporaryError(f"Media download returned HTTP {response.status_code}.")
        if response.status_code >= 400:
            raise InvalidMediaError(f"Media download returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as error:
            raise InvalidMediaError("Media response is not valid JSON.") from error
        media_base64 = _extract_base64(payload)
        return _decode_media(
            media_base64,
            mimetype=normalized_mimetype,
            file_name=None,
            source="evolution_api",
            max_bytes=byte_limit,
        )

    async def close(self) -> None:
        if not self._owns_client:
            return
        result = self._http_client.aclose()
        if inspect.isawaitable(result):
            await result


def _extract_base64(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("base64", "media"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("base64"), str):
            return data["base64"]
    raise InvalidMediaError("Media response did not include base64.")


def _decode_media(
    value: str,
    *,
    mimetype: str | None,
    file_name: str | None,
    source: str,
    max_bytes: int,
) -> DownloadedMedia:
    clean = value.strip()
    if "," in clean and clean.lower().startswith("data:"):
        clean = clean.split(",", maxsplit=1)[1]
    try:
        content = base64.b64decode(clean, validate=True)
    except Exception as error:
        raise InvalidMediaError("Media base64 is invalid.") from error
    if not content:
        raise InvalidMediaError("Media content is empty.")
    if len(content) > max_bytes:
        raise MediaTooLargeError("Media content is too large.")
    return DownloadedMedia(
        content=content,
        mimetype=mimetype,
        file_name=file_name,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        source=source,  # type: ignore[arg-type]
    )


def normalize_mimetype(value: str | None) -> str | None:
    if value is None:
        return None
    family = value.split(";", maxsplit=1)[0].strip().lower()
    if family == "image/jpg":
        return "image/jpeg"
    return family or None


def _validate_mimetype(
    mimetype: str | None,
    allowed_mimetypes: set[str],
) -> None:
    if mimetype is None:
        return
    normalized_allowed = {normalize_mimetype(item) for item in allowed_mimetypes}
    if mimetype not in normalized_allowed:
        raise UnsupportedMediaTypeError("Media mimetype is not supported.")
