import logging
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from fastapi.testclient import TestClient

from app.core.request_context import get_request_id
from app.main import app


def test_generates_uuid_when_absent(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    UUID(response.headers["X-Request-ID"])


def test_preserves_safe_request_id(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "safe-id-123"})

    assert response.headers["X-Request-ID"] == "safe-id-123"


def test_replaces_invalid_request_id(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "bad id"})

    assert response.headers["X-Request-ID"] != "bad id"
    UUID(response.headers["X-Request-ID"])


def test_request_context_is_clean_after_request(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert get_request_id() is None


def test_concurrent_requests_do_not_mix_ids() -> None:
    def request_with_id(request_id: str) -> str:
        with TestClient(app) as test_client:
            return test_client.get(
                "/health/live",
                headers={"X-Request-ID": request_id},
            ).headers["X-Request-ID"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request_with_id, ["req-a", "req-b"]))

    assert sorted(results) == ["req-a", "req-b"]


def test_request_id_appears_in_logs(client: TestClient, caplog) -> None:
    with caplog.at_level(logging.INFO):
        response = client.get("/health/live", headers={"X-Request-ID": "log-id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "log-id"
