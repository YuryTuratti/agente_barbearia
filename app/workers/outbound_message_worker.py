import argparse
import asyncio
import logging
import signal

from app.clients.evolution_client import EvolutionClient
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.database.connection import AsyncSessionLocal, engine
from app.services.outbound_message_processor import OutboundMessageProcessor

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process pending outbound messages.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single worker cycle and exit.",
    )

    return parser.parse_args(argv)


async def run_worker(
    *,
    once: bool = False,
    processor: OutboundMessageProcessor | None = None,
    settings: Settings | None = None,
    evolution_client: EvolutionClient | None = None,
    dispose_engine: bool = True,
) -> int:
    worker_settings = settings or get_settings()
    configure_logging(worker_settings)
    owns_client = processor is None
    client = evolution_client
    if client is None and processor is None:
        client = EvolutionClient(
            base_url=worker_settings.evolution_api_base_url,
            api_key=worker_settings.evolution_api_key,
            send_text_path=worker_settings.evolution_send_text_path,
            timeout_seconds=worker_settings.evolution_request_timeout_seconds,
        )
    worker_processor = processor or OutboundMessageProcessor(
        session_factory=AsyncSessionLocal,
        evolution_client=client,  # type: ignore[arg-type]
        settings=worker_settings,
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

    logger.info("Outbound message worker started: once=%s", once)

    try:
        while not stop_event.is_set():
            claimed_count = await worker_processor.process_once()
            logger.info("Outbound worker cycle completed: claimed_count=%s", claimed_count)

            if once:
                break

            if claimed_count == 0:
                await asyncio.sleep(
                    worker_settings.outbound_worker_poll_interval_seconds
                )
    except KeyboardInterrupt:
        logger.info("Outbound message worker interrupted.")
        return 0
    except Exception:
        logger.exception("Outbound message worker stopped after a fatal error.")
        return 1
    finally:
        shutdown_timeout = worker_settings.graceful_shutdown_timeout_seconds
        if owns_client and client is not None:
            await _close_resource(client.close(), shutdown_timeout)
        if dispose_engine:
            await _close_resource(engine.dispose(), shutdown_timeout)
        logger.info("Outbound message worker stopped.")

    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    return asyncio.run(run_worker(once=args.once))


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
