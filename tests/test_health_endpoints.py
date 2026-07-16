from fastapi.testclient import TestClient

from app import main


def test_live_returns_online_without_database(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "online", "service": "api"}


def test_ready_returns_ready_when_service_passes(client: TestClient, monkeypatch) -> None:
    async def passing_check(session) -> None:
        return None

    monkeypatch.setattr(main, "check_database_ready", passing_check)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "connected",
        "migrations": "up_to_date",
    }


def test_ready_returns_503_with_generic_message(client: TestClient, monkeypatch) -> None:
    async def failing_check(session) -> None:
        raise RuntimeError("sensitive sql details")

    monkeypatch.setattr(main, "check_database_ready", failing_check)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert "sensitive" not in response.text


def test_info_returns_safe_fields(client: TestClient) -> None:
    response = client.get("/info")

    assert response.status_code == 200
    assert set(response.json()) == {"service", "environment", "version"}
