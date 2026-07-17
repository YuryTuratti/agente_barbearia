import argparse
import asyncio
import logging
import signal

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.clients.openai_client import OpenAIResponsesClient
from app.clients.evolution_media_client import EvolutionMediaClient
from app.clients.gemini_image_client import GeminiImageClient
from app.clients.openai_transcription_client import OpenAITranscriptionClient
from app.database.connection import AsyncSessionLocal, engine
from app.exceptions.openai import OpenAIPermanentError
from app.handlers.base import MessageHandler
from app.handlers.carlos_ai_handler import CarlosAIHandler
from app.handlers.carlos_scheduling_handler import CarlosSchedulingHandler
from app.handlers.carlos_scheduling_write_handler import CarlosSchedulingWriteHandler
from app.handlers.logging_message_handler import LoggingMessageHandler
from app.handlers.test_reply_handler import TestReplyHandler
from app.domain.clock import SystemClock
from app.services.carlos_response_service import CarlosResponseService
from app.services.carlos_scheduling_service import CarlosSchedulingService
from app.services.carlos_scheduling_write_service import CarlosSchedulingWriteService
from app.services.inbound_message_processor import InboundMessageProcessor
from app.services.audio_transcription_service import AudioTranscriptionService
from app.services.image_analysis_service import ImageAnalysisService
from app.services.scheduling_action_service import SchedulingActionService
from app.tools.scheduling_executor import SchedulingToolExecutor
from app.tools.scheduling_write_executor import SchedulingWriteToolExecutor

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process pending inbound messages.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single worker cycle and exit.",
    )

    return parser.parse_args(argv)


async def run_worker(
    *,
    once: bool = False,
    processor: InboundMessageProcessor | None = None,
    settings: Settings | None = None,
    openai_client: OpenAIResponsesClient | None = None,
    dispose_engine: bool = True,
) -> int:
    worker_settings = settings or get_settings()
    configure_logging(worker_settings)
    handler: MessageHandler | None = None
    audio_transcription_service = None
    image_analysis_service = None
    media_client = None
    transcription_client = None
    gemini_client = None
    if processor is None:
        handler = _build_handler(worker_settings, openai_client=openai_client)
        if (
            worker_settings.inbound_audio_transcription_enabled
            or worker_settings.inbound_image_analysis_enabled
        ):
            media_client = EvolutionMediaClient(settings=worker_settings)
        if worker_settings.inbound_audio_transcription_enabled:
            if worker_settings.openai_api_key is None:
                raise OpenAIPermanentError("OpenAI API key is required for audio transcription.")
            transcription_client = OpenAITranscriptionClient(
                api_key=worker_settings.openai_api_key,
                settings=worker_settings,
            )
            audio_transcription_service = AudioTranscriptionService(
                session_factory=AsyncSessionLocal,
                media_client=media_client,
                transcription_client=transcription_client,
                settings=worker_settings,
            )
        if worker_settings.inbound_image_analysis_enabled:
            if worker_settings.gemini_api_key is None:
                raise OpenAIPermanentError("Gemini API key is required for image analysis.")
            gemini_client = GeminiImageClient(
                api_key=worker_settings.gemini_api_key,
                model=worker_settings.gemini_image_model,
                timeout_seconds=worker_settings.gemini_image_timeout_seconds,
                max_output_tokens=worker_settings.gemini_image_max_output_tokens,
                temperature=worker_settings.gemini_image_temperature,
            )
            image_analysis_service = ImageAnalysisService(
                session_factory=AsyncSessionLocal,
                media_client=media_client,
                gemini_client=gemini_client,
                settings=worker_settings,
            )
    worker_processor = processor or InboundMessageProcessor(
        session_factory=AsyncSessionLocal,
        handler=handler,
        settings=worker_settings,
        audio_transcription_service=audio_transcription_service,
        image_analysis_service=image_analysis_service,
    )
    stop_event = asyncio.Event()

    def request_stop() -> None:
        stop_event.set()

    running_loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is None:
            continue
        try:
            running_loop.add_signal_handler(signal_value, request_stop)
        except (NotImplementedError, RuntimeError):
            pass

    logger.info("Inbound message worker started: once=%s", once)

    try:
        while not stop_event.is_set():
            claimed_count = await worker_processor.process_once()
            logger.info("Worker cycle completed: claimed_count=%s", claimed_count)

            if once:
                break

            if claimed_count == 0:
                await asyncio.sleep(worker_settings.worker_poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Inbound message worker interrupted.")
        return 0
    except Exception:
        logger.exception("Inbound message worker stopped after a fatal error.")
        return 1
    finally:
        shutdown_timeout = worker_settings.graceful_shutdown_timeout_seconds
        close_method = getattr(handler, "close", None)
        if close_method is not None:
            await _close_resource(close_method(), shutdown_timeout)
        if media_client is not None:
            await _close_resource(media_client.close(), shutdown_timeout)
        if transcription_client is not None:
            await _close_resource(transcription_client.close(), shutdown_timeout)
        if gemini_client is not None:
            await _close_resource(gemini_client.close(), shutdown_timeout)
        if dispose_engine:
            await _close_resource(engine.dispose(), shutdown_timeout)
        logger.info("Inbound message worker stopped.")

    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    return asyncio.run(run_worker(once=args.once))


def _build_handler(
    settings: Settings,
    *,
    openai_client: OpenAIResponsesClient | None = None,
) -> MessageHandler:
    if settings.inbound_handler_mode == "test_reply":
        return TestReplyHandler(AsyncSessionLocal)
    if settings.inbound_handler_mode == "openai_text":
        client = openai_client or _build_openai_client(settings)
        response_service = CarlosResponseService(
            session_factory=AsyncSessionLocal,
            openai_client=client,
            settings=settings,
        )
        return CarlosAIHandler(
            session_factory=AsyncSessionLocal,
            response_service=response_service,
        )
    if settings.inbound_handler_mode == "openai_scheduling":
        client = openai_client or _build_openai_client(settings)
        clock = SystemClock()
        tool_executor = SchedulingToolExecutor(
            session_factory=AsyncSessionLocal,
            settings=settings,
            clock=clock,
        )
        response_service = CarlosSchedulingService(
            session_factory=AsyncSessionLocal,
            openai_client=client,
            tool_executor=tool_executor,
            settings=settings,
            clock=clock,
        )
        return CarlosSchedulingHandler(
            session_factory=AsyncSessionLocal,
            response_service=response_service,
        )
    if settings.inbound_handler_mode == "openai_scheduling_write":
        client = openai_client or _build_openai_client(settings)
        clock = SystemClock()
        read_executor = SchedulingToolExecutor(
            session_factory=AsyncSessionLocal,
            settings=settings,
            clock=clock,
        )
        action_service = SchedulingActionService(
            session_factory=AsyncSessionLocal,
            settings=settings,
            clock=clock,
        )
        write_executor = SchedulingWriteToolExecutor(
            read_executor=read_executor,
            action_service=action_service,
        )
        response_service = CarlosSchedulingWriteService(
            session_factory=AsyncSessionLocal,
            openai_client=client,
            tool_executor=write_executor,
            settings=settings,
            clock=clock,
        )
        return CarlosSchedulingWriteHandler(
            session_factory=AsyncSessionLocal,
            response_service=response_service,
        )

    return LoggingMessageHandler()


def _build_openai_client(settings: Settings) -> OpenAIResponsesClient:
    if settings.openai_api_key is None:
        raise OpenAIPermanentError(
            "OpenAI API key is required for OpenAI handler modes."
        )

    return OpenAIResponsesClient(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
        max_output_tokens=settings.openai_max_output_tokens,
        base_url=settings.openai_base_url,
        compat_mode=settings.openai_compat_mode,
    )


async def _close_resource(awaitable, timeout_seconds: float) -> None:
    try:
        await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except Exception as error:
        logger.error(
            "Resource close failed: error_type=%s",
            error.__class__.__name__,
        )


if __name__ == "__main__":
    raise SystemExit(main())
