import pytest

from app.core.config import Settings
from app.exceptions.openai import OpenAIPermanentError
from app.handlers.carlos_scheduling_handler import CarlosSchedulingHandler
from app.workers import inbound_message_worker


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeProcessor:
    async def process_once(self) -> int:
        return 0


def test_openai_scheduling_requires_api_key() -> None:
    with pytest.raises(OpenAIPermanentError):
        inbound_message_worker._build_handler(
            _settings(inbound_handler_mode="openai_scheduling", openai_api_key=None)
        )


def test_openai_scheduling_builds_scheduling_handler_with_injected_client() -> None:
    handler = inbound_message_worker._build_handler(
        _settings(inbound_handler_mode="openai_scheduling"),
        openai_client=FakeOpenAIClient(),
    )

    assert isinstance(handler, CarlosSchedulingHandler)


@pytest.mark.anyio
async def test_openai_scheduling_client_is_closed_on_worker_exit(monkeypatch):
    fake_client = FakeOpenAIClient()
    monkeypatch.setattr(
        inbound_message_worker,
        "InboundMessageProcessor",
        lambda **kwargs: FakeProcessor(),
    )

    exit_code = await inbound_message_worker.run_worker(
        once=True,
        processor=None,
        settings=_settings(inbound_handler_mode="openai_scheduling"),
        openai_client=fake_client,
        dispose_engine=False,
    )

    assert exit_code == 0
    assert fake_client.closed is True


def test_openai_scheduling_mode_is_allowed_and_default_remains_logging() -> None:
    assert _settings().inbound_handler_mode == "logging"
    assert _settings(inbound_handler_mode="openai_scheduling").inbound_handler_mode == "openai_scheduling"


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
    return Settings(**values)
