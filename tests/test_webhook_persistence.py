from collections.abc import AsyncIterator

import anyio
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.connection import get_database_session
from app.database.models import InboundMessage, OutboundMessage
from app.main import app


def test_processable_new_message_returns_accepted_and_not_duplicate(
    client: TestClient,
) -> None:
    response = client.post("/webhooks/evolution", json=_payload())
    message = response.json()["message"]

    assert response.status_code == 200
    assert message["accepted_for_processing"] is True
    assert message["duplicate"] is False


def test_webhook_registers_message_as_pending_without_processing(
    client: TestClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    response = client.post("/webhooks/evolution", json=_payload())

    assert response.status_code == 200
    record = _get_single_record(session_maker)
    assert record.status == "pending"
    assert record.locked_at is None
    assert record.processed_at is None
    assert record.attempts == 0
    assert _count_outbound_records(session_maker) == 0


def test_second_equal_webhook_returns_duplicate_and_not_accepted(
    client: TestClient,
) -> None:
    first_response = client.post("/webhooks/evolution", json=_payload())
    second_response = client.post("/webhooks/evolution", json=_payload())
    message = second_response.json()["message"]

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert message["duplicate"] is True
    assert message["accepted_for_processing"] is False


def test_from_me_message_is_not_saved(
    client: TestClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    payload = _payload()
    payload["data"]["key"]["fromMe"] = True

    response = client.post("/webhooks/evolution", json=payload)

    assert response.status_code == 200
    assert response.json()["message"]["accepted_for_processing"] is False
    assert _count_records(session_maker) == 0


def test_group_message_is_not_saved(
    client: TestClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    payload = _payload()
    payload["data"]["key"]["remoteJid"] = "120363000000000000@g.us"

    response = client.post("/webhooks/evolution", json=payload)

    assert response.status_code == 200
    assert response.json()["message"]["ignore_reason"] == "group_message"
    assert _count_records(session_maker) == 0


def test_unsupported_event_is_not_saved(
    client: TestClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    payload = _payload()
    payload["event"] = "connection.update"

    response = client.post("/webhooks/evolution", json=payload)

    assert response.status_code == 200
    assert response.json()["message"]["ignore_reason"] == "unsupported_event"
    assert _count_records(session_maker) == 0


def test_message_without_id_is_not_saved(
    client: TestClient,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    payload = _payload()
    del payload["data"]["key"]["id"]

    response = client.post("/webhooks/evolution", json=payload)

    assert response.status_code == 200
    assert response.json()["message"]["ignore_reason"] == "missing_message_id"
    assert _count_records(session_maker) == 0


def test_webhook_persistence_response_does_not_include_phone_or_text(
    client: TestClient,
) -> None:
    response = client.post("/webhooks/evolution", json=_payload())
    response_text = response.text
    response_json = response.json()

    assert "5534999999999" not in response_text
    assert "Olá, gostaria de marcar um corte amanhã." not in response_text
    assert "phone" not in response_json
    assert "text" not in response_json
    assert "phone" not in response_json["message"]
    assert "text" not in response_json["message"]


def test_invalid_json_still_returns_status_400(client: TestClient) -> None:
    response = client.post(
        "/webhooks/evolution",
        content="{invalid-json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400


def test_real_database_failure_returns_status_503() -> None:
    async def failing_database_session() -> AsyncIterator[object]:
        yield _FailingSession()

    app.dependency_overrides[get_database_session] = failing_database_session
    try:
        with TestClient(app) as test_client:
            response = test_client.post("/webhooks/evolution", json=_payload())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Serviço temporariamente indisponível.",
    }


def test_duplicate_does_not_return_status_503(client: TestClient) -> None:
    client.post("/webhooks/evolution", json=_payload())
    response = client.post("/webhooks/evolution", json=_payload())

    assert response.status_code == 200
    assert response.json()["message"]["duplicate"] is True


def test_health_still_returns_online(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "online"


def _count_records(session_maker: async_sessionmaker[AsyncSession]) -> int:
    async def count() -> int:
        async with session_maker() as session:
            result = await session.execute(
                select(func.count()).select_from(InboundMessage)
            )
            return result.scalar_one()

    return anyio.run(count)


def _count_outbound_records(session_maker: async_sessionmaker[AsyncSession]) -> int:
    async def count() -> int:
        async with session_maker() as session:
            result = await session.execute(
                select(func.count()).select_from(OutboundMessage)
            )
            return result.scalar_one()

    return anyio.run(count)


def _get_single_record(
    session_maker: async_sessionmaker[AsyncSession],
) -> InboundMessage:
    async def get_record() -> InboundMessage:
        async with session_maker() as session:
            result = await session.execute(select(InboundMessage))
            return result.scalar_one()

    return anyio.run(get_record)


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
                "conversation": "Olá, gostaria de marcar um corte amanhã.",
            },
        },
    }


class _FailingSession:
    def add(self, record: object) -> None:
        return None

    async def commit(self) -> None:
        raise OperationalError(
            statement="",
            params={},
            orig=RuntimeError("database unavailable"),
        )
