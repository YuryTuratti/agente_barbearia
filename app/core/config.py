from functools import lru_cache
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ALLOWED_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


class Settings(BaseSettings):
    app_name: str = "Carlos - Turatti Barbe"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_log_level: str = "INFO"
    app_json_logs: bool = False
    app_enable_docs: bool = True
    app_build_version: str = "development"
    database_url: str = (
        "postgresql+asyncpg://postgres:CHANGE_ME@localhost:5432/agente_barbearia"
    )
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout_seconds: float = 30.0
    database_pool_recycle_seconds: int = 1800
    database_pool_pre_ping: bool = True
    worker_poll_interval_seconds: float = 2.0
    worker_max_attempts: int = 3
    worker_retry_delay_seconds: int = 30
    worker_processing_timeout_seconds: int = 300
    worker_batch_size: int = 1
    inbound_message_buffer_seconds: int = 30
    inbound_handler_mode: str = "logging"
    evolution_api_base_url: str = "http://localhost:8080"
    evolution_api_key: str = "CHANGE_ME"
    evolution_webhook_auth_enabled: bool = False
    evolution_webhook_secret: SecretStr | None = None
    evolution_webhook_secret_header: str = "x-webhook-secret"
    evolution_send_text_path: str = "/message/sendText/{instance}"
    evolution_request_timeout_seconds: float = 15.0
    webhook_max_body_bytes: int = 1_000_000
    graceful_shutdown_timeout_seconds: float = 30.0
    outbound_worker_poll_interval_seconds: float = 2.0
    outbound_worker_max_attempts: int = 5
    outbound_worker_retry_delay_seconds: int = 30
    outbound_worker_processing_timeout_seconds: int = 300
    outbound_worker_batch_size: int = 5
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    openai_compat_mode: str = "responses"
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 30.0
    openai_max_output_tokens: int = 300
    openai_history_limit: int = 12
    carlos_history_message_limit: int = 40
    carlos_conversation_summary_enabled: bool = True
    openai_max_reply_characters: int = 1200
    openai_max_tool_rounds: int = 5
    llm_provider: str = "openai"
    ollama_api_key: SecretStr | None = None
    ollama_base_url: str = "https://ollama.com"
    ollama_model: str = "gpt-oss:120b"
    ollama_timeout_seconds: float = 120.0
    inbound_allowed_phones: str = ""
    inbound_audio_transcription_enabled: bool = False
    inbound_image_analysis_enabled: bool = False
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    openai_transcription_timeout_seconds: float = 60.0
    openai_transcription_language: str | None = "pt"
    openai_transcription_prompt: str | None = None
    openai_transcription_max_characters: int = 4000
    gemini_api_key: SecretStr | None = None
    gemini_image_model: str = "gemini-2.5-flash"
    gemini_image_timeout_seconds: float = 60.0
    gemini_image_max_output_tokens: int = 800
    gemini_image_temperature: float = 0.1
    media_max_audio_bytes: int = 15_000_000
    media_max_image_bytes: int = 10_000_000
    media_download_timeout_seconds: float = 30.0
    media_max_download_redirects: int = 3
    media_processing_max_attempts: int = 3
    media_processing_retry_delay_seconds: int = 30
    media_processing_timeout_seconds: int = 300
    evolution_media_base64_path: str = "/chat/getBase64FromMediaMessage/{instance}"
    image_analysis_max_features: int = 8
    image_analysis_max_summary_characters: int = 1000
    image_analysis_max_context_characters: int = 1600
    barbershop_instance: str = "o-original-barbershop"
    barbershop_timezone: str = "America/Sao_Paulo"
    default_resource_key: str = "main"
    scheduling_min_notice_minutes: int = 30
    scheduling_max_days_ahead: int = 90
    scheduling_slot_interval_minutes: int = 10
    scheduling_confirmation_code_length: int = 8
    scheduling_max_services_per_appointment: int = 5
    scheduling_confirmation_ttl_minutes: int = 15
    scheduling_pending_action_error_max_length: int = 500
    admin_dashboard_enabled: bool = False
    admin_dashboard_username: str | None = None
    admin_dashboard_password: SecretStr | None = None

    @field_validator(
        "worker_poll_interval_seconds",
        "worker_max_attempts",
        "worker_retry_delay_seconds",
        "worker_processing_timeout_seconds",
        "worker_batch_size",
        "database_pool_size",
        "database_pool_timeout_seconds",
        "database_pool_recycle_seconds",
        "evolution_request_timeout_seconds",
        "webhook_max_body_bytes",
        "graceful_shutdown_timeout_seconds",
        "outbound_worker_poll_interval_seconds",
        "outbound_worker_max_attempts",
        "outbound_worker_retry_delay_seconds",
        "outbound_worker_processing_timeout_seconds",
        "outbound_worker_batch_size",
        "openai_timeout_seconds",
        "openai_max_output_tokens",
        "openai_history_limit",
        "carlos_history_message_limit",
        "openai_max_reply_characters",
        "ollama_timeout_seconds",
        "openai_transcription_timeout_seconds",
        "openai_transcription_max_characters",
        "gemini_image_timeout_seconds",
        "gemini_image_max_output_tokens",
        "media_max_audio_bytes",
        "media_max_image_bytes",
        "media_download_timeout_seconds",
        "media_processing_max_attempts",
        "media_processing_retry_delay_seconds",
        "media_processing_timeout_seconds",
        "image_analysis_max_summary_characters",
        "image_analysis_max_context_characters",
        "scheduling_max_days_ahead",
        "scheduling_slot_interval_minutes",
        "scheduling_max_services_per_appointment",
    )
    @classmethod
    def validate_positive_worker_settings(cls, value: float | int) -> float | int:
        if value <= 0:
            raise ValueError("Numeric settings must be greater than zero.")

        return value

    @field_validator("inbound_message_buffer_seconds")
    @classmethod
    def validate_inbound_message_buffer_seconds(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Inbound message buffer must be greater than or equal to zero.")
        return value

    @field_validator("database_max_overflow")
    @classmethod
    def validate_database_max_overflow(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Database max overflow must be greater than or equal to zero.")
        return value

    @field_validator("app_log_level")
    @classmethod
    def validate_app_log_level(cls, value: str) -> str:
        clean_value = value.strip().upper()
        if clean_value not in ALLOWED_LOG_LEVELS:
            raise ValueError("App log level must be CRITICAL, ERROR, WARNING, INFO or DEBUG.")
        return clean_value

    @field_validator("media_max_download_redirects")
    @classmethod
    def validate_non_negative_redirects(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Media max download redirects must be greater than or equal to zero.")
        return value

    @field_validator("gemini_image_temperature")
    @classmethod
    def validate_gemini_temperature(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("Gemini image temperature must be between 0 and 1.")
        return value

    @field_validator("image_analysis_max_features")
    @classmethod
    def validate_image_analysis_max_features(cls, value: int) -> int:
        if value < 1 or value > 20:
            raise ValueError("Image analysis max features must be between 1 and 20.")
        return value

    @field_validator("scheduling_confirmation_ttl_minutes")
    @classmethod
    def validate_scheduling_confirmation_ttl_minutes(cls, value: int) -> int:
        if value < 1 or value > 120:
            raise ValueError("Scheduling confirmation TTL must be between 1 and 120 minutes.")
        return value

    @field_validator("scheduling_pending_action_error_max_length")
    @classmethod
    def validate_pending_action_error_max_length(cls, value: int) -> int:
        if value < 100 or value > 2000:
            raise ValueError("Pending action error max length must be between 100 and 2000.")
        return value

    @field_validator("openai_max_tool_rounds")
    @classmethod
    def validate_openai_max_tool_rounds(cls, value: int) -> int:
        if value < 1 or value > 10:
            raise ValueError("OpenAI max tool rounds must be between 1 and 10.")

        return value

    @field_validator("scheduling_min_notice_minutes")
    @classmethod
    def validate_non_negative_scheduling_setting(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Scheduling minimum notice must be greater than or equal to zero.")

        return value

    @field_validator("scheduling_confirmation_code_length")
    @classmethod
    def validate_confirmation_code_length(cls, value: int) -> int:
        if value < 4 or value > 32:
            raise ValueError("Scheduling confirmation code length must be between 4 and 32.")

        return value

    @field_validator(
        "evolution_api_base_url",
        "evolution_api_key",
        "evolution_webhook_secret_header",
        "evolution_send_text_path",
        "openai_model",
        "ollama_base_url",
        "ollama_model",
        "openai_transcription_model",
        "gemini_image_model",
        "evolution_media_base64_path",
        "barbershop_instance",
        "default_resource_key",
    )
    @classmethod
    def validate_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Setting must not be blank.")

        return value

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, value: str) -> str:
        clean = value.strip().lower()
        if clean not in {"openai", "ollama_cloud"}:
            raise ValueError("LLM provider must be openai or ollama_cloud.")
        return clean

    @field_validator(
        "openai_transcription_language",
        "openai_transcription_prompt",
        "admin_dashboard_username",
        "openai_base_url",
    )
    @classmethod
    def blank_optional_strings_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        return clean or None

    @field_validator("inbound_allowed_phones")
    @classmethod
    def normalize_inbound_allowed_phones(cls, value: str) -> str:
        phones = []
        for item in value.split(","):
            phone = "".join(character for character in item if character.isdigit())
            if phone and phone not in phones:
                phones.append(phone)
        return ",".join(phones)

    @property
    def inbound_allowed_phone_set(self) -> set[str]:
        return set(filter(None, self.inbound_allowed_phones.split(",")))

    @field_validator("openai_compat_mode")
    @classmethod
    def validate_openai_compat_mode(cls, value: str) -> str:
        clean = value.strip().lower()
        if clean not in {"responses", "chat_completions"}:
            raise ValueError(
                "OpenAI compat mode must be responses or chat_completions."
            )
        return clean

    @field_validator("evolution_media_base64_path")
    @classmethod
    def validate_evolution_media_base64_path(cls, value: str) -> str:
        clean = value.strip()
        if not clean or "{instance}" not in clean:
            raise ValueError("Evolution media base64 path must contain {instance}.")
        return clean

    @field_validator("barbershop_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        clean_value = value.strip()
        try:
            ZoneInfo(clean_value)
        except ZoneInfoNotFoundError as error:
            if clean_value != "America/Sao_Paulo":
                raise ValueError("Barbershop timezone must be a valid IANA timezone.") from error

        return clean_value

    @field_validator("inbound_handler_mode")
    @classmethod
    def validate_inbound_handler_mode(cls, value: str) -> str:
        if value not in {
            "logging",
            "test_reply",
            "openai_text",
            "openai_scheduling",
            "openai_scheduling_write",
        }:
            raise ValueError(
                "Inbound handler mode must be logging, test_reply, openai_text "
                "openai_scheduling or openai_scheduling_write."
            )

        return value

    @model_validator(mode="after")
    def validate_production_settings(self) -> Self:
        if (
            self.app_env.strip().lower() != "production"
            and "inbound_message_buffer_seconds" not in self.model_fields_set
        ):
            # Fast local/unit-test cycles remain immediate unless explicitly
            # testing the debounce. Production keeps the declared 30s default.
            self.inbound_message_buffer_seconds = 0
        if (
            "openai_compat_mode" not in self.model_fields_set
            and self.openai_base_url is not None
            and "ollama" in self.openai_base_url.lower()
        ):
            self.openai_compat_mode = "chat_completions"
        if (
            self.app_env.strip().lower() == "production"
            and "app_enable_docs" not in self.model_fields_set
        ):
            self.app_enable_docs = False
        if self.evolution_webhook_auth_enabled and self.evolution_webhook_secret is None:
            raise ValueError("Evolution webhook secret is required when auth is enabled.")
        if self.inbound_image_analysis_enabled and self.gemini_api_key is None:
            raise ValueError("Gemini API key is required when image analysis is enabled.")
        if self.admin_dashboard_enabled and (
            self.admin_dashboard_username is None or self.admin_dashboard_password is None
        ):
            raise ValueError(
                "Admin dashboard username and password are required when dashboard is enabled."
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
