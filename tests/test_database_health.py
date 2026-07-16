from fastapi.testclient import TestClient


def test_database_health_returns_connected(client: TestClient) -> None:
    response = client.get("/health/database")

    assert response.status_code == 200
    assert response.json() == {
        "status": "online",
        "database": "connected",
    }
