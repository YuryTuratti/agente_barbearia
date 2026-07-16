import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.core.request_context import get_request_id


SAFE_LOG_RECORD_FIELDS = {
    "inbound_id",
    "outbound_id",
    "tool_name",
    "status",
}


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        request_id = get_request_id()
        if request_id is not None:
            record.request_id = request_id
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, *, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._settings.app_name,
            "environment": self._settings.app_env,
            "build_version": self._settings.app_build_version,
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        for field_name in SAFE_LOG_RECORD_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value
        if record.exc_info:
            payload["exception"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(settings.app_log_level)

    handler = logging.StreamHandler()
    handler.setLevel(settings.app_log_level)
    handler.addFilter(RequestContextFilter())
    if settings.app_json_logs:
        handler.setFormatter(JsonFormatter(settings=settings))
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    root_logger.addHandler(handler)
