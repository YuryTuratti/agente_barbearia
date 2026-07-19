import logging

import httpx
from pydantic import SecretStr

from app.exceptions.openai import OpenAIPermanentError, OpenAITemporaryError
from app.schemas.conversation import ConversationMessage
from app.schemas.openai_response import OpenAITextResult

logger = logging.getLogger(__name__)

CHAT_EMPTY_FALLBACK = "Desculpa, não consegui entender bem. Pode me mandar de novo?"


class OllamaCloudClient:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout_seconds: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.get_secret_value().strip():
            raise OpenAIPermanentError("Ollama API key is required.")
        if not base_url.strip() or not model.strip():
            raise OpenAIPermanentError("Ollama base URL and model are required.")
        if timeout_seconds <= 0:
            raise OpenAIPermanentError("Ollama timeout must be greater than zero.")

        self._model = model.strip()
        self._url = f"{base_url.rstrip('/')}/api/chat"
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)
        self._headers = {
            "Authorization": f"Bearer {api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        logger.info(
            "LLM client configured: provider=ollama_cloud model=%s timeout_seconds=%s",
            self._model,
            timeout_seconds,
        )

    async def generate_text(
        self,
        *,
        instructions: str,
        messages: list[ConversationMessage],
    ) -> OpenAITextResult:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": instructions},
                *[
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
            ],
            "stream": False,
            "options": {"temperature": 0.2},
        }
        try:
            response = await self._http_client.post(
                self._url,
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except (TimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.TransportError) as error:
            logger.warning("Ollama Cloud request failed temporarily: error_type=%s", type(error).__name__)
            raise OpenAITemporaryError("Ollama Cloud request failed temporarily.") from error
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            logger.warning("Ollama Cloud HTTP error: status_code=%s", status_code)
            if status_code in {408, 409, 425, 429} or status_code >= 500:
                raise OpenAITemporaryError("Ollama Cloud request failed temporarily.") from error
            raise OpenAIPermanentError("Ollama Cloud request was rejected.") from error
        except (ValueError, TypeError) as error:
            logger.warning("Ollama Cloud returned invalid JSON: error_type=%s", type(error).__name__)
            raise OpenAITemporaryError("Ollama Cloud returned an invalid response.") from error

        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        text = content.strip() if isinstance(content, str) else ""
        return OpenAITextResult(
            text=text or CHAT_EMPTY_FALLBACK,
            response_id=None,
            model=self._model,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._http_client.aclose()
