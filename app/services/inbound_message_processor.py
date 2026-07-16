import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.exceptions.handlers import PermanentMessageHandlingError
from app.exceptions.gemini import GeminiPermanentError
from app.exceptions.media import MediaPermanentError, MediaTemporaryError, MediaTooLargeError
from app.handlers.base import MessageHandler
from app.repositories.inbound_message_repository import (
    claim_pending_messages,
    mark_message_completed,
    mark_message_failed,
    mark_message_permanently_failed,
    release_stale_processing_messages,
)
from app.repositories.outbound_message_repository import enqueue_text_message
from app.services.image_analysis_service import (
    IMAGE_ANALYSIS_FAILURE_REPLY,
    IMAGE_TOO_LARGE_REPLY,
)

logger = logging.getLogger(__name__)

AUDIO_TRANSCRIPTION_FAILURE_REPLY = (
    "Nao consegui entender esse audio. Pode enviar novamente ou escrever sua "
    "mensagem, por favor?"
)


class InboundMessageProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        handler: MessageHandler,
        settings: Settings,
        audio_transcription_service=None,
        image_analysis_service=None,
    ) -> None:
        self._session_factory = session_factory
        self._handler = handler
        self._settings = settings
        self._audio_transcription_service = audio_transcription_service
        self._image_analysis_service = image_analysis_service

    async def process_once(self) -> int:
        now = datetime.now(UTC)
        stale_before = now - timedelta(
            seconds=self._settings.worker_processing_timeout_seconds
        )

        async with self._session_factory() as session:
            released_count = await release_stale_processing_messages(
                session,
                stale_before=stale_before,
                now=now,
                max_attempts=self._settings.worker_max_attempts,
            )
            messages = await claim_pending_messages(
                session,
                limit=self._settings.worker_batch_size,
                now=now,
            )

        if released_count:
            logger.info("Released stale processing messages: count=%s", released_count)

        logger.info("Claimed inbound messages: count=%s", len(messages))

        for message in messages:
            try:
                if not self._is_phone_allowed(message.phone):
                    async with self._session_factory() as session:
                        await mark_message_completed(
                            session,
                            message.id,
                            completed_at=datetime.now(UTC),
                        )
                    logger.info(
                        "Inbound message ignored by phone allowlist: "
                        "record_id=%s phone=%s",
                        message.id,
                        _mask_phone(message.phone),
                    )
                    continue
                if (
                    self._settings.inbound_audio_transcription_enabled
                    and message.message_type == "audio"
                    and self._audio_transcription_service is not None
                ):
                    try:
                        transcription = await (
                            self._audio_transcription_service
                        ).transcribe_inbound_audio(message)
                    except MediaPermanentError:
                        if not message.phone:
                            raise PermanentMessageHandlingError(
                                "Audio message has no recipient phone."
                            )
                        async with self._session_factory() as session:
                            await enqueue_text_message(
                                session,
                                inbound_message_id=message.id,
                                deduplication_key=f"inbound-reply:{message.id}",
                                instance=message.instance,
                                recipient=message.phone,
                                text=AUDIO_TRANSCRIPTION_FAILURE_REPLY,
                            )
                            await mark_message_completed(
                                session,
                                message.id,
                                completed_at=datetime.now(UTC),
                            )
                        logger.info(
                            "Inbound audio failed permanently and received a safe "
                            "reply: record_id=%s",
                            message.id,
                        )
                        continue
                    except MediaTemporaryError:
                        raise
                    else:
                        message.message_type = "text"
                        message.text = transcription
                if (
                    self._settings.inbound_image_analysis_enabled
                    and message.message_type == "image"
                    and self._image_analysis_service is not None
                ):
                    try:
                        context = await (
                            self._image_analysis_service
                        ).analyze_inbound_image(message)
                    except MediaTooLargeError:
                        await self._enqueue_safe_media_reply(
                            message,
                            text=IMAGE_TOO_LARGE_REPLY,
                        )
                        continue
                    except (MediaPermanentError, GeminiPermanentError):
                        await self._enqueue_safe_media_reply(
                            message,
                            text=IMAGE_ANALYSIS_FAILURE_REPLY,
                        )
                        continue
                    except MediaTemporaryError:
                        raise
                    else:
                        message.text = context
                await self._handler.handle(message)
            except PermanentMessageHandlingError as error:
                logger.info(
                    "Inbound message permanently failed: record_id=%s "
                    "message_type=%s error_type=%s",
                    message.id,
                    message.message_type,
                    error.__class__.__name__,
                )
                async with self._session_factory() as session:
                    await mark_message_permanently_failed(
                        session,
                        message.id,
                        error_message=str(error),
                        failed_at=datetime.now(UTC),
                    )
                continue
            except Exception as error:
                logger.exception(
                    "Inbound message handler failed: record_id=%s message_type=%s",
                    message.id,
                    message.message_type,
                )
                async with self._session_factory() as session:
                    await mark_message_failed(
                        session,
                        message.id,
                        error_message=str(error),
                        failed_at=datetime.now(UTC),
                        max_attempts=self._settings.worker_max_attempts,
                        retry_delay_seconds=(
                            self._settings.worker_retry_delay_seconds
                        ),
                    )
                continue

            async with self._session_factory() as session:
                await mark_message_completed(
                    session,
                    message.id,
                    completed_at=datetime.now(UTC),
                )
            logger.info(
                "Inbound message completed: record_id=%s",
                message.id,
            )

        return len(messages)

    def _is_phone_allowed(self, phone: str | None) -> bool:
        allowed = self._settings.inbound_allowed_phone_set
        if not allowed:
            return True
        normalized = "".join(
            character for character in (phone or "") if character.isdigit()
        )
        return normalized in allowed

    async def _enqueue_safe_media_reply(
        self,
        message,
        *,
        text: str,
    ) -> None:
        if not message.phone:
            raise PermanentMessageHandlingError(
                "Media message has no recipient phone."
            )
        async with self._session_factory() as session:
            await enqueue_text_message(
                session,
                inbound_message_id=message.id,
                deduplication_key=f"inbound-reply:{message.id}",
                instance=message.instance,
                recipient=message.phone,
                text=text,
            )
            await mark_message_completed(
                session,
                message.id,
                completed_at=datetime.now(UTC),
            )


def _mask_phone(phone: str | None) -> str:
    clean = "".join(character for character in (phone or "") if character.isdigit())
    if len(clean) < 6:
        return "*" * len(clean)
    return f"{clean[:2]}******{clean[-4:]}"
