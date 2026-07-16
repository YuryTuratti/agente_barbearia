import base64
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.database.models import InboundMedia, InboundMessage
from app.exceptions.media import InvalidMediaError, MediaTemporaryError
from app.schemas.media import DownloadedMedia, TranscriptionResult
from app.services.audio_transcription_service import AudioTranscriptionService


@pytest.mark.anyio
async def test_audio_transcription_service_saves_success_and_clears_inline_base64(
    session_maker,
) -> None:
    message = await _create_audio_message(session_maker)
    media_client = FakeMediaClient()
    transcription_client = FakeTranscriptionClient(text="Mensagem transcrita")
    service = _service(session_maker, media_client, transcription_client)

    text = await service.transcribe_inbound_audio(message)

    assert text == "Mensagem transcrita"
    async with session_maker() as session:
        media = (await session.execute(select(InboundMedia))).scalar_one()
        assert media.status == "completed"
        assert media.attempts == 1
        assert media.extracted_text == "Mensagem transcrita"
        assert media.content_sha256 == "sha256"
        assert media.file_size_bytes == 5
        assert media.provider == "openai"
        assert media.model == "gpt-test-transcribe"
        assert media.inline_base64 is None
        assert media.processed_at is not None


@pytest.mark.anyio
async def test_audio_transcription_service_replay_reuses_completed_transcription(
    session_maker,
) -> None:
    message = await _create_audio_message(session_maker, status="completed", extracted_text="Ja transcrito")
    media_client = FakeMediaClient()
    transcription_client = FakeTranscriptionClient(text="Novo texto")
    service = _service(session_maker, media_client, transcription_client)

    text = await service.transcribe_inbound_audio(message)

    assert text == "Ja transcrito"
    assert media_client.calls == 0
    assert transcription_client.calls == 0


@pytest.mark.anyio
async def test_audio_transcription_service_temporary_error_schedules_retry(
    session_maker,
) -> None:
    message = await _create_audio_message(session_maker)
    service = _service(
        session_maker,
        FakeMediaClient(error=MediaTemporaryError("temporary")),
        FakeTranscriptionClient(text="unused"),
    )

    with pytest.raises(MediaTemporaryError):
        await service.transcribe_inbound_audio(message)

    async with session_maker() as session:
        media = (await session.execute(select(InboundMedia))).scalar_one()
        assert media.status == "pending"
        assert media.attempts == 1
        assert media.next_attempt_at is not None
        assert media.inline_base64 is not None


@pytest.mark.anyio
async def test_audio_transcription_service_permanent_error_marks_failed_and_clears_base64(
    session_maker,
) -> None:
    message = await _create_audio_message(session_maker)
    service = _service(
        session_maker,
        FakeMediaClient(error=InvalidMediaError("invalid")),
        FakeTranscriptionClient(text="unused"),
    )

    with pytest.raises(InvalidMediaError):
        await service.transcribe_inbound_audio(message)

    async with session_maker() as session:
        media = (await session.execute(select(InboundMedia))).scalar_one()
        assert media.status == "failed"
        assert media.inline_base64 is None
        assert media.last_error == "InvalidMediaError"


async def _create_audio_message(
    session_maker,
    *,
    status: str = "pending",
    extracted_text: str | None = None,
) -> InboundMessage:
    async with session_maker() as session:
        message = InboundMessage(
            instance="turatti",
            message_id=f"AUDIO-{datetime.now(UTC).timestamp()}",
            event="messages.upsert",
            remote_jid="5534999999999@s.whatsapp.net",
            phone="5534999999999",
            message_type="audio",
            text=None,
            media_mimetype="audio/ogg",
            status="pending",
            attempts=0,
        )
        session.add(message)
        await session.flush()
        session.add(
            InboundMedia(
                inbound_message_id=message.id,
                media_type="audio",
                mimetype="audio/ogg; codecs=opus",
                file_name=None,
                file_size_bytes=5,
                status=status,
                attempts=0,
                source="inline_base64",
                media_locator={"message_id": message.message_id},
                inline_base64=base64.b64encode(b"audio").decode(),
                extracted_text=extracted_text,
            )
        )
        await session.commit()
        await session.refresh(message)
        return message


def _service(session_maker, media_client, transcription_client) -> AudioTranscriptionService:
    return AudioTranscriptionService(
        session_factory=session_maker,
        media_client=media_client,
        transcription_client=transcription_client,
        settings=Settings(
            media_processing_retry_delay_seconds=10,
            openai_transcription_model="gpt-test-transcribe",
        ),
    )


class FakeMediaClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def get_media_bytes(self, **kwargs) -> DownloadedMedia:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return DownloadedMedia(
            content=b"audio",
            mimetype="audio/ogg",
            file_name="audio.ogg",
            size_bytes=5,
            sha256="sha256",
            source="inline_base64",
        )


class FakeTranscriptionClient:
    def __init__(self, *, text: str) -> None:
        self.text = text
        self.calls = 0

    async def transcribe(self, *, audio: DownloadedMedia) -> TranscriptionResult:
        self.calls += 1
        return TranscriptionResult(
            text=self.text,
            provider="openai",
            model="gpt-test-transcribe",
        )
