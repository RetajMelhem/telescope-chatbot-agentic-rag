"""Opt-in review presentation at the existing route, without enabling public serving."""

from uuid import UUID

from fastapi import APIRouter, Request

from telescope_rag.api.offline_service import OfflineChatService
from telescope_rag.api.responses import OfflineChatResponse
from telescope_rag.api.schemas import ChatRequest
from telescope_rag.core.errors import ErrorResponse

router = APIRouter(prefix="/api/v1", tags=["offline-response"])


@router.post(
    "/chat",
    response_model=OfflineChatResponse,
    responses={
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def offline_response(payload: ChatRequest, request: Request) -> OfflineChatResponse:
    service: OfflineChatService = request.app.state.offline_chat_service
    return await service.respond(payload, request_id=UUID(request.state.request_id))
