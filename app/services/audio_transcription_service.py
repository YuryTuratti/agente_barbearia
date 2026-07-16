from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.evolution_media_client import EvolutionMediaClient
from app.clients.openai_transcription_client import OpenAITranscriptionClient
from app.core.config import Settings
from app.database.models import InboundMedia, InboundMessage
from app.exceptions.media import MediaPermanentError, MediaProcessingError, MediaTemporaryError, UnsupportedMediaTypeError
from app.repositories.inbound_media_repository import (
    claim_inbound_media,
    get_inbound_media_by_inbound_id,
    mark_media_completed,
    mark_media_failed,
    mark_media_retry,
)

SUPPORTED_AUDIO_MIME_TYPES = {
    "audio/ogg",
    "audio/opus",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
}


class AudioTranscriptionService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        media_client: EvolutionMediaClient,
        transcription_client: OpenAITranscriptionClient,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._media_client = media_client
        self._transcription_client = transcription_client
        self._settings = settings

    async def transcribe_inbound_audio(self, message: InboundMessage) -> str:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            media = await get_inbound_media_by_inbound_id(session, inbound_message_id=message.id)
            if media is None:
                raise MediaPermanentError("Inbound audio media was not registered.")
            if media.status == "completed" and media.extracted_text:
                return media.extracted_text
            media = await claim_inbound_media(session, inbound_message_id=message.id, now=now)
            if media is None:
                raise MediaPermanentError("Inbound audio media was not registered.")
            if media.status in {"failed", "unsupported"}:
                raise MediaPermanentError("Inbound audio media is not processable.")
            if media.media_type != "audio":
                raise UnsupportedMediaTypeError("Only audio media can be transcribed.")
            _validate_audio_mimetype(media.mimetype)
            if media.status == "completed" and media.extracted_text:
                return media.extracted_text

        try:
            downloaded = await self._media_client.get_media_bytes(
                instance=message.instance,
                media_locator=media.media_locator,
                inline_base64=media.inline_base64,
                expected_mimetype=media.mimetype,
                allowed_mimetypes=SUPPORTED_AUDIO_MIME_TYPES,
                max_bytes=self._settings.media_max_audio_bytes,
            )
            result = await self._transcription_client.transcribe(audio=downloaded)
        except MediaTemporaryError as error:
            await self._handle_temporary_error(media, error)
            raise
        except MediaPermanentError as error:
            await self._handle_permanent_error(media, error)
            raise
        except MediaProcessingError:
            raise

        async with self._session_factory() as session:
            fresh = await session.get(InboundMedia, media.id)
            if fresh is None:
                raise MediaPermanentError("Inbound audio media was not registered.")
            await mark_media_completed(
                session,
                media=fresh,
                extracted_text=result.text,
                content_sha256=downloaded.sha256,
                size_bytes=downloaded.size_bytes,
                provider=result.provider,
                model=result.model,
                now=datetime.now(UTC),
            )
        return result.text

    async def _handle_temporary_error(self, media: InboundMedia, error: Exception) -> None:
        async with self._session_factory() as session:
            fresh = await session.get(InboundMedia, media.id)
            if fresh is None:
                return
            if fresh.attempts >= self._settings.media_processing_max_attempts:
                await mark_media_failed(
                    session,
                    media=fresh,
                    error_message="Temporary media processing error.",
                    now=datetime.now(UTC),
                )
            else:
                await mark_media_retry(
                    session,
                    media=fresh,
                    error_message="Temporary media processing error.",
                    now=datetime.now(UTC),
                    retry_delay_seconds=self._settings.media_processing_retry_delay_seconds,
                )

    async def _handle_permanent_error(self, media: InboundMedia, error: Exception) -> None:
        async with self._session_factory() as session:
            fresh = await session.get(InboundMedia, media.id)
            if fresh is None:
                return
            await mark_media_failed(
                session,
                media=fresh,
                error_message=error.__class__.__name__,
                now=datetime.now(UTC),
            )


def _validate_audio_mimetype(mimetype: str | None) -> None:
    if mimetype is None:
        return
    family = mimetype.split(";", maxsplit=1)[0].strip().lower()
    if family not in SUPPORTED_AUDIO_MIME_TYPES:
        raise UnsupportedMediaTypeError("Audio mimetype is not supported.")
