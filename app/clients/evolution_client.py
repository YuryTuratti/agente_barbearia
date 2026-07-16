from typing import Any
from urllib.parse import quote

import httpx

from app.exceptions.evolution import EvolutionPermanentError, EvolutionTemporaryError
from app.schemas.outbound_message import EvolutionSendResult


class EvolutionClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        send_text_path: str,
        timeout_seconds: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url.strip():
            raise EvolutionPermanentError("Evolution API base URL is required.")
        if not send_text_path.strip():
            raise EvolutionPermanentError("Evolution API send text path is required.")
        if timeout_seconds <= 0:
            raise EvolutionPermanentError("Evolution API timeout must be greater than zero.")

        self._base_url = base_url.rstrip("/") + "/"
        self._api_key = api_key
        self._send_text_path = send_text_path
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def send_text(
        self,
        *,
        instance: str,
        recipient: str,
        text: str,
    ) -> EvolutionSendResult:
        clean_instance = instance.strip()
        clean_recipient = recipient.strip()
        clean_text = text.strip()

        if not clean_instance:
            raise EvolutionPermanentError("Evolution API instance is required.")
        if not clean_recipient or not clean_recipient.isdigit():
            raise EvolutionPermanentError("Evolution API recipient is invalid.")
        if not clean_text:
            raise EvolutionPermanentError("Evolution API text is required.")

        escaped_instance = quote(clean_instance, safe="")
        path = self._send_text_path.replace("{instance}", escaped_instance).lstrip("/")
        url = httpx.URL(self._base_url).join(path)

        try:
            response = await self._http_client.post(
                url,
                headers={
                    "apikey": self._api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "number": clean_recipient,
                    "text": clean_text,
                },
            )
        except httpx.TimeoutException as error:
            raise EvolutionTemporaryError("Evolution API request timed out.") from error
        except httpx.ConnectError as error:
            raise EvolutionTemporaryError("Evolution API connection failed.") from error
        except httpx.TransportError as error:
            raise EvolutionTemporaryError("Evolution API transport failed.") from error

        if response.status_code in {408, 429} or 500 <= response.status_code <= 599:
            raise EvolutionTemporaryError(
                f"Evolution API returned HTTP {response.status_code}."
            )
        if 400 <= response.status_code <= 499:
            raise EvolutionPermanentError(
                f"Evolution API returned HTTP {response.status_code}."
            )

        return EvolutionSendResult(
            success=True,
            external_message_id=_extract_external_message_id(response),
            status_code=response.status_code,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._http_client.aclose()


def _extract_external_message_id(response: httpx.Response) -> str | None:
    try:
        response_json = response.json()
    except ValueError:
        return None

    if not isinstance(response_json, dict):
        return None

    key = response_json.get("key")
    if isinstance(key, dict):
        key_id = key.get("id")
        if isinstance(key_id, str) and key_id:
            return key_id

    for field_name in ("messageId", "id"):
        value: Any = response_json.get(field_name)
        if isinstance(value, str) and value:
            return value

    return None
