"""Validate mounted MVP resources and prepare its ignored runtime key, without I/O to services."""

import os
import tempfile
from pathlib import Path

from dotenv import dotenv_values

from telescope_rag.api.local import load_resources
from telescope_rag.core.settings import ConfigurationError, load_settings
from telescope_rag.ingestion.runner import read_secret


def prepare(root: Path) -> None:
    root = root.resolve()
    env_file = root / ".env"
    # Do not substitute a shell key if the designated project key is absent.
    if not env_file.is_file() or not dotenv_values(env_file).get("OPENROUTER_API_KEY"):
        raise ConfigurationError("The project .env must contain its OpenRouter key.")
    settings = load_settings(env_file)
    if settings.app_env == "production":
        raise ConfigurationError("The local MVP cannot use production settings.")
    load_resources(root)
    read_secret(root / ".tools/qdrant-m3/read.key")
    if not (root / "data/processed/m4-query-cache-v1").is_dir():
        raise ConfigurationError("The reviewed query-cache directory is missing.")
    directory = (root / "runtime-data/local-mvp").resolve()
    if not directory.is_relative_to(root):
        raise ConfigurationError("The local runtime directory must stay inside the workspace.")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "openrouter.key"
    value = settings.openrouter_api_key.get_secret_value().encode("ascii")
    if destination.exists() and destination.read_bytes() == value:
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".openrouter-", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(value)
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        prepare(Path.cwd())
    except Exception:
        raise SystemExit(
            "Local MVP preparation failed. Check the project key and reviewed resources; "
            "no credentials have been printed."
        ) from None
    print(
        "Reviewed resources validated; local runtime secret prepared. No inference or index write."
    )
