from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.database.models import CarlosConversationState, InboundMessage, OutboundMessage
from app.services.carlos_conversation_context import _merge_state, prepare_carlos_context


TODAY = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def test_state_keeps_service_and_advances_after_professional() -> None:
    state = _merge_state({}, "quero marcar um corte", None, TODAY.date())
    state["last_question_asked"] = "Com qual barbeiro você prefere: Lucas ou Daniel?"
    state = _merge_state(state, "Lucas", None, TODAY.date())

    assert state["requested_service"] == "Corte Social"
    assert state["requested_professional"] == "Lucas"
    assert state["resource_key"] == "main"
    assert state["awaiting_field"] == "date"


def test_state_never_erases_existing_fields() -> None:
    state = _merge_state(
        {"requested_service": "Corte Social"}, "amanhã", None, TODAY.date()
    )
    assert state["requested_service"] == "Corte Social"
    assert state["requested_date"] == "2026-07-24"


def test_state_keeps_date_and_period_when_professional_arrives_later() -> None:
    state = _merge_state({}, "amanhã de manhã", None, TODAY.date())
    state = _merge_state(state, "com Daniel", None, TODAY.date())

    assert state["requested_date"] == "2026-07-24"
    assert state["requested_period"] == "morning"
    assert state["requested_professional"] == "Daniel"
    assert state["awaiting_field"] == "service"


def test_state_keeps_professional_when_date_arrives_later() -> None:
    state = _merge_state({}, "com Lucas", None, TODAY.date())
    state = _merge_state(state, "terça de tarde", None, TODAY.date())

    assert state["requested_professional"] == "Lucas"
    assert state["resource_key"] == "main"
    assert state["requested_period"] == "afternoon"
    assert state["requested_date"] == "2026-07-28"


@pytest.mark.anyio
async def test_buffer_fragments_are_one_current_entry_and_fill_state(session_maker) -> None:
    deadline = TODAY + timedelta(seconds=30)
    fragments = ["quero cortar", "com Lucas", "amanhã", "de manhã"]
    messages = [
        InboundMessage(
            instance="o-original", message_id=f"m{index}", phone="5534999999999",
            message_type="text", text=text,
            status="completed" if index < 3 else "processing",
            process_after_at=deadline, created_at=TODAY + timedelta(seconds=index),
        )
        for index, text in enumerate(fragments)
    ]
    async with session_maker() as session:
        session.add_all(messages)
        await session.commit()

    context = await prepare_carlos_context(
        session_maker, messages[-1],
        Settings(carlos_history_message_limit=40), now_utc=TODAY,
    )

    assert context.current_text == "quero cortar com Lucas amanhã de manhã"
    assert context.history == []
    assert context.state["requested_service"] == "Corte Social"
    assert context.state["requested_professional"] == "Lucas"
    assert context.state["resource_key"] == "main"
    assert context.state["requested_date"] == "2026-07-24"
    assert context.state["requested_period"] == "morning"
    assert context.state["awaiting_field"] == "availability"
    assert "ESTADO ATUAL DO ATENDIMENTO:" in context.instructions_context
    assert "- Serviço: Corte Social" in context.instructions_context


@pytest.mark.anyio
async def test_history_limit_uses_carlos_setting_and_long_conversation_has_summary(
    session_maker,
) -> None:
    current = InboundMessage(
        instance="o-original", message_id="current", phone="5534999999999",
        message_type="text", text="amanhã", status="processing", created_at=TODAY,
    )
    async with session_maker() as session:
        for index in range(45):
            session.add(InboundMessage(
                instance="o-original", message_id=f"old-{index}",
                phone="5534999999999", message_type="text", text=f"mensagem {index}",
                status="completed", created_at=TODAY - timedelta(minutes=45-index),
            ))
        session.add(current)
        await session.commit()

    context = await prepare_carlos_context(
        session_maker, current,
        Settings(
            carlos_history_message_limit=40,
            carlos_conversation_summary_enabled=True,
        ),
        now_utc=TODAY,
    )

    assert len(context.history) == 40
    assert context.history[0].content == "mensagem 5"
    assert "RESUMO DA CONVERSA ANTERIOR:" in context.instructions_context
    async with session_maker() as session:
        saved = await session.scalar(select(CarlosConversationState))
        assert saved is not None and saved.summary


@pytest.mark.anyio
async def test_last_question_is_preserved_in_explicit_prompt(session_maker) -> None:
    current = InboundMessage(
        instance="o-original", message_id="current-question", phone="5534999999999",
        message_type="text", text="Lucas", status="processing", created_at=TODAY,
    )
    async with session_maker() as session:
        session.add(InboundMessage(
            instance="o-original", message_id="service", phone="5534999999999",
            message_type="text", text="quero marcar um corte", status="completed",
            created_at=TODAY - timedelta(minutes=2),
        ))
        session.add(OutboundMessage(
            inbound_message_id=None, deduplication_key="question", instance="o-original",
            recipient="5534999999999", message_type="text",
            text="Com qual barbeiro você prefere: Lucas ou Daniel?", status="sent",
            created_at=TODAY - timedelta(minutes=1),
        ))
        session.add(current)
        await session.commit()

    # The persisted state represents data extracted on the prior turn.
    async with session_maker() as session:
        session.add(CarlosConversationState(
            instance="o-original", phone="5534999999999",
            state={"requested_service": "Corte Social"},
        ))
        await session.commit()
    context = await prepare_carlos_context(
        session_maker, current, Settings(), now_utc=TODAY
    )

    assert context.state["requested_service"] == "Corte Social"
    assert context.state["requested_professional"] == "Lucas"
    assert context.state["awaiting_field"] == "date"
    assert "Com qual barbeiro" in context.instructions_context
