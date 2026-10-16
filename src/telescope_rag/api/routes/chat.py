"""Validated transport placeholder. RAG inference is implemented in M5."""

from fastapi import APIRouter, Request

from telescope_rag.api.schemas import ChatRequest
from telescope_rag.api.validation import validate_chat_limits
from telescope_rag.core.errors import ApplicationError, ErrorResponse

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post(
    "/chat",
    status_code=503,
    response_model=ErrorResponse,
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def chat(payload: ChatRequest, request: Request) -> None:
    validate_chat_limits(payload, request.app.state.settings)
    raise ApplicationError(503, "chat_not_available", "The clinic chatbot is not available yet.")
