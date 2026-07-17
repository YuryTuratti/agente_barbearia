import anyio
from types import SimpleNamespace
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.clients.openai_client import OpenAIResponsesClient
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


class FakeChatCompletions:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def create(self, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            id="chat-ollama",
            model="llama3.1:8b",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Resposta via chat completions")
                )
            ],
        )


class FakeChatSDK:
    def __init__(self, error: Exception | None = None) -> None:
        self.chat_completions = FakeChatCompletions(error)
        self.chat = SimpleNamespace(completions=self.chat_completions)


class FakeProviderError(Exception):
    status_code = 500
    response = SimpleNamespace(
        status_code=500,
        text='provider failed for 5534999999999 with token sk-unsafe',
    )


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


def test_chat_completions_reply_is_enqueued_as_outbound(
    client: TestClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    response = client.post("/webhooks/evolution", json=_payload())
    assert response.status_code == 200
    sdk = FakeChatSDK()
    openai_client = OpenAIResponsesClient(
        api_key=SecretStr("ollama"),
        model="llama3.1:8b",
        timeout_seconds=30,
        max_output_tokens=300,
        compat_mode="chat_completions",
        sdk_client=sdk,
    )

    async def run_flow() -> None:
        settings = _settings()
        service = CarlosResponseService(
            session_factory=session_maker,
            openai_client=openai_client,
            settings=settings,
        )
        processor = InboundMessageProcessor(
            session_maker,
            CarlosAIHandler(session_factory=session_maker, response_service=service),
            settings,
        )
        assert await processor.process_once() == 1

    anyio.run(run_flow)

    async def inspect_outbound() -> list[OutboundMessage]:
        async with session_maker() as session:
            return list((await session.execute(select(OutboundMessage))).scalars().all())

    outbounds = anyio.run(inspect_outbound)
    assert sdk.chat_completions.calls == 1
    assert outbounds[0].text == "Resposta via chat completions"


def test_chat_provider_error_leaves_inbound_pending_for_retry(
    client: TestClient,
    session_maker: async_sessionmaker[AsyncSession],
    caplog,
) -> None:
    caplog.set_level("ERROR")
    assert client.post("/webhooks/evolution", json=_payload()).status_code == 200
    sdk = FakeChatSDK(FakeProviderError())
    openai_client = OpenAIResponsesClient(
        api_key=SecretStr("ollama"),
        model="llama3.1:8b",
        timeout_seconds=30,
        max_output_tokens=300,
        compat_mode="chat_completions",
        sdk_client=sdk,
    )

    async def run_flow() -> None:
        settings = _settings()
        service = CarlosResponseService(
            session_factory=session_maker,
            openai_client=openai_client,
            settings=settings,
        )
        processor = InboundMessageProcessor(
            session_maker,
            CarlosAIHandler(session_factory=session_maker, response_service=service),
            settings,
        )
        assert await processor.process_once() == 1

    anyio.run(run_flow)

    async def inspect_inbound() -> InboundMessage:
        async with session_maker() as session:
            return (await session.execute(select(InboundMessage))).scalar_one()

    inbound = anyio.run(inspect_inbound)
    assert sdk.chat_completions.calls == 1
    assert inbound.status == "pending"
    assert inbound.next_attempt_at is not None
    assert "mode=chat_completions" in caplog.text
    assert "status_code=500" in caplog.text
    assert "FakeProviderError" in caplog.text
    assert "5534999999999" not in caplog.text
    assert "sk-unsafe" not in caplog.text


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
