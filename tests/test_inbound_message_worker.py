import pytest

from app.core.config import Settings
from app.exceptions.openai import OpenAIPermanentError
from app.handlers.carlos_ai_handler import CarlosAIHandler
from app.handlers.logging_message_handler import LoggingMessageHandler
from app.handlers.test_reply_handler import TestReplyHandler
from app.clients.ollama_cloud_client import OllamaCloudClient
from app.workers import inbound_message_worker


class FakeProcessor:
    def __init__(self, counts: list[int] | None = None) -> None:
        self.counts = counts or [0]
        self.calls = 0

    async def process_once(self) -> int:
        self.calls += 1
        index = min(self.calls - 1, len(self.counts) - 1)
        return self.counts[index]


class FailingProcessor:
    async def process_once(self) -> int:
        raise RuntimeError("fatal worker error")


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_parse_once_argument() -> None:
    args = inbound_message_worker.parse_args(["--once"])

    assert args.once is True


def test_default_handler_mode_is_logging() -> None:
    assert _settings().inbound_handler_mode == "logging"
    assert isinstance(
        inbound_message_worker._build_handler(_settings()),
        LoggingMessageHandler,
    )


def test_test_reply_mode_builds_test_reply_handler() -> None:
    assert isinstance(
        inbound_message_worker._build_handler(_settings(inbound_handler_mode="test_reply")),
        TestReplyHandler,
    )


def test_logging_and_test_reply_do_not_require_openai_key() -> None:
    assert isinstance(
        inbound_message_worker._build_handler(_settings(openai_api_key=None)),
        LoggingMessageHandler,
    )
    assert isinstance(
        inbound_message_worker._build_handler(
            _settings(inbound_handler_mode="test_reply", openai_api_key=None)
        ),
        TestReplyHandler,
    )


def test_openai_text_requires_api_key() -> None:
    with pytest.raises(OpenAIPermanentError):
        inbound_message_worker._build_handler(
            _settings(inbound_handler_mode="openai_text", openai_api_key=None)
        )


def test_openai_text_builds_carlos_handler_with_injected_client() -> None:
    handler = inbound_message_worker._build_handler(
        _settings(inbound_handler_mode="openai_text"),
        openai_client=FakeOpenAIClient(),
    )

    assert isinstance(handler, CarlosAIHandler)


def test_openai_text_uses_openai_provider_by_default(monkeypatch) -> None:
    sentinel = FakeOpenAIClient()
    monkeypatch.setattr(inbound_message_worker, "_build_openai_client", lambda settings: sentinel)

    assert inbound_message_worker._build_text_client(_settings()) is sentinel


def test_openai_text_builds_ollama_cloud_provider() -> None:
    client = inbound_message_worker._build_text_client(
        _settings(llm_provider="ollama_cloud", ollama_api_key="ollama-key")
    )

    assert isinstance(client, OllamaCloudClient)


def test_ollama_cloud_requires_its_api_key() -> None:
    with pytest.raises(OpenAIPermanentError):
        inbound_message_worker._build_text_client(
            _settings(llm_provider="ollama_cloud", ollama_api_key=None)
        )


def test_scheduling_keeps_official_openai_when_text_provider_is_ollama(monkeypatch) -> None:
    sentinel = FakeOpenAIClient()
    monkeypatch.setattr(inbound_message_worker, "_build_openai_client", lambda settings: sentinel)

    inbound_message_worker._build_handler(
        _settings(inbound_handler_mode="openai_scheduling", llm_provider="ollama_cloud")
    )

    assert sentinel is not None


@pytest.mark.anyio
async def test_once_mode_calls_only_one_cycle() -> None:
    processor = FakeProcessor([0, 0])

    exit_code = await inbound_message_worker.run_worker(
        once=True,
        processor=processor,
        settings=_settings(),
        dispose_engine=False,
    )

    assert exit_code == 0
    assert processor.calls == 1


@pytest.mark.anyio
async def test_once_mode_exits_successfully() -> None:
    exit_code = await inbound_message_worker.run_worker(
        once=True,
        processor=FakeProcessor([1]),
        settings=_settings(),
        dispose_engine=False,
    )

    assert exit_code == 0


@pytest.mark.anyio
async def test_fatal_worker_error_returns_non_zero() -> None:
    exit_code = await inbound_message_worker.run_worker(
        once=True,
        processor=FailingProcessor(),
        settings=_settings(),
        dispose_engine=False,
    )

    assert exit_code == 1


@pytest.mark.anyio
async def test_worker_does_not_need_postgresql_when_processor_is_injected() -> None:
    processor = FakeProcessor([0])

    exit_code = await inbound_message_worker.run_worker(
        once=True,
        processor=processor,
        settings=_settings(),
        dispose_engine=False,
    )

    assert exit_code == 0
    assert processor.calls == 1


@pytest.mark.anyio
async def test_worker_disposes_engine_on_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_engine = FakeEngine()
    monkeypatch.setattr(inbound_message_worker, "engine", fake_engine)

    exit_code = await inbound_message_worker.run_worker(
        once=True,
        processor=FakeProcessor([0]),
        settings=_settings(),
        dispose_engine=True,
    )

    assert exit_code == 0
    assert fake_engine.disposed is True


@pytest.mark.anyio
async def test_openai_client_is_closed_on_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeOpenAIClient()
    monkeypatch.setattr(
        inbound_message_worker,
        "CarlosResponseService",
        lambda **kwargs: _FakeClosableService(fake_client),
    )
    monkeypatch.setattr(
        inbound_message_worker,
        "InboundMessageProcessor",
        lambda **kwargs: FakeProcessor([0]),
    )

    exit_code = await inbound_message_worker.run_worker(
        once=True,
        processor=None,
        settings=_settings(inbound_handler_mode="openai_text"),
        openai_client=fake_client,
        dispose_engine=False,
    )

    assert exit_code == 0
    assert fake_client.closed is True


def _settings(**overrides: object) -> Settings:
    values = {
        "database_url": "sqlite+aiosqlite:///test.db",
        "worker_poll_interval_seconds": 0.01,
        "worker_max_attempts": 3,
        "worker_retry_delay_seconds": 30,
        "worker_processing_timeout_seconds": 300,
        "worker_batch_size": 1,
        "openai_api_key": "test-key",
    }
    values.update(overrides)
    return Settings(
        **values,
    )


class _FakeClosableService:
    def __init__(self, client: FakeOpenAIClient) -> None:
        self.client = client

    async def generate_reply(self, message):
        return "ok"

    async def close(self) -> None:
        await self.client.close()
