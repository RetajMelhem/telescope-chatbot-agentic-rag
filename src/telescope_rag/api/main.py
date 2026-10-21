"""Application factory; importing this module performs no configuration or network work."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from telescope_rag.api.offline_service import OfflineChatService
from telescope_rag.api.routes import chat, health
from telescope_rag.core.errors import ApplicationError, error_payload
from telescope_rag.core.logging import configure_logging
from telescope_rag.core.middleware import RequestBoundaryMiddleware
from telescope_rag.core.settings import Settings, load_settings
from telescope_rag.retrieval.contracts import KnowledgeProbe, UnavailableKnowledgeProbe


def create_app(
    settings: Settings | None = None,
    *,
    knowledge_probe: KnowledgeProbe | None = None,
    offline_chat_service: OfflineChatService | None = None,
    offline_response_format: Literal["draft", "rendered", "hours", "local"] = "draft",
) -> FastAPI:
    config = settings if settings is not None else load_settings()
    if offline_response_format not in {"draft", "rendered", "hours", "local"} or (
        offline_response_format != "draft" and offline_chat_service is None
    ):
        raise ValueError("offline_response_configuration_invalid")
    from telescope_rag.api.hours_service import HoursChatService

    if (offline_response_format in {"hours", "local"}) != isinstance(
        offline_chat_service, HoursChatService
    ):
        raise ValueError("offline_response_configuration_invalid")
    if offline_chat_service is not None:
        offline_chat_service.check_configuration(config)
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
                async with asyncio.timeout(config.shutdown_timeout_seconds):
                    await probe.aclose()
            except TimeoutError:
                logger.warning("adapter_cleanup_timed_out")
            except Exception:
                # Only the failure event is public; adapter exception details stay private.
                logger.warning("adapter_cleanup_failed")

    app = FastAPI(
        title="Telescope clinic chatbot",
        version="0.3.0",
        description=(
            "Explicit nonproduction offline draft transport; "
            "semantic and live acceptance unverified."
            if offline_chat_service is not None
            else "M1 API foundation. Chat inference and live knowledge are not implemented yet."
        ),
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
            error_payload(request.state.request_id, code, message),
            status_code=error.status_code,
            headers={"Allow": error.headers["Allow"]}
            if error.status_code == 405 and error.headers and "Allow" in error.headers
            else None,
        )

    app.include_router(health.router)
    if offline_chat_service is None:
        app.include_router(chat.router)
    else:
        # Import/register the draft route only for explicit trusted construction.
        # No environment toggle, default provider or production adoption.
        if offline_response_format == "local":
            from telescope_rag.api.routes.local_chat import router as offline_router
        elif offline_response_format == "hours":
            from telescope_rag.api.routes.hours_chat import router as offline_router
        elif offline_response_format == "rendered":
            from telescope_rag.api.routes.rendered_chat import router as offline_router
        else:
            from telescope_rag.api.routes.offline_chat import router as offline_router

        app.state.offline_chat_service = offline_chat_service
        app.include_router(offline_router)
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
        cors_allowed_origins=config.cors_allowed_origins,
        logger=logger,
    )
    return app
