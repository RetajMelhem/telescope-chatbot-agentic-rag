"""Validated transport placeholder. RAG inference is implemented in M5."""

from fastapi import APIRouter, Request

from telescope_rag.api.schemas import ChatRequest
from telescope_rag.core.errors import ApplicationError, ErrorResponse
from telescope_rag.core.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post(
    "/chat",
    status_code=503,
    response_model=ErrorResponse,
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def chat(payload: ChatRequest, request: Request) -> None:
    settings: Settings = request.app.state.settings
    if (
        len(payload.query) > settings.max_query_chars
        or len(payload.history) > settings.max_history_messages
        or sum(len(message.content) for message in payload.history) > settings.max_history_chars
    ):
        raise ApplicationError(
            422, "invalid_request", "The request exceeds configured text limits."
        )
    raise ApplicationError(503, "chat_not_available", "The clinic chatbot is not available yet.")
