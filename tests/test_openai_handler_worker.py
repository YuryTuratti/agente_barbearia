import anyio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.database.models import InboundMessage, OutboundMessage
from app.handlers.carlos_ai_handler import CarlosAIHandler
from app.schemas.openai_response import OpenAITextResult
from app.services.carlos_response_service import CarlosResponseService
from app.services.inbound_message_processor import InboundMessageProcessor
from app.services.outbound_message_processor import OutboundMessageProcessor
from app.workers import inbound_message_worker, outbound_message_worker


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_text(self, *, instructions: str, messages: list[object]):
        self.calls += 1
        return OpenAITextResult(text="Posso te ajudar com isso.", model="fake")

    async def close(self) -> None:
        return None


class FakeEvolutionClient:
    def __init__(self) -> None:
        self.calls = 0

    async def send_text(self, *, instance: str, recipient: str, text: str):
        self.calls += 1
        return type(
            "Result",
            (),
            {
                "success": True,
                "external_message_id": "evo-1",
                "status_code": 200,
            },
        )()


def test_local_end_to_end_openai_to_outbound_to_evolution(
    client: TestClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    fake_openai = FakeOpenAIClient()
    fake_evolution = FakeEvolutionClient()

    response = client.post("/webhooks/evolution", json=_payload())
    assert response.status_code == 200

    async def run_flow() -> None:
        settings = _settings()
        response_service = CarlosResponseService(
            session_factory=session_maker,
            openai_client=fake_openai,
            settings=settings,
        )
        inbound_processor = InboundMessageProcessor(
            session_maker,
            CarlosAIHandler(
                session_factory=session_maker,
                response_service=response_service,
            ),
            settings,
        )
        outbound_processor = OutboundMessageProcessor(
            session_factory=session_maker,
            evolution_client=fake_evolution,
            settings=settings,
        )

        assert await inbound_message_worker.run_worker(
            once=True,
            processor=inbound_processor,
            settings=settings,
            dispose_engine=False,
        ) == 0
        assert await outbound_message_worker.run_worker(
            once=True,
            processor=outbound_processor,
            settings=settings,
            dispose_engine=False,
        ) == 0
        assert await inbound_message_worker.run_worker(
            once=True,
            processor=inbound_processor,
            settings=settings,
            dispose_engine=False,
        ) == 0
        assert await outbound_message_worker.run_worker(
            once=True,
            processor=outbound_processor,
            settings=settings,
            dispose_engine=False,
        ) == 0

    anyio.run(run_flow)

    async def inspect_state() -> tuple[list[InboundMessage], list[OutboundMessage]]:
        async with session_maker() as session:
            inbounds = list((await session.execute(select(InboundMessage))).scalars().all())
            outbounds = list((await session.execute(select(OutboundMessage))).scalars().all())
            return inbounds, outbounds

    inbounds, outbounds = anyio.run(inspect_state)
    assert fake_openai.calls == 1
    assert fake_evolution.calls == 1
    assert len(outbounds) == 1
    assert inbounds[0].status == "completed"
    assert outbounds[0].status == "sent"


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///test.db",
        worker_poll_interval_seconds=0.01,
        worker_batch_size=1,
        worker_max_attempts=3,
        worker_retry_delay_seconds=30,
        worker_processing_timeout_seconds=300,
        outbound_worker_batch_size=1,
        outbound_worker_max_attempts=3,
        outbound_worker_retry_delay_seconds=30,
        outbound_worker_processing_timeout_seconds=300,
    )


def _payload() -> dict[str, object]:
    return {
        "event": "messages.upsert",
        "instance": "turatti-barbe",
        "data": {
            "key": {
                "id": "ABC123",
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "Cliente Teste",
            "message": {
                "conversation": "Ola, quero marcar um corte.",
            },
        },
    }
