"""Local container entry point; the default/production factory remains unavailable."""

from pathlib import Path

from fastapi import FastAPI

from telescope_rag.api.local import create_local_app


def create_container_app() -> FastAPI:
    return create_local_app(Path("/runtime"), runtime="container")
