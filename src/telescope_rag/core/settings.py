"""Environment settings without inference or other startup network activity."""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
)

CsvValues = Annotated[tuple[str, ...], NoDecode]
PUBLIC_HOSTS = frozenset({"telescopecenter.com", "www.telescopecenter.com"})


class ConfigurationError(RuntimeError):
    """A safe startup error; never attach the original input to the public message."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource | Callable[[], dict], ...]:
        def project_openrouter_key() -> dict:
            # The user designated the project .env as this credential's authority.
            # Other settings retain process overrides. Explicit injected settings
            # still take priority for isolated tests; without dotenv, runtime
            # environment injection remains available for future deployment.
            values = dotenv_settings()
            return (
                {"openrouter_api_key": values["openrouter_api_key"]}
                if "openrouter_api_key" in values
                else {}
            )

        return (
            init_settings,
            project_openrouter_key,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    host: str = Field(default="0.0.0.0", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    clinic_timezone: str = "Asia/Amman"
    default_language: Literal["ar", "en"] = "ar"
    cors_allowed_origins: CsvValues = (
        "https://telescopecenter.com",
        "https://www.telescopecenter.com",
    )

    openrouter_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    openrouter_base_url: AnyHttpUrl = AnyHttpUrl("https://openrouter.ai/api/v1")
    openrouter_chat_model: Literal["openai/gpt-6-luna"] = "openai/gpt-6-luna"
    openrouter_embedding_model: Literal["qwen/qwen3-embedding-8b"] = "qwen/qwen3-embedding-8b"
    # Normal Luna calls use actual provider usage after dispatch. Strict local
    # counting remains available explicitly; embeddings always require counting.
    chat_input_accounting: Literal["reported_usage", "strict"] = "reported_usage"
    # Optional experiment control; omission preserves the provider default.
    chat_reasoning_effort: Literal["none"] | None = None
    provider_timeout_seconds: float = Field(default=15, gt=0)
    provider_max_retries: int = Field(default=1, ge=0, le=1)
    provider_max_request_bytes: int = Field(default=262144, gt=0)
    provider_max_response_bytes: int = Field(default=2000000, gt=0)
    provider_retry_delay_seconds: float = Field(default=0.1, ge=0, le=2)
    max_embedding_calls: int = Field(default=1, ge=1, le=1)
    max_embedding_input_tokens: int = Field(default=16000, gt=0)
    max_embedding_batch_size: int = Field(default=32, ge=1, le=32)

    qdrant_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:6333")
    qdrant_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    qdrant_collection_alias: str = Field(default="telescope_public_active", min_length=1)
    embedding_dimensions: int = Field(default=4096, ge=32, le=4096)

    max_query_chars: int = Field(default=4000, gt=0, le=4000)
    max_history_messages: int = Field(default=6, ge=0, le=6)
    max_history_chars: int = Field(default=8000, ge=0, le=8000)
    max_subquestions: int = Field(default=4, gt=0, le=4)
    max_llm_calls: int = Field(default=2, ge=1, le=2)
    max_retrieval_rounds: int = Field(default=1, ge=1, le=1)
    retrieval_top_k_per_question: int = Field(default=5, gt=0)
    max_evidence_chunks: int = Field(default=16, gt=0)
    max_evidence_tokens: int = Field(default=6000, gt=0)
    max_total_input_tokens: int = Field(default=16000, gt=0)
    max_total_output_tokens: int = Field(default=2000, gt=0)
    request_timeout_seconds: float = Field(default=30, gt=0)
    retrieval_concurrency: int = Field(default=4, gt=0)
    max_request_body_bytes: int = Field(default=131072, gt=0)
    readiness_timeout_seconds: float = Field(default=2, gt=0)
    shutdown_timeout_seconds: float = Field(default=5, gt=0)

    website_base_url: AnyHttpUrl = AnyHttpUrl("https://telescopecenter.com/")
    crawl_allowed_hosts: CsvValues = tuple(sorted(PUBLIC_HOSTS))
    crawl_max_pages: int = Field(default=250, gt=0)
    crawl_max_depth: int = Field(default=4, ge=0)
    crawl_concurrency: int = Field(default=2, gt=0)
    crawl_delay_seconds: float = Field(default=1, ge=0)
    crawl_max_page_bytes: int = Field(default=2000000, gt=0)
    chunking_strategy: Literal["structure_aware"] = "structure_aware"
    chunk_max_tokens: int = Field(default=1200, gt=0, le=32768)
    # Accepted only so existing .env files remain usable; neither controls chunking.
    chunk_target_tokens: int | None = Field(default=None, repr=False, exclude=True)
    chunk_overlap_tokens: int | None = Field(default=None, repr=False, exclude=True)
    knowledge_max_age_hours: int = Field(default=168, gt=0)
    langsmith_tracing: bool = False

    @field_validator("langsmith_tracing")
    @classmethod
    def keep_tracing_disabled(cls, value: bool) -> bool:
        if value:
            raise ValueError("External conversation tracing is not enabled for this milestone.")
        return value

    @field_validator("openrouter_api_key", "qdrant_api_key", mode="before")
    @classmethod
    def clean_secret(cls, value: str | SecretStr) -> SecretStr:
        text = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(text, str):
            raise ValueError("Credentials must be strings.")
        return SecretStr(text.strip())

    @field_validator("cors_allowed_origins", "crawl_allowed_hosts", mode="before")
    @classmethod
    def parse_csv(cls, value: str | tuple[str, ...]) -> tuple[str, ...]:
        values = value.split(",") if isinstance(value, str) else value
        return tuple(item.strip() for item in values if item.strip())

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in value
            ):
                raise ValueError(
                    "CORS requires explicit HTTP origins without paths or credentials."
                )
            try:
                _ = parsed.port
            except ValueError:
                raise ValueError("CORS origin has an invalid port.") from None
        return values

    @field_validator("crawl_allowed_hosts")
    @classmethod
    def validate_hosts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or not set(values).issubset(PUBLIC_HOSTS):
            raise ValueError("Crawl hosts must be approved clinic website hosts.")
        return values

    @field_validator("clinic_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Clinic timezone must be a valid IANA timezone.") from None
        return value

    @field_validator("openrouter_base_url", "qdrant_url", "website_base_url")
    @classmethod
    def reject_url_credentials(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("Service URLs must not contain credentials, queries, or fragments.")
        return value

    @model_validator(mode="after")
    def validate_relationships(self) -> Self:
        if self.provider_timeout_seconds > self.request_timeout_seconds:
            raise ValueError("Provider timeout must fit the request deadline.")
        if self.readiness_timeout_seconds > self.request_timeout_seconds:
            raise ValueError("Readiness timeout must fit the request deadline.")
        if self.chunk_max_tokens > self.max_evidence_tokens:
            raise ValueError("The chunk safety ceiling must fit the evidence budget.")
        if self.max_evidence_tokens >= self.max_total_input_tokens:
            raise ValueError("Input budget must leave room beyond evidence.")
        if self.website_base_url.scheme != "https" or (
            self.website_base_url.host not in self.crawl_allowed_hosts
        ):
            raise ValueError("The website base URL must use HTTPS on an approved crawl host.")
        if (
            self.openrouter_base_url.scheme != "https"
            or self.openrouter_base_url.host != "openrouter.ai"
            or self.openrouter_base_url.port != 443
            or (self.openrouter_base_url.path or "").rstrip("/") != "/api/v1"
        ):
            raise ValueError("OpenRouter must use the approved HTTPS API base URL.")
        if self.app_env == "production" and not self.qdrant_api_key.get_secret_value():
            raise ValueError("Production requires a read-only knowledge credential.")
        return self

    @property
    def has_model_credentials(self) -> bool:
        return bool(self.openrouter_api_key.get_secret_value())


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    """Use the project's dotenv OpenRouter key; suppress unsafe input details."""
    try:
        return Settings(_env_file=env_file)
    except (ValidationError, SettingsError, OSError, ValueError):
        raise ConfigurationError(
            "Invalid application configuration. Check setting names, types, and limits."
        ) from None
