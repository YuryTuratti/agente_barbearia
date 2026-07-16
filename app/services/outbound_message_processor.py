import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.evolution_client import EvolutionClient
from app.core.config import Settings
from app.exceptions.evolution import EvolutionPermanentError, EvolutionTemporaryError
from app.repositories.outbound_message_repository import (
    claim_pending_outbound_messages,
    mark_outbound_message_permanent_error,
    mark_outbound_message_sent,
    mark_outbound_message_temporary_error,
    release_stale_outbound_messages,
)

logger = logging.getLogger(__name__)


class OutboundMessageProcessor:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        evolution_client: EvolutionClient,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._evolution_client = evolution_client
        self._settings = settings

    async def process_once(self) -> int:
        now = datetime.now(UTC)
        stale_before = now - timedelta(
            seconds=self._settings.outbound_worker_processing_timeout_seconds
        )

        async with self._session_factory() as session:
            released_count = await release_stale_outbound_messages(
                session,
                stale_before=stale_before,
                now=now,
                max_attempts=self._settings.outbound_worker_max_attempts,
            )
            messages = await claim_pending_outbound_messages(
                session,
                limit=self._settings.outbound_worker_batch_size,
                now=now,
            )

        if released_count:
            logger.info("Released stale outbound messages: count=%s", released_count)

        logger.info("Claimed outbound messages: count=%s", len(messages))

        for message in messages:
            try:
                result = await self._evolution_client.send_text(
                    instance=message.instance,
                    recipient=message.recipient,
                    text=message.text,
                )
            except EvolutionTemporaryError as error:
                logger.info(
                    "Temporary outbound send failure: record_id=%s",
                    message.id,
                )
                async with self._session_factory() as session:
                    await mark_outbound_message_temporary_error(
                        session,
                        message.id,
                        error_message=str(error),
                        failed_at=datetime.now(UTC),
                        max_attempts=self._settings.outbound_worker_max_attempts,
                        retry_delay_seconds=(
                            self._settings.outbound_worker_retry_delay_seconds
                        ),
                    )
                continue
            except EvolutionPermanentError as error:
                logger.info(
                    "Permanent outbound send failure: record_id=%s",
                    message.id,
                )
                async with self._session_factory() as session:
                    await mark_outbound_message_permanent_error(
                        session,
                        message.id,
                        error_message=str(error),
                        failed_at=datetime.now(UTC),
                    )
                continue
            except Exception as error:
                logger.exception(
                    "Unexpected outbound send failure: record_id=%s",
                    message.id,
                )
                async with self._session_factory() as session:
                    await mark_outbound_message_temporary_error(
                        session,
                        message.id,
                        error_message=str(error),
                        failed_at=datetime.now(UTC),
                        max_attempts=self._settings.outbound_worker_max_attempts,
                        retry_delay_seconds=(
                            self._settings.outbound_worker_retry_delay_seconds
                        ),
                    )
                continue

            async with self._session_factory() as session:
                await mark_outbound_message_sent(
                    session,
                    message.id,
                    sent_at=datetime.now(UTC),
                    external_message_id=result.external_message_id,
                )

            logger.info(
                "Outbound message sent: record_id=%s status_code=%s",
                message.id,
                result.status_code,
            )

        return len(messages)
