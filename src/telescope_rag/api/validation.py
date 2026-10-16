"""Configured transport bounds shared by unavailable and explicitly injected draft routes."""

from telescope_rag.api.schemas import ChatRequest
from telescope_rag.core.errors import ApplicationError
from telescope_rag.core.settings import Settings


def validate_chat_limits(payload: ChatRequest, settings: Settings) -> None:
    if (
        len(payload.query) > settings.max_query_chars
        or len(payload.history) > settings.max_history_messages
        or sum(len(message.content) for message in payload.history) > settings.max_history_chars
    ):
        raise ApplicationError(
            422, "invalid_request", "The request exceeds configured text limits."
        )
