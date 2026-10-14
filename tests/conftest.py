"""Tests never load local secrets or inherit application settings from the host."""

import os

import pytest

from telescope_rag.core.settings import Settings


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    names = {name.upper() for name in Settings.model_fields}
    for name in list(os.environ):
        if name.upper() in names:
            monkeypatch.delenv(name)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, app_env="test")
