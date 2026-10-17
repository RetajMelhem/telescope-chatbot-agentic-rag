"""Explicit local MVP wire; no public selector or default-app adoption."""

from uuid import UUID

from fastapi import APIRouter, Request

from telescope_rag.api.local import LocalChatResponse
from telescope_rag.api.schemas import ChatRequest

router = APIRouter(prefix="/api/v1", tags=["local-mvp"])


@router.post("/chat", response_model=LocalChatResponse)
async def chat(payload: ChatRequest, request: Request) -> LocalChatResponse:
    response = await request.app.state.offline_chat_service.respond(
        payload, request_id=UUID(request.state.request_id)
    )
    values = {
        name: getattr(response, name)
        for name in LocalChatResponse.model_fields
        if name not in {"schema_version", "mode"}
    }
    return LocalChatResponse(**values)
