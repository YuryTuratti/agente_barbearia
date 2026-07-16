import base64
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.database.models import InboundMedia, InboundMessage
from app.exceptions.gemini import GeminiPermanentError, GeminiTemporaryError
from app.schemas.image_analysis import HaircutReferenceAnalysis, ImageAnalysisResult
from app.schemas.media import DownloadedMedia
from app.services.image_analysis_service import ImageAnalysisService


@pytest.mark.anyio
async def test_image_analysis_service_saves_structured_result_and_context(session_maker) -> None:
    message = await _create_image_message(session_maker, caption="Quero parecido")
    media_client = FakeMediaClient()
    gemini_client = FakeGeminiClient(_haircut_result(features=["laterais curtas", "laterais curtas", "volume no topo"]))
    service = _service(session_maker, media_client, gemini_client)

    context = await service.analyze_inbound_image(message)

    assert "Mensagem escrita pelo cliente: Quero parecido" in context
    assert "referencia visual" in context
    async with session_maker() as session:
        media = (await session.execute(select(InboundMedia))).scalar_one()
        assert media.status == "completed"
        assert media.attempts == 1
        assert media.analysis_kind == "haircut_reference"
        assert media.analysis_data["purpose"] == "haircut_reference"
        assert media.analysis_data["haircut"]["features"] == ["laterais curtas", "volume no topo"]
        assert media.extracted_text == context
        assert media.content_sha256 == "image-sha"
        assert media.file_size_bytes == 6
        assert media.provider == "gemini"
        assert media.model == "gemini-test"
        assert media.inline_base64 is None


@pytest.mark.anyio
async def test_image_analysis_service_replay_reuses_completed_context(session_maker) -> None:
    message = await _create_image_message(
        session_maker,
        status="completed",
        extracted_text="Contexto existente",
    )
    media_client = FakeMediaClient()
    gemini_client = FakeGeminiClient(_haircut_result())
    service = _service(session_maker, media_client, gemini_client)

    context = await service.analyze_inbound_image(message)

    assert context == "Contexto existente"
    assert media_client.calls == 0
    assert gemini_client.calls == 0


@pytest.mark.anyio
async def test_image_analysis_service_temporary_error_schedules_retry(session_maker) -> None:
    message = await _create_image_message(session_maker)
    service = _service(
        session_maker,
        FakeMediaClient(),
        FakeGeminiClient(error=GeminiTemporaryError("temporary")),
    )

    with pytest.raises(Exception):
        await service.analyze_inbound_image(message)

    async with session_maker() as session:
        media = (await session.execute(select(InboundMedia))).scalar_one()
        assert media.status == "pending"
        assert media.next_attempt_at is not None
        assert media.inline_base64 is not None


@pytest.mark.anyio
async def test_image_analysis_service_permanent_error_marks_failed_and_clears_base64(session_maker) -> None:
    message = await _create_image_message(session_maker)
    service = _service(
        session_maker,
        FakeMediaClient(),
        FakeGeminiClient(error=GeminiPermanentError("blocked")),
    )

    with pytest.raises(GeminiPermanentError):
        await service.analyze_inbound_image(message)

    async with session_maker() as session:
        media = (await session.execute(select(InboundMedia))).scalar_one()
        assert media.status == "failed"
        assert media.inline_base64 is None
        assert media.last_error == "GeminiPermanentError"


async def _create_image_message(
    session_maker,
    *,
    caption: str | None = None,
    status: str = "pending",
    extracted_text: str | None = None,
) -> InboundMessage:
    async with session_maker() as session:
        message = InboundMessage(
            instance="turatti",
            message_id=f"IMAGE-{datetime.now(UTC).timestamp()}",
            event="messages.upsert",
            remote_jid="5534999999999@s.whatsapp.net",
            phone="5534999999999",
            message_type="image",
            text=caption,
            media_mimetype="image/jpeg",
            status="pending",
            attempts=0,
        )
        session.add(message)
        await session.flush()
        session.add(
            InboundMedia(
                inbound_message_id=message.id,
                media_type="image",
                mimetype="image/jpeg",
                status=status,
                attempts=0,
                source="inline_base64",
                media_locator={"message_id": message.message_id},
                inline_base64=base64.b64encode(b"image").decode(),
                extracted_text=extracted_text,
            )
        )
        await session.commit()
        await session.refresh(message)
        return message


def _service(session_maker, media_client, gemini_client) -> ImageAnalysisService:
    return ImageAnalysisService(
        session_factory=session_maker,
        media_client=media_client,
        gemini_client=gemini_client,
        settings=Settings(
            gemini_image_model="gemini-test",
            image_analysis_max_features=2,
            image_analysis_max_summary_characters=1000,
            image_analysis_max_context_characters=1600,
        ),
    )


class FakeMediaClient:
    def __init__(self) -> None:
        self.calls = 0

    async def get_media_bytes(self, **kwargs) -> DownloadedMedia:
        self.calls += 1
        return DownloadedMedia(
            content=b"image!",
            mimetype="image/jpeg",
            file_name="image.jpg",
            size_bytes=6,
            sha256="image-sha",
            source="inline_base64",
        )


class FakeGeminiClient:
    def __init__(
        self,
        result: ImageAnalysisResult | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def analyze(self, *, image: DownloadedMedia) -> ImageAnalysisResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _haircut_result(features: list[str] | None = None) -> ImageAnalysisResult:
    return ImageAnalysisResult(
        purpose="haircut_reference",
        confidence="medium",
        safe_summary="Corte com laterais curtas e volume no topo.",
        haircut=HaircutReferenceAnalysis(
            visible=True,
            probable_style_name="degrade baixo",
            features=features or ["laterais curtas"],
            fade_level="low",
            top_length="medium",
            texture_description=None,
            beard_visible=False,
            notes=None,
        ),
    )
