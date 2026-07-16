from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings


class WebhookBodyLimitMiddleware:
    def __init__(self, app, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/webhooks/evolution":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length.decode("ascii")) > self.settings.webhook_max_body_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                pass

        received = 0
        cached_messages: list[dict[str, object]] = []
        more_body = True
        while more_body:
            message = await receive()
            cached_messages.append(message)
            body = message.get("body", b"")
            if isinstance(body, bytes):
                received += len(body)
            if received > self.settings.webhook_max_body_bytes:
                await self._reject(scope, receive, send)
                return
            more_body = bool(message.get("more_body", False))

        async def replay_receive() -> dict[str, object]:
            if cached_messages:
                return cached_messages.pop(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    async def _reject(self, scope, receive, send) -> None:
        response = JSONResponse(
            {"detail": "Payload too large."},
            status_code=413,
        )
        await response(scope, receive, send)
