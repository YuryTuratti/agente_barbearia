from fastapi.testclient import TestClient


def test_health_returns_status_200(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200


def test_health_returns_online_status(client: TestClient) -> None:
    response = client.get("/health")

    assert response.json()["status"] == "online"


def test_valid_webhook_returns_status_200(client: TestClient) -> None:
    response = client.post("/webhooks/evolution", json=_webhook_payload())

    assert response.status_code == 200


def test_valid_webhook_returns_received_true(client: TestClient) -> None:
    response = client.post("/webhooks/evolution", json=_webhook_payload())

    assert response.json()["received"] is True


def test_valid_webhook_response_contains_message_processable(
    client: TestClient,
) -> None:
    response = client.post("/webhooks/evolution", json=_webhook_payload())

    assert response.json()["message"]["processable"] is True


def test_valid_webhook_response_does_not_include_text_or_phone(
    client: TestClient,
) -> None:
    response = client.post("/webhooks/evolution", json=_webhook_payload())
    response_json = response.json()
    response_text = response.text

    assert "Olá, gostaria de marcar um corte amanhã." not in response_text
    assert "5534999999999" not in response_text
    assert "phone" not in response_json
    assert "text" not in response_json
    assert "phone" not in response_json["message"]
    assert "text" not in response_json["message"]


def test_invalid_json_webhook_returns_status_400(client: TestClient) -> None:
    response = client.post(
        "/webhooks/evolution",
        content="{invalid-json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "O corpo da requisição não contém um JSON válido."
    }


def _webhook_payload() -> dict[str, object]:
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
