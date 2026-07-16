import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def test_development_defaults_keep_docs_enabled() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///test.db")

    assert settings.app_env == "development"
    assert settings.app_enable_docs is True


def test_production_disables_docs_when_not_explicit() -> None:
    settings = Settings(app_env="production", database_url="sqlite+aiosqlite:///test.db")

    assert settings.app_enable_docs is False


def test_production_can_enable_docs_explicitly() -> None:
    settings = Settings(
        app_env="production",
        app_enable_docs=True,
        database_url="sqlite+aiosqlite:///test.db",
    )

    assert settings.app_enable_docs is True


def test_webhook_secret_required_when_auth_enabled() -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="sqlite+aiosqlite:///test.db",
            evolution_webhook_auth_enabled=True,
            evolution_webhook_secret=None,
        )


def test_webhook_auth_disabled_does_not_require_secret() -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///test.db",
        evolution_webhook_auth_enabled=False,
        evolution_webhook_secret=None,
    )

    assert settings.evolution_webhook_secret is None


def test_body_limit_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite+aiosqlite:///test.db", webhook_max_body_bytes=0)


def test_invalid_pool_size_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite+aiosqlite:///test.db", database_pool_size=0)


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite+aiosqlite:///test.db", app_log_level="TRACE")


def test_secret_values_are_masked_in_repr() -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///test.db",
        openai_api_key=SecretStr("secret-openai"),
        gemini_api_key=SecretStr("secret-gemini"),
    )

    assert "secret-openai" not in repr(settings)
    assert "secret-gemini" not in repr(settings)


def test_env_production_example_has_no_real_credentials() -> None:
    with open(".env.production.example", encoding="utf-8") as env_file:
        content = env_file.read()

    assert "CHANGE_ME" in content
    assert "sk-" not in content
    assert "AIza" not in content
