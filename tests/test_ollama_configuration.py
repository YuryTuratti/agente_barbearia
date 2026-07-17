from pathlib import Path

from pydantic import SecretStr

from app.core.config import Settings
from app.workers import inbound_message_worker


class CapturingClient:
    def __init__(self, **kwargs) -> None:
        self.options = kwargs


def test_empty_openai_base_url_keeps_sdk_default(monkeypatch) -> None:
    monkeypatch.setattr(inbound_message_worker, "OpenAIResponsesClient", CapturingClient)
    client = inbound_message_worker._build_openai_client(
        Settings(openai_api_key=SecretStr("ollama"), openai_base_url="")
    )

    assert client.options["base_url"] is None
    assert client.options["compat_mode"] == "responses"


def test_openai_base_url_is_forwarded(monkeypatch) -> None:
    monkeypatch.setattr(inbound_message_worker, "OpenAIResponsesClient", CapturingClient)
    client = inbound_message_worker._build_openai_client(
        Settings(
            openai_api_key=SecretStr("ollama"),
            openai_base_url="http://ollama:11434/v1",
            openai_model="llama3.1:8b",
        )
    )

    assert client.options["base_url"] == "http://ollama:11434/v1"
    assert client.options["model"] == "llama3.1:8b"
    assert client.options["api_key"].get_secret_value() == "ollama"
    assert client.options["compat_mode"] == "chat_completions"


def test_explicit_responses_overrides_ollama_auto_detection() -> None:
    settings = Settings(
        openai_base_url="http://ollama:11434/v1",
        openai_compat_mode="responses",
    )

    assert settings.openai_compat_mode == "responses"


def test_examples_contain_placeholders_only() -> None:
    for path in (".env.example", ".env.production.example", ".env.vps-test.example"):
        content = Path(path).read_text(encoding="utf-8")
        assert "sk-" not in content
        assert "5534999999999" not in content
