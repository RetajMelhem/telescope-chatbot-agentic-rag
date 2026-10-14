"""Health checks never call a model or accept a request-supplied configuration."""

import asyncio

from fastapi import APIRouter, Request

from telescope_rag.api.schemas import HealthResponse
from telescope_rag.core.errors import ApplicationError, ErrorResponse
from telescope_rag.core.settings import Settings
from telescope_rag.retrieval.contracts import KnowledgeProbe

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def live(request: Request) -> HealthResponse:
    return HealthResponse(request_id=request.state.request_id, status="live")


@router.get("/ready", response_model=HealthResponse, responses={503: {"model": ErrorResponse}})
async def ready(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    probe: KnowledgeProbe = request.app.state.knowledge_probe
    if not settings.has_model_credentials:
        raise ApplicationError(
            503, "configuration_incomplete", "Model credentials are not configured."
        )
    try:
        snapshot = await asyncio.wait_for(
            probe.check_readiness(), timeout=settings.readiness_timeout_seconds
        )
    except Exception:
        raise ApplicationError(
            503, "knowledge_unavailable", "The knowledge store is unavailable."
        ) from None
    if not snapshot.reachable:
        raise ApplicationError(503, "knowledge_unavailable", "The knowledge store is unavailable.")
    if not snapshot.approved or not snapshot.snapshot_id:
        raise ApplicationError(
            503, "knowledge_not_ready", "Approved website knowledge is not ready."
        )
    if (
        snapshot.embedding_model != settings.openrouter_embedding_model
        or snapshot.dimensions != settings.embedding_dimensions
    ):
        raise ApplicationError(
            503, "knowledge_incompatible", "The approved knowledge configuration is incompatible."
        )
    return HealthResponse(request_id=request.state.request_id, status="ready")
