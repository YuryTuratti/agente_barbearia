from sqlalchemy import select

import pytest

from app.core.config import Settings
from app.database.models import InboundMessage, OutboundMessage
from app.exceptions.media import InvalidMediaError
from app.services.inbound_message_processor import (
    AUDIO_TRANSCRIPTION_FAILURE_REPLY,
    InboundMessageProcessor,
)


@pytest.mark.anyio
async def test_audio_processor_passes_transcribed_text_to_handler(session_maker) -> None:
    message = await _create_pending_audio(session_maker)
    handler = RecordingHandler()
    processor = InboundMessageProcessor(
        session_factory=session_maker,
        handler=handler,
        settings=Settings(inbound_audio_transcription_enabled=True),
        audio_transcription_service=FakeAudioTranscriptionService("Quero agendar"),
    )

    processed = await processor.process_once()

    assert processed == 1
    assert handler.messages == [("text", "Quero agendar", message.id)]
    async with session_maker() as session:
        stored = await session.get(InboundMessage, message.id)
        assert stored is not None
        assert stored.message_type == "audio"
        assert stored.text is None
        assert stored.status == "completed"


@pytest.mark.anyio
async def test_audio_processor_permanent_failure_enqueues_safe_reply_without_handler(
    session_maker,
) -> None:
    message = await _create_pending_audio(session_maker)
    handler = RecordingHandler()
    processor = InboundMessageProcessor(
        session_factory=session_maker,
        handler=handler,
        settings=Settings(inbound_audio_transcription_enabled=True),
        audio_transcription_service=FakeAudioTranscriptionService(
            error=InvalidMediaError("invalid")
        ),
    )

    processed = await processor.process_once()

    assert processed == 1
    assert handler.messages == []
    async with session_maker() as session:
        stored = await session.get(InboundMessage, message.id)
        outbound = (await session.execute(select(OutboundMessage))).scalar_one()
        assert stored is not None
        assert stored.status == "completed"
        assert outbound.deduplication_key == f"inbound-reply:{message.id}"
        assert outbound.text == AUDIO_TRANSCRIPTION_FAILURE_REPLY


async def _create_pending_audio(session_maker) -> InboundMessage:
    async with session_maker() as session:
        message = InboundMessage(
            instance="turatti",
            message_id="AUDIO-PROCESSOR",
            event="messages.upsert",
            remote_jid="5534999999999@s.whatsapp.net",
            phone="5534999999999",
            message_type="audio",
            text=None,
            status="pending",
            attempts=0,
        )
        session.add(message)
        await session.commit()
        await session.refresh(message)
        return message


class RecordingHandler:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str | None, str]] = []

    async def handle(self, message: InboundMessage) -> None:
        self.messages.append((message.message_type, message.text, message.id))


class FakeAudioTranscriptionService:
    def __init__(
        self,
        text: str | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.text = text
        self.error = error

    async def transcribe_inbound_audio(self, message: InboundMessage) -> str:
        if self.error is not None:
            raise self.error
        assert self.text is not None
        return self.text
