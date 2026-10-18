"""Preparation handles only the designated project key and leaves its source untouched."""

import importlib.util
from pathlib import Path

import pytest

from telescope_rag.core.settings import ConfigurationError

SPEC = importlib.util.spec_from_file_location(
    "prepare_local_runtime", Path(__file__).parents[2] / "scripts/prepare_local_mvp_runtime.py"
)
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


def setup(root, monkeypatch):
    monkeypatch.setattr(PREPARE, "load_resources", lambda path: None)
    key = root / ".tools/qdrant-m3/read.key"
    key.parent.mkdir(parents=True)
    key.write_text("synthetic-reader", encoding="ascii")
    (root / "data/processed/m4-query-cache-v1").mkdir(parents=True)


def test_only_project_key_is_prepared_idempotently_without_changing_dotenv(monkeypatch, tmp_path):
    setup(tmp_path, monkeypatch)
    source = b"OPENROUTER_API_KEY=synthetic-project\n"
    (tmp_path / ".env").write_bytes(source)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-inherited")
    PREPARE.prepare(tmp_path)
    destination = tmp_path / "runtime-data/local-mvp/openrouter.key"
    assert destination.read_bytes() == b"synthetic-project"
    stamp = destination.stat().st_mtime_ns
    PREPARE.prepare(tmp_path)
    assert destination.stat().st_mtime_ns == stamp
    assert (tmp_path / ".env").read_bytes() == source


@pytest.mark.parametrize("dotenv", [None, "APP_ENV=development\n", "OPENROUTER_API_KEY=\n"])
def test_absent_project_key_does_not_copy_inherited_credentials(monkeypatch, tmp_path, dotenv):
    setup(tmp_path, monkeypatch)
    if dotenv is not None:
        (tmp_path / ".env").write_text(dotenv, encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-inherited")
    with pytest.raises(ConfigurationError, match="project .env"):
        PREPARE.prepare(tmp_path)
    assert not (tmp_path / "runtime-data").exists()


def test_failed_resource_validation_cannot_create_secret(monkeypatch, tmp_path):
    setup(tmp_path, monkeypatch)
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=synthetic-project\n", encoding="utf-8")

    def reject(path):
        raise ValueError("synthetic-source-digest-mismatch")

    monkeypatch.setattr(PREPARE, "load_resources", reject)
    with pytest.raises(ValueError, match="digest-mismatch"):
        PREPARE.prepare(tmp_path)
    assert not (tmp_path / "runtime-data").exists()
