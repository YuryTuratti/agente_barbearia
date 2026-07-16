import pytest

from app.core.config import Settings
from app.workers import outbound_message_worker


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


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def test_parse_once_argument() -> None:
    args = outbound_message_worker.parse_args(["--once"])

    assert args.once is True


@pytest.mark.anyio
async def test_once_mode_calls_only_one_cycle_and_returns_zero() -> None:
    processor = FakeProcessor([0, 0])

    exit_code = await outbound_message_worker.run_worker(
        once=True,
        processor=processor,
        settings=_settings(),
        dispose_engine=False,
    )

    assert exit_code == 0
    assert processor.calls == 1


@pytest.mark.anyio
async def test_fatal_worker_error_returns_non_zero() -> None:
    exit_code = await outbound_message_worker.run_worker(
        once=True,
        processor=FailingProcessor(),
        settings=_settings(),
        dispose_engine=False,
    )

    assert exit_code == 1


@pytest.mark.anyio
async def test_worker_closes_client_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_engine = FakeEngine()
    fake_client = FakeClient()
    monkeypatch.setattr(outbound_message_worker, "engine", fake_engine)
    monkeypatch.setattr(
        outbound_message_worker,
        "OutboundMessageProcessor",
        lambda **kwargs: FakeProcessor([0]),
    )

    exit_code = await outbound_message_worker.run_worker(
        once=True,
        evolution_client=fake_client,
        settings=_settings(),
        dispose_engine=True,
    )

    assert exit_code == 0
    assert fake_client.closed is True
    assert fake_engine.disposed is True


@pytest.mark.anyio
async def test_continuous_worker_uses_async_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = FakeProcessor([0, 0])
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr(outbound_message_worker.asyncio, "sleep", fake_sleep)

    exit_code = await outbound_message_worker.run_worker(
        once=False,
        processor=processor,
        settings=_settings(),
        dispose_engine=False,
    )

    assert exit_code == 0
    assert sleep_calls == [0.01]


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///test.db",
        outbound_worker_poll_interval_seconds=0.01,
        outbound_worker_max_attempts=3,
        outbound_worker_retry_delay_seconds=30,
        outbound_worker_processing_timeout_seconds=300,
        outbound_worker_batch_size=1,
    )
