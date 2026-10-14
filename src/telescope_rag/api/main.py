"""Application factory; importing this module performs no configuration or network work."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from telescope_rag.api.routes import chat, health
from telescope_rag.core.errors import ApplicationError, error_payload
from telescope_rag.core.logging import configure_logging
from telescope_rag.core.middleware import RequestBoundaryMiddleware
from telescope_rag.core.settings import Settings, load_settings
from telescope_rag.retrieval.contracts import KnowledgeProbe, UnavailableKnowledgeProbe


def create_app(
    settings: Settings | None = None, *, knowledge_probe: KnowledgeProbe | None = None
) -> FastAPI:
    config = settings if settings is not None else load_settings()
    probe = knowledge_probe if knowledge_probe is not None else UnavailableKnowledgeProbe()
    logger = configure_logging(config.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Adapters are injected and owned by this application lifetime.
        # No inference, collection creation, or crawling is performed here.
        try:
            yield
        finally:
            try:
                await probe.aclose()
            except Exception:
                # Closing a failed adapter must not disclose its configuration or payload.
                pass

    app = FastAPI(
        title="Telescope clinic chatbot",
        version="0.1.0",
        description="M1 API foundation. Chat inference and live knowledge are not implemented yet.",
        lifespan=lifespan,
        debug=False,
        docs_url="/docs" if config.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.app_env != "production" else None,
    )
    app.state.settings = config
    app.state.knowledge_probe = probe

    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, error: ApplicationError) -> JSONResponse:
        return JSONResponse(
            error_payload(request.state.request_id, error.code, error.safe_message),
            status_code=error.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        # FastAPI's default errors include rejected input. Do not serialize them.
        return JSONResponse(
            error_payload(
                request.state.request_id, "invalid_request", "The request payload is invalid."
            ),
            status_code=422,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        code, message = {
            404: ("not_found", "The endpoint does not exist."),
            405: ("method_not_allowed", "The HTTP method is not allowed."),
        }.get(error.status_code, ("http_error", "The HTTP request could not be completed."))
        return JSONResponse(
            error_payload(request.state.request_id, code, message), status_code=error.status_code
        )

    app.include_router(health.router)
    app.include_router(chat.router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
        allow_credentials=False,
    )
    app.add_middleware(
        RequestBoundaryMiddleware,
        max_body_bytes=config.max_request_body_bytes,
        timeout_seconds=config.request_timeout_seconds,
        logger=logger,
    )
    return app
