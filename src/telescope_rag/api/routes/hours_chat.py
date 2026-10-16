"""Opt-in offline response only; this router is never selected from the environment."""

from uuid import UUID

from fastapi import APIRouter, Request

from telescope_rag.api.hours_responses import HoursChatResponse
from telescope_rag.api.schemas import ChatRequest
from telescope_rag.core.errors import ErrorResponse

router = APIRouter(prefix="/api/v1", tags=["offline-hours"])


@router.post(
    "/chat",
    response_model=HoursChatResponse,
    responses={
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def chat(payload: ChatRequest, request: Request) -> HoursChatResponse:
    return await request.app.state.offline_chat_service.respond(
        payload, request_id=UUID(request.state.request_id)
    )
