import json
import logging

from app.core.config import Settings
from app.core.logging import JsonFormatter
from app.core.request_context import reset_request_id, set_request_id


def test_json_logs_are_valid_and_include_required_fields() -> None:
    formatter = JsonFormatter(settings=Settings(database_url="sqlite+aiosqlite:///test.db"))
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["service"] == "Carlos - Turatti Barbe"
    assert "timestamp" in payload


def test_json_logs_include_request_id_when_available() -> None:
    token = set_request_id("req-123")
    try:
        formatter = JsonFormatter(settings=Settings(database_url="sqlite+aiosqlite:///test.db"))
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
        record.request_id = "req-123"
        payload = json.loads(formatter.format(record))
    finally:
        reset_request_id(token)

    assert payload["request_id"] == "req-123"


def test_json_logs_do_not_include_secret_values() -> None:
    formatter = JsonFormatter(settings=Settings(database_url="sqlite+aiosqlite:///test.db"))
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message ok", (), None)

    payload = formatter.format(record)

    assert "CHANGE_ME" not in payload
    assert "postgresql+asyncpg://" not in payload
