from sqlalchemy import select

import pytest

from app.core.config import Settings
from app.database.models import InboundMessage, OutboundMessage
from app.exceptions.gemini import GeminiPermanentError
from app.services.image_analysis_service import IMAGE_ANALYSIS_FAILURE_REPLY
from app.services.inbound_message_processor import InboundMessageProcessor


@pytest.mark.anyio
async def test_image_processor_passes_controlled_context_to_handler(session_maker) -> None:
    message = await _create_pending_image(session_maker)
    handler = RecordingHandler()
    processor = InboundMessageProcessor(
        session_factory=session_maker,
        handler=handler,
        settings=Settings(inbound_image_analysis_enabled=True, gemini_api_key="fake"),
        image_analysis_service=FakeImageAnalysisService("Contexto visual controlado"),
    )

    processed = await processor.process_once()

    assert processed == 1
    assert handler.messages == [("image", "Contexto visual controlado", message.id)]
    async with session_maker() as session:
        stored = await session.get(InboundMessage, message.id)
        assert stored is not None
        assert stored.message_type == "image"
        assert stored.text is None
        assert stored.status == "completed"


@pytest.mark.anyio
async def test_image_processor_permanent_failure_enqueues_safe_reply_without_handler(session_maker) -> None:
    message = await _create_pending_image(session_maker)
    handler = RecordingHandler()
    processor = InboundMessageProcessor(
        session_factory=session_maker,
        handler=handler,
        settings=Settings(inbound_image_analysis_enabled=True, gemini_api_key="fake"),
        image_analysis_service=FakeImageAnalysisService(
            error=GeminiPermanentError("blocked")
        ),
    )

    processed = await processor.process_once()

    assert processed == 1
    assert handler.messages == []
    async with session_maker() as session:
        outbound = (await session.execute(select(OutboundMessage))).scalar_one()
        assert outbound.text == IMAGE_ANALYSIS_FAILURE_REPLY
        assert outbound.deduplication_key == f"inbound-reply:{message.id}"


async def _create_pending_image(session_maker) -> InboundMessage:
    async with session_maker() as session:
        message = InboundMessage(
            instance="turatti",
            message_id="IMAGE-PROCESSOR",
            event="messages.upsert",
            remote_jid="5534999999999@s.whatsapp.net",
            phone="5534999999999",
            message_type="image",
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


class FakeImageAnalysisService:
    def __init__(
        self,
        text: str | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.text = text
        self.error = error

    async def analyze_inbound_image(self, message: InboundMessage) -> str:
        if self.error is not None:
            raise self.error
        assert self.text is not None
        return self.text
