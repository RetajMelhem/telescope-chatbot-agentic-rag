"""Explicitly injected nonproduction draft route; absent from the default app."""

from uuid import UUID

from fastapi import APIRouter, Request

from telescope_rag.api.offline_service import OfflineChatService
from telescope_rag.api.schemas import ChatRequest
from telescope_rag.core.errors import ErrorResponse
from telescope_rag.graph.contracts import WorkflowResult

router = APIRouter(prefix="/api/v1", tags=["offline-draft"])


@router.post(
    "/chat",
    response_model=WorkflowResult,
    responses={
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def offline_draft(payload: ChatRequest, request: Request) -> WorkflowResult:
    service: OfflineChatService = request.app.state.offline_chat_service
    return await service.draft(payload, request_id=UUID(request.state.request_id))
