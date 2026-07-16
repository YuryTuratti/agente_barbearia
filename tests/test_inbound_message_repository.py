import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import InboundMessage
from app.repositories.inbound_message_repository import register_message
from app.schemas.normalized_message import NormalizedMessage


@pytest.mark.anyio
async def test_registers_new_message(db_session: AsyncSession) -> None:
    result = await register_message(db_session, _message())

    assert result.created is True
    assert result.duplicate is False
    assert result.record_id is not None


@pytest.mark.anyio
async def test_duplicate_same_instance_and_id_is_detected(
    db_session: AsyncSession,
) -> None:
    message = _message()

    first_result = await register_message(db_session, message)
    second_result = await register_message(db_session, message)

    assert first_result.created is True
    assert second_result.created is False
    assert second_result.duplicate is True
    assert second_result.record_id == first_result.record_id


@pytest.mark.anyio
async def test_same_message_id_in_different_instances_is_allowed(
    db_session: AsyncSession,
) -> None:
    first_result = await register_message(
        db_session,
        _message(instance="turatti-barbe"),
    )
    second_result = await register_message(
        db_session,
        _message(instance="outra-instancia"),
    )

    assert first_result.created is True
    assert second_result.created is True
    assert first_result.record_id != second_result.record_id


@pytest.mark.anyio
async def test_stores_phone_as_string_status_pending_and_attempts_zero(
    db_session: AsyncSession,
) -> None:
    result = await register_message(db_session, _message(phone="5534999999999"))

    statement = select(InboundMessage).where(InboundMessage.id == result.record_id)
    record = (await db_session.execute(statement)).scalar_one()

    assert record.phone == "5534999999999"
    assert isinstance(record.phone, str)
    assert record.status == "pending"
    assert record.attempts == 0


@pytest.mark.anyio
async def test_non_processable_message_cannot_be_registered(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError):
        await register_message(
            db_session,
            _message(processable=False, ignore_reason="from_me"),
        )


@pytest.mark.anyio
async def test_message_without_id_cannot_be_registered(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError):
        await register_message(db_session, _message(message_id=None))


@pytest.mark.anyio
async def test_register_message_does_not_modify_normalized_message(
    db_session: AsyncSession,
) -> None:
    message = _message()
    original_message = message.model_copy(deep=True)

    await register_message(db_session, message)

    assert message == original_message


@pytest.mark.anyio
async def test_duplicate_does_not_leave_session_unusable(
    db_session: AsyncSession,
) -> None:
    message = _message()

    await register_message(db_session, message)
    duplicate_result = await register_message(db_session, message)
    count = await _count_records(db_session)

    assert duplicate_result.duplicate is True
    assert count == 1


@pytest.mark.anyio
async def test_concurrent_duplicate_registration_creates_only_one_record(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    message = _message(message_id="CONCURRENT-1")

    async def attempt_registration() -> bool:
        async with session_maker() as session:
            result = await register_message(session, deepcopy(message))
            return result.created

    results = await asyncio.gather(attempt_registration(), attempt_registration())

    async with session_maker() as session:
        count = await _count_records(session)

    assert sorted(results) == [False, True]
    assert count == 1


async def _count_records(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(InboundMessage))
    return result.scalar_one()


def _message(
    *,
    instance: str | None = "turatti-barbe",
    message_id: str | None = "ABC123",
    phone: str | None = "5534999999999",
    processable: bool = True,
    ignore_reason: str | None = None,
) -> NormalizedMessage:
    return NormalizedMessage(
        event="messages.upsert",
        instance=instance,
        message_id=message_id,
        remote_jid="5534999999999@s.whatsapp.net",
        phone=phone,
        sender_name="Cliente Teste",
        from_me=False,
        is_group=False,
        message_type="text",
        text="Olá, gostaria de marcar um corte amanhã.",
        media_mimetype=None,
        timestamp=1_719_000_000,
        processable=processable,
        ignore_reason=ignore_reason,
    )
