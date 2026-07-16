from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.evolution_media_client import EvolutionMediaClient
from app.clients.gemini_image_client import GeminiImageClient
from app.core.config import Settings
from app.database.models import InboundMedia, InboundMessage
from app.domain.image_analysis import build_image_context, sanitize_image_analysis
from app.exceptions.gemini import GeminiPermanentError, GeminiTemporaryError
from app.exceptions.media import MediaPermanentError, MediaProcessingError, MediaTemporaryError, UnsupportedMediaTypeError
from app.repositories.inbound_media_repository import (
    claim_inbound_media,
    get_inbound_media_by_inbound_id,
    mark_media_completed,
    mark_media_failed,
    mark_media_retry,
)

SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/heic",
    "image/heif",
}

IMAGE_ANALYSIS_FAILURE_REPLY = (
    "Nao consegui entender essa imagem. Pode enviar outra foto mais clara ou "
    "descrever o corte por mensagem, por favor?"
)

IMAGE_TOO_LARGE_REPLY = (
    "Essa imagem e muito grande para eu analisar. Pode enviar uma versao menor, "
    "por favor?"
)


class ImageAnalysisService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        media_client: EvolutionMediaClient,
        gemini_client: GeminiImageClient,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._media_client = media_client
        self._gemini_client = gemini_client
        self._settings = settings

    async def analyze_inbound_image(self, message: InboundMessage) -> str:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            media = await get_inbound_media_by_inbound_id(session, inbound_message_id=message.id)
            if media is None:
                raise MediaPermanentError("Inbound image media was not registered.")
            if media.status == "completed" and media.extracted_text:
                return media.extracted_text
            media = await claim_inbound_media(session, inbound_message_id=message.id, now=now)
            if media is None:
                raise MediaPermanentError("Inbound image media was not registered.")
            if media.status in {"failed", "unsupported"}:
                raise MediaPermanentError("Inbound image media is not processable.")
            if media.media_type != "image":
                raise UnsupportedMediaTypeError("Only image media can be analyzed.")
            if media.status == "completed" and media.extracted_text:
                return media.extracted_text

        try:
            downloaded = await self._media_client.get_media_bytes(
                instance=message.instance,
                media_locator=media.media_locator,
                inline_base64=media.inline_base64,
                expected_mimetype=media.mimetype,
                allowed_mimetypes=SUPPORTED_IMAGE_MIME_TYPES,
                max_bytes=self._settings.media_max_image_bytes,
            )
            raw_analysis = await self._gemini_client.analyze(image=downloaded)
            analysis = sanitize_image_analysis(
                raw_analysis,
                max_features=self._settings.image_analysis_max_features,
                max_summary_characters=self._settings.image_analysis_max_summary_characters,
            )
            context = build_image_context(
                analysis,
                caption=message.text,
                max_characters=self._settings.image_analysis_max_context_characters,
            )
        except (MediaTemporaryError, GeminiTemporaryError) as error:
            await self._handle_temporary_error(media)
            raise MediaTemporaryError("Image analysis failed temporarily.") from error
        except (MediaPermanentError, GeminiPermanentError) as error:
            await self._handle_permanent_error(media, error)
            raise
        except MediaProcessingError:
            raise

        async with self._session_factory() as session:
            fresh = await session.get(InboundMedia, media.id)
            if fresh is None:
                raise MediaPermanentError("Inbound image media was not registered.")
            await mark_media_completed(
                session,
                media=fresh,
                extracted_text=context,
                content_sha256=downloaded.sha256,
                size_bytes=downloaded.size_bytes,
                provider="gemini",
                model=self._settings.gemini_image_model,
                now=datetime.now(UTC),
                analysis_kind=analysis.purpose,
                analysis_data=analysis.model_dump(mode="json"),
            )
        return context

    async def _handle_temporary_error(self, media: InboundMedia) -> None:
        async with self._session_factory() as session:
            fresh = await session.get(InboundMedia, media.id)
            if fresh is None:
                return
            if fresh.attempts >= self._settings.media_processing_max_attempts:
                await mark_media_failed(
                    session,
                    media=fresh,
                    error_message="Temporary image analysis error.",
                    now=datetime.now(UTC),
                )
            else:
                await mark_media_retry(
                    session,
                    media=fresh,
                    error_message="Temporary image analysis error.",
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
