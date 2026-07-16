from fastapi.testclient import TestClient

from app.main import settings


def test_small_json_works(client: TestClient) -> None:
    response = client.post("/webhooks/evolution", json=_payload("BODY1"))

    assert response.status_code == 200


def test_content_length_above_limit_returns_413(client: TestClient) -> None:
    original_limit = settings.webhook_max_body_bytes
    settings.webhook_max_body_bytes = 10
    try:
        response = client.post("/webhooks/evolution", content=b'{"a": "too-large"}')
    finally:
        settings.webhook_max_body_bytes = original_limit

    assert response.status_code == 413


def test_real_body_above_limit_returns_413(client: TestClient) -> None:
    original_limit = settings.webhook_max_body_bytes
    settings.webhook_max_body_bytes = 20
    try:
        response = client.post(
            "/webhooks/evolution",
            content=b'{"event":"messages.upsert","data":"large"}',
            headers={"Content-Length": "1"},
        )
    finally:
        settings.webhook_max_body_bytes = original_limit

    assert response.status_code == 413


def test_empty_body_keeps_invalid_json_treatment(client: TestClient) -> None:
    response = client.post("/webhooks/evolution", content=b"")

    assert response.status_code == 400


def _payload(message_id: str) -> dict[str, object]:
    return {
        "event": "messages.upsert",
        "instance": "turatti-barbe",
        "data": {
            "key": {
                "id": message_id,
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {"conversation": "Ola"},
        },
    }
