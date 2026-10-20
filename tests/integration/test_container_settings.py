"""Runtime file secrets remain independent from dotenv and inherited credentials."""

import pytest

from telescope_rag.api.local import container_settings
from telescope_rag.core.settings import ConfigurationError


def files(root):
    (root / "openrouter_key").write_text("synthetic-file-openrouter", encoding="ascii")
    (root / "qdrant_read_key").write_text("synthetic-file-read", encoding="ascii")


def test_container_file_keys_win_without_dotenv_or_process_substitution(monkeypatch, tmp_path):
    files(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=synthetic-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-inherited")
    monkeypatch.setenv("QDRANT_API_KEY", "synthetic-inherited-admin")
    result = container_settings(tmp_path)
    assert result.openrouter_api_key.get_secret_value() == "synthetic-file-openrouter"
    assert result.qdrant_api_key.get_secret_value() == "synthetic-file-read"
    assert str(result.qdrant_url) == "http://telescope-m3-qdrant:6333/"
    assert result.provider_max_retries == 0 and result.max_llm_calls == 2
    assert result.max_total_output_tokens == 8192 and result.retrieval_top_k_per_question == 11
    assert result.chat_input_accounting == "reported_usage"


@pytest.mark.parametrize("missing", ["openrouter_key", "qdrant_read_key"])
def test_missing_secret_cannot_fall_back_to_environment(monkeypatch, tmp_path, missing):
    files(tmp_path)
    (tmp_path / missing).unlink()
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-inherited")
    monkeypatch.setenv("QDRANT_API_KEY", "synthetic-inherited-admin")
    with pytest.raises(ValueError, match="secret_file_invalid"):
        container_settings(tmp_path)


def test_container_does_not_enable_production(monkeypatch, tmp_path):
    files(tmp_path)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ConfigurationError, match="production"):
        container_settings(tmp_path)
