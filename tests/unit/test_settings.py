from pathlib import Path

import pytest
from pydantic import ValidationError

from telescope_rag.core.settings import ConfigurationError, Settings, load_settings


def test_template_loads_and_keeps_selected_models() -> None:
    settings = load_settings(Path(__file__).parents[2] / ".env.example")
    assert settings.openrouter_chat_model == "openai/gpt-6-luna"
    assert settings.openrouter_embedding_model == "qwen/qwen3-embedding-8b"
    assert settings.cors_allowed_origins == (
        "https://telescopecenter.com",
        "https://www.telescopecenter.com",
    )
    assert not settings.has_model_credentials


def test_environment_overrides_dotenv_without_rewriting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    original = "PORT=8123\nOPENROUTER_API_KEY=synthetic-test-secret\n"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setenv("PORT", "8456")
    settings = load_settings(path)
    assert settings.port == 8456
    assert settings.has_model_credentials
    assert path.read_text(encoding="utf-8") == original
    assert "synthetic-test-secret" not in repr(settings)
    assert "synthetic-test-secret" not in settings.model_dump_json()


@pytest.mark.parametrize(
    "values",
    [
        {"port": 0},
        {"max_subquestions": 5},
        {"provider_max_retries": 2},
        {"request_timeout_seconds": -1},
        {"request_timeout_seconds": 5, "provider_timeout_seconds": 15},
        {"chunk_overlap_tokens": 500},
        {"max_evidence_tokens": 16000},
        {"clinic_timezone": "Unknown/Zone"},
        {"cors_allowed_origins": "*"},
        {"cors_allowed_origins": "https://example.com/path"},
        {"cors_allowed_origins": "https://user:secret@example.com"},
        {"crawl_allowed_hosts": "telescopecenter.com,example.com"},
        {"website_base_url": "https://example.com"},
        {"qdrant_url": "http://user:secret@localhost:6333"},
        {"openrouter_base_url": "https://example.com/api/v1"},
        {"openrouter_chat_model": "some-other-model"},
        {"langsmith_tracing": True},
        {"app_env": "production"},
    ],
)
def test_invalid_or_out_of_scope_configuration_is_rejected(values: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_startup_error_does_not_echo_invalid_secret_values(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("PORT=synthetic-private-value\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as error:
        load_settings(path)
    assert "synthetic-private-value" not in str(error.value)
    assert error.value.__suppress_context__


def test_missing_configuration_file_is_valid_without_credentials(tmp_path: Path) -> None:
    assert not load_settings(tmp_path / "missing.env").has_model_credentials


def test_blank_credentials_do_not_make_configuration_ready() -> None:
    assert not Settings(_env_file=None, openrouter_api_key=" \t ").has_model_credentials


def test_production_accepts_role_scoped_credential_without_requiring_inference() -> None:
    settings = Settings(_env_file=None, app_env="production", qdrant_api_key="synthetic-read-key")
    assert not settings.has_model_credentials


def test_unknown_dotenv_keys_fail_safely(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("PATIENT_DATABASE_SECRET=synthetic-private-value\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as error:
        load_settings(path)
    assert "synthetic-private-value" not in str(error.value)
