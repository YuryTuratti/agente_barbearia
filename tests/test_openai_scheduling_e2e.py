from datetime import UTC, date, datetime, time
from types import SimpleNamespace

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.database.models import Appointment, InboundMessage, OutboundMessage
from app.handlers.carlos_scheduling_handler import CarlosSchedulingHandler
from app.schemas.openai_response import OpenAIResponseTurn, OpenAIToolCall
from app.services.carlos_scheduling_service import CarlosSchedulingService
from app.services.inbound_message_processor import InboundMessageProcessor
from app.services.outbound_message_processor import OutboundMessageProcessor
from app.services.scheduling_service import SchedulingService
from app.tools.scheduling_executor import SchedulingToolExecutor
from app.workers import inbound_message_worker, outbound_message_worker
from tests.scheduling_helpers import FakeClock, add_hours, add_service


class SequencedOpenAIClient:
    def __init__(self, turns: list[OpenAIResponseTurn]) -> None:
        self.turns = turns
        self.calls = 0
        self.closed = False

    async def create_tool_turn(self, **kwargs):
        self.calls += 1
        return self.turns.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeEvolutionClient:
    def __init__(self) -> None:
        self.calls = 0

    async def send_text(self, *, instance: str, recipient: str, text: str):
        self.calls += 1
        return SimpleNamespace(success=True, external_message_id="evo-1", status_code=200)


@pytest.mark.parametrize(
    ("message_text", "turn_factory", "create_existing_appointment"),
    [
        (
            "Quais serviços vocês oferecem?",
            lambda service_id: [_tool("call_1", "list_services", "{}"), _final("Temos Corte.")],
            False,
        ),
        (
            "Tem horário no dia 10 para corte?",
            lambda service_id: [
                _tool("call_1", "list_services", "{}"),
                _tool(
                    "call_2",
                    "list_available_slots",
                    f'{{"local_date": "2026-07-10", "service_ids": ["{service_id}"]}}',
                ),
                _final("Tem horários disponíveis às 08:00."),
            ],
            False,
        ),
        (
            "Quais são meus agendamentos?",
            lambda service_id: [_tool("call_1", "list_my_appointments", "{}"), _final("Você tem um horário agendado.")],
            True,
        ),
    ],
)
def test_openai_scheduling_local_e2e_read_only(
    client: TestClient,
    session_maker: async_sessionmaker[AsyncSession],
    message_text: str,
    turn_factory,
    create_existing_appointment: bool,
) -> None:
    fake_evolution = FakeEvolutionClient()

    async def setup() -> str:
        async with session_maker() as session:
            service = await add_service(session, slug="corte", name="Corte", duration_minutes=30)
            service_id = service.id
            await add_hours(
                session,
                instance="turatti-barbe",
                weekday=4,
                opens_at=time(8, 0),
                closes_at=time(9, 0),
            )
        if create_existing_appointment:
            async with session_maker() as session:
                scheduler = SchedulingService(
                    session,
                    settings=_settings(),
                    clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
                )
                await scheduler.create_appointment(
                    instance="turatti-barbe",
                    phone="5534999999999",
                    customer_name=None,
                    service_ids=[service_id],
                    local_date=date(2026, 7, 10),
                    local_start_time=time(8, 0),
                )
        return service_id

    service_id = anyio.run(setup)
    fake_openai = SequencedOpenAIClient(turn_factory(service_id))

    response = client.post("/webhooks/evolution", json=_payload(message_text))
    assert response.status_code == 200

    async def run_flow() -> tuple[list[InboundMessage], list[OutboundMessage], list[Appointment]]:
        settings = _settings()
        clock = FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC))
        executor = SchedulingToolExecutor(
            session_factory=session_maker,
            settings=settings,
            clock=clock,
        )
        response_service = CarlosSchedulingService(
            session_factory=session_maker,
            openai_client=fake_openai,
            tool_executor=executor,
            settings=settings,
            clock=clock,
        )
        inbound_processor = InboundMessageProcessor(
            session_maker,
            CarlosSchedulingHandler(
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
        async with session_maker() as session:
            inbounds = list((await session.execute(select(InboundMessage))).scalars().all())
            outbounds = list((await session.execute(select(OutboundMessage))).scalars().all())
            appointments = list((await session.execute(select(Appointment))).scalars().all())
            return inbounds, outbounds, appointments

    inbounds, outbounds, appointments = anyio.run(run_flow)

    assert inbounds[0].status == "completed"
    assert len(outbounds) == 1
    assert outbounds[0].status == "sent"
    assert fake_evolution.calls == 1
    assert len(appointments) == (1 if create_existing_appointment else 0)
    assert all(appointment.status == "scheduled" for appointment in appointments)


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///test.db",
        inbound_handler_mode="openai_scheduling",
        worker_poll_interval_seconds=0.01,
        worker_batch_size=1,
        worker_max_attempts=3,
        worker_retry_delay_seconds=30,
        worker_processing_timeout_seconds=300,
        outbound_worker_batch_size=1,
        outbound_worker_max_attempts=3,
        outbound_worker_retry_delay_seconds=30,
        outbound_worker_processing_timeout_seconds=300,
        scheduling_min_notice_minutes=0,
    )


def _payload(text: str) -> dict[str, object]:
    return {
        "event": "messages.upsert",
        "instance": "turatti-barbe",
        "data": {
            "key": {
                "id": f"MSG-{text}",
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "Cliente Teste",
            "message": {"conversation": text},
        },
    }


def _tool(call_id: str, name: str, arguments: str) -> OpenAIResponseTurn:
    return OpenAIResponseTurn(
        output_text=None,
        tool_calls=[OpenAIToolCall(call_id=call_id, name=name, arguments=arguments)],
        response_output_items=[
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
            }
        ],
    )


def _final(text: str) -> OpenAIResponseTurn:
    return OpenAIResponseTurn(output_text=text, tool_calls=[], response_output_items=[])
