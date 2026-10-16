"""Closed review-only response records; no model-generated narrative or readiness claim."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from telescope_rag.graph.contracts import DraftStatus, ReasonCode


class ResponseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class ResponseCitation(ResponseRecord):
    id: str
    question_id: str
    chunk_id: str
    document_id: str
    parent_block_id: str
    url: str
    title: str
    section: tuple[str, ...]
    source_language: Literal["en", "ar", "und"]
    fetched_at: datetime
    snapshot_id: str
    literal_owner_id: str | None
    literal_owner_name: str | None
    canonical_owner_id: str | None
    canonical_owner_name: str | None
    source_issue_codes: tuple[str, ...]
    quote: str = Field(repr=False)


class ResponseQuestion(ResponseRecord):
    id: str
    question: str = Field(repr=False)
    status: DraftStatus
    answer: str = Field(repr=False)
    citation_ids: tuple[str, ...]
    reason_code: ReasonCode | None
    admitted_scope_complete: bool | None


class ResponseKnowledge(ResponseRecord):
    snapshot_id: str
    prepared_digest: str
    fetched_at: datetime


class OfflineChatResponse(ResponseRecord):
    schema_version: Literal["offline-response-v1"] = "offline-response-v1"
    request_id: str
    status: Literal["draft_ready", "not_found", "out_of_scope", "clarification_required"]
    answer: str = Field(repr=False)
    answer_format: Literal["plain_text"] = "plain_text"
    language: Literal["en", "ar", "ar-JO"]
    questions: tuple[ResponseQuestion, ...] = Field(min_length=1, max_length=4, repr=False)
    citations: tuple[ResponseCitation, ...] = Field(max_length=64, repr=False)
    unresolved_questions: tuple[str, ...] = Field(max_length=4)
    knowledge: ResponseKnowledge | None
    review_notice: str
    offline_only: Literal[True] = True
    semantic_grounding_verified: Literal[False] = False
    luna_compatibility_verified: Literal[False] = False
