import inspect
import logging
import re
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from app.exceptions.openai import (
    OpenAIInvalidResponseError,
    OpenAIPermanentError,
    OpenAITemporaryError,
)
from app.schemas.conversation import ConversationMessage
from app.schemas.openai_response import OpenAIResponseTurn, OpenAITextResult, OpenAIToolCall

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
CHAT_EMPTY_FALLBACK = "Desculpa, não consegui entender bem. Pode me mandar de novo?"


class OpenAIResponsesClient:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float,
        max_output_tokens: int,
        base_url: str | None = None,
        compat_mode: str = "responses",
        sdk_client: "AsyncOpenAI | None" = None,
    ) -> None:
        if not api_key.get_secret_value().strip():
            raise OpenAIPermanentError("OpenAI API key is required.")
        if not model.strip():
            raise OpenAIPermanentError("OpenAI model is required.")
        if timeout_seconds <= 0:
            raise OpenAIPermanentError("OpenAI timeout must be greater than zero.")
        if max_output_tokens <= 0:
            raise OpenAIPermanentError(
                "OpenAI max output tokens must be greater than zero."
            )
        if compat_mode not in {"responses", "chat_completions"}:
            raise OpenAIPermanentError("OpenAI compatibility mode is invalid.")

        self._model = model
        self._max_output_tokens = max_output_tokens
        self._compat_mode = compat_mode
        self._owns_client = sdk_client is None
        if sdk_client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as error:
                raise OpenAIPermanentError("OpenAI SDK is not installed.") from error

            client_options: dict[str, Any] = {
                "api_key": api_key.get_secret_value(),
                "timeout": timeout_seconds,
            }
            if base_url:
                client_options["base_url"] = base_url
            sdk_client = AsyncOpenAI(**client_options)
        self._sdk_client = sdk_client

    async def generate_text(
        self,
        *,
        instructions: str,
        messages: list[ConversationMessage],
    ) -> OpenAITextResult:
        safe_input = [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in messages
        ]

        if self._compat_mode == "chat_completions":
            return await self._generate_chat_completion(
                instructions=instructions,
                messages=safe_input,
            )

        try:
            response = await self._sdk_client.responses.create(
                model=self._model,
                instructions=instructions,
                input=safe_input,
                max_output_tokens=self._max_output_tokens,
                store=False,
            )
        except Exception as error:
            _log_provider_error(error, mode="responses")
            raise _map_openai_error(error) from error

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise OpenAIInvalidResponseError("OpenAI returned an empty response.")

        return OpenAITextResult(
            text=output_text.strip(),
            response_id=_optional_str(getattr(response, "id", None)),
            model=_optional_str(getattr(response, "model", None)),
        )

    async def _generate_chat_completion(
        self,
        *,
        instructions: str,
        messages: list[dict[str, str]],
    ) -> OpenAITextResult:
        chat_messages = [{"role": "system", "content": instructions}, *messages]
        try:
            response = await self._sdk_client.chat.completions.create(
                model=self._model,
                messages=chat_messages,
                max_tokens=self._max_output_tokens,
            )
        except Exception as error:
            _log_provider_error(error, mode="chat_completions")
            raise _map_openai_error(error) from error

        choices = getattr(response, "choices", None) or []
        message = getattr(choices[0], "message", None) if choices else None
        content = getattr(message, "content", None)
        text = content.strip() if isinstance(content, str) else ""
        return OpenAITextResult(
            text=text or CHAT_EMPTY_FALLBACK,
            response_id=_optional_str(getattr(response, "id", None)),
            model=_optional_str(getattr(response, "model", None)),
        )

    async def create_tool_turn(
        self,
        *,
        instructions: str,
        input_items: list[object],
        tools: list[dict[str, Any]],
    ) -> OpenAIResponseTurn:
        try:
            response = await self._sdk_client.responses.create(
                model=self._model,
                instructions=instructions,
                input=input_items,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=False,
                max_output_tokens=self._max_output_tokens,
                store=False,
            )
        except Exception as error:
            _log_provider_error(error, mode="responses")
            raise _map_openai_error(error) from error

        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str):
            output_text = output_text.strip() or None
        else:
            output_text = None

        output_items = [_serialize_response_item(item) for item in _response_output(response)]
        tool_calls = [
            OpenAIToolCall(
                call_id=_required_str(_item_value(item, "call_id"), "call_id"),
                name=_required_str(_item_value(item, "name"), "name"),
                arguments=_required_str(_item_value(item, "arguments"), "arguments"),
            )
            for item in output_items
            if _item_value(item, "type") == "function_call"
        ]

        return OpenAIResponseTurn(
            output_text=output_text,
            tool_calls=tool_calls,
            response_output_items=output_items,
        )

    async def close(self) -> None:
        if not self._owns_client:
            return

        close_method = getattr(self._sdk_client, "close", None) or getattr(
            self._sdk_client,
            "aclose",
            None,
        )
        if close_method is None:
            return

        result = close_method()
        if inspect.isawaitable(result):
            await result


def _map_openai_error(error: Exception) -> Exception:
    status_code = getattr(error, "status_code", None)
    if status_code in {408, 409, 429} or (
        isinstance(status_code, int) and 500 <= status_code <= 599
    ):
        return OpenAITemporaryError(f"OpenAI returned HTTP {status_code}.")
    if status_code in {400, 401, 403, 404}:
        return OpenAIPermanentError(f"OpenAI returned HTTP {status_code}.")

    error_name = error.__class__.__name__.lower()
    if "timeout" in error_name:
        return OpenAITemporaryError("OpenAI request timed out.")
    if "connection" in error_name or "connect" in error_name:
        return OpenAITemporaryError("OpenAI connection failed.")
    if "ratelimit" in error_name or "rate_limit" in error_name:
        return OpenAITemporaryError("OpenAI returned HTTP 429.")
    if "authentication" in error_name or "permission" in error_name:
        return OpenAIPermanentError("OpenAI authentication or permission failed.")
    if "badrequest" in error_name or "notfound" in error_name:
        return OpenAIPermanentError("OpenAI request configuration is invalid.")

    return OpenAITemporaryError("OpenAI request failed.")


def _log_provider_error(error: Exception, *, mode: str) -> None:
    response = getattr(error, "response", None)
    status_code = getattr(error, "status_code", None) or getattr(
        response, "status_code", None
    )
    body = getattr(response, "text", None) if response is not None else None
    logger.error(
        "OpenAI-compatible provider request failed: mode=%s error_type=%s "
        "status_code=%s response_body=%s",
        mode,
        error.__class__.__name__,
        status_code,
        _sanitize_provider_body(body),
    )


def _sanitize_provider_body(body: object) -> str | None:
    if not isinstance(body, str) or not body.strip():
        return None
    clean = " ".join(body.split())[:500]
    clean = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", clean)
    clean = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", clean)
    clean = re.sub(r"\b\d{8,15}\b", "[REDACTED_PHONE]", clean)
    return clean


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value

    return None


def _response_output(response: object) -> list[object]:
    output = getattr(response, "output", None)
    if output is None:
        return []
    return list(output)


def _serialize_response_item(item: object) -> object:
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "__dict__"):
        return {
            key: value
            for key, value in vars(item).items()
            if not key.startswith("_")
        }
    return item


def _item_value(item: object, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _required_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OpenAIInvalidResponseError(f"OpenAI function call missing {field_name}.")
    return value
