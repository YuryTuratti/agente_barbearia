from fastapi.testclient import TestClient

from app.core.config import Settings
from app.security import webhook_auth
from app.security.webhook_auth import compare_webhook_secret


def test_compare_webhook_secret_uses_safe_comparison() -> None:
    assert compare_webhook_secret("a", "a") is True
    assert compare_webhook_secret("a", "b") is False


def test_auth_disabled_preserves_webhook_behavior(client: TestClient) -> None:
    response = client.post("/webhooks/evolution", json=_payload())

    assert response.status_code == 200


def test_correct_header_allows_request(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(webhook_auth, "get_settings", lambda: _settings())

    response = client.post(
        "/webhooks/evolution",
        json=_payload(),
        headers={"x-webhook-secret": "secret"},
    )

    assert response.status_code == 200


def test_missing_header_blocks_before_database(monkeypatch) -> None:
    monkeypatch.setattr(webhook_auth, "get_settings", lambda: _settings())

    with TestClient(__import__("app.main").main.app) as test_client:
        response = test_client.post("/webhooks/evolution", json=_payload())

    assert response.status_code == 403
    assert "secret" not in response.text


def test_wrong_header_blocks(monkeypatch) -> None:
    monkeypatch.setattr(webhook_auth, "get_settings", lambda: _settings())

    with TestClient(__import__("app.main").main.app) as test_client:
        response = test_client.post(
            "/webhooks/evolution",
            json=_payload(),
            headers={"x-webhook-secret": "wrong"},
        )

    assert response.status_code == 403
    assert "secret" not in response.text


def test_configurable_header_name_works(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        webhook_auth,
        "get_settings",
        lambda: _settings(evolution_webhook_secret_header="x-custom-secret"),
    )

    response = client.post(
        "/webhooks/evolution",
        json=_payload(),
        headers={"x-custom-secret": "secret"},
    )

    assert response.status_code == 200


def _settings(**overrides: object) -> Settings:
    values = {
        "database_url": "sqlite+aiosqlite:///test.db",
        "evolution_webhook_auth_enabled": True,
        "evolution_webhook_secret": "secret",
    }
    values.update(overrides)
    return Settings(**values)


def _payload() -> dict[str, object]:
    return {
        "event": "messages.upsert",
        "instance": "turatti-barbe",
        "data": {
            "key": {
                "id": "AUTH123",
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {"conversation": "Ola"},
        },
    }
