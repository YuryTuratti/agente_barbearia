import pytest

from app.core.config import Settings
from app.exceptions.openai import OpenAIPermanentError
from app.handlers.carlos_scheduling_handler import CarlosSchedulingHandler
from app.handlers.carlos_scheduling_write_handler import CarlosSchedulingWriteHandler
from app.workers import inbound_message_worker


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeProcessor:
    async def process_once(self) -> int:
        return 0


def test_write_mode_requires_api_key() -> None:
    with pytest.raises(OpenAIPermanentError):
        inbound_message_worker._build_handler(
            _settings(inbound_handler_mode="openai_scheduling_write", openai_api_key=None)
        )


def test_write_mode_builds_write_handler_and_read_mode_stays_read_handler() -> None:
    write_handler = inbound_message_worker._build_handler(
        _settings(inbound_handler_mode="openai_scheduling_write"),
        openai_client=FakeOpenAIClient(),
    )
    read_handler = inbound_message_worker._build_handler(
        _settings(inbound_handler_mode="openai_scheduling"),
        openai_client=FakeOpenAIClient(),
    )

    assert isinstance(write_handler, CarlosSchedulingWriteHandler)
    assert isinstance(read_handler, CarlosSchedulingHandler)


@pytest.mark.anyio
async def test_write_mode_closes_openai_client(monkeypatch):
    fake_client = FakeOpenAIClient()
    monkeypatch.setattr(
        inbound_message_worker,
        "InboundMessageProcessor",
        lambda **kwargs: FakeProcessor(),
    )

    exit_code = await inbound_message_worker.run_worker(
        once=True,
        processor=None,
        settings=_settings(inbound_handler_mode="openai_scheduling_write"),
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
    return Settings(**values)
