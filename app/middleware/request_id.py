import re
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_context import reset_request_id, set_request_id


REQUEST_ID_HEADER = "X-Request-ID"
SAFE_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def is_safe_request_id(value: str) -> bool:
    return bool(SAFE_REQUEST_ID_PATTERN.fullmatch(value))


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        received_request_id = request.headers.get(REQUEST_ID_HEADER)
        request_id = (
            received_request_id
            if received_request_id and is_safe_request_id(received_request_id)
            else str(uuid4())
        )
        token = set_request_id(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            reset_request_id(token)
