"""Closed wire schemas and explicit request-owned offline workflow interfaces."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telescope_rag.ingestion.models import BlockKind
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import AttemptReceipt
from telescope_rag.retrieval.assembly import (
    AssembledEvidence,
    AssemblyRequest,
    IntendedUse,
    SourceScope,
)


class ClosedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class HistoryTurn(ClosedRecord):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000, repr=False)


class WorkflowRequest(ClosedRecord):
    query: str = Field(min_length=1, max_length=4000, repr=False)
    history: tuple[HistoryTurn, ...] = Field(default=(), max_length=6, repr=False)
    language: Literal["auto", "ar", "en"] = "auto"

    @model_validator(mode="after")
    def bound_request(self):
        if not self.query.strip() or sum(len(h.content) for h in self.history) > 8000:
            raise ValueError("workflow_request_invalid")
        return self


# Every wire property is required, including nullable properties. Convenience
# assembly models contain defaults and must not be used as provider schemas.
class PlannerPart(ClosedRecord):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    state: Literal["public", "excluded", "clarification_required"]
    operation: Literal["search", "read_source", "time_comparison"]
    intended_use: IntendedUse
    retrieval_query: str | None = Field(max_length=4000, repr=False)
    document_handles: tuple[str, ...] = Field(max_length=16)
    owner_handle: str | None
    block_types: tuple[BlockKind, ...] = Field(max_length=10)
    source_language: Literal["ar", "en", "und"] | None
    reference_text: str | None = Field(max_length=512, repr=False)
    history_indices: tuple[int, ...] = Field(max_length=6)
    reason: str | None = Field(max_length=512, repr=False)


class PlannerReply(ClosedRecord):
    language: Literal["en", "ar", "ar-JO"]
    parts: tuple[PlannerPart, ...] = Field(min_length=1, max_length=4)


class QuoteDraft(ClosedRecord):
    chunk_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=12000, repr=False)


DraftStatus = Literal["candidate", "unknown", "excluded", "clarification_required"]
ReasonCode = Literal[
    "not_found",
    "scope_excluded",
    "ambiguous_request",
    "context_only",
    "scope_incomplete",
    "operation_unavailable",
    "budget_limited",
    "draft_unavailable",
]


class PartDraft(ClosedRecord):
    part_id: str = Field(min_length=1, max_length=128)
    status: DraftStatus
    quotes: tuple[QuoteDraft, ...] = Field(max_length=16)
    reason_code: ReasonCode | None


class AnswerDraft(ClosedRecord):
    parts: tuple[PartDraft, ...] = Field(min_length=1, max_length=4)


class RetrievalQuery(ClosedRecord):
    part_id: str
    text: str = Field(min_length=1, max_length=4000, repr=False)
    scope: SourceScope


class RetrievedPart(ClosedRecord):
    part_id: str
    chunk_ids: tuple[str, ...] = Field(max_length=100)


class RetrievalBatch(ClosedRecord):
    snapshot_id: str
    prepared_digest: str
    parts: tuple[RetrievedPart, ...] = Field(min_length=1, max_length=4)


class EvidenceRetriever(Protocol):
    async def retrieve(
        self,
        queries: Sequence[RetrievalQuery],
        *,
        snapshot_id: str,
        prepared_digest: str,
        budget: ExecutionBudget,
    ) -> RetrievalBatch:
        """One bounded dense batch; no writes, arbitrary fetches or source invention."""
        ...


@dataclass(frozen=True)
class ValidatedPlan:
    language: Literal["en", "ar", "ar-JO"]
    assembly_request: AssemblyRequest = field(repr=False)
    operations: tuple[Literal["search", "read_source", "time_comparison"], ...]
    retrieval_queries: tuple[RetrievalQuery, ...] = field(repr=False)
    # Validation is structural/literal, not proof of semantic interpretation.
    semantic_interpretation_verified: bool = False


class QuotedEvidence(ClosedRecord):
    chunk_id: str
    source_url: str
    document_id: str
    snapshot_id: str
    fetched_at: datetime
    literal_owner_id: str | None
    canonical_owner_id: str | None
    quote: str = Field(repr=False)


class PartResult(ClosedRecord):
    part_id: str
    original_text: str = Field(repr=False)
    status: DraftStatus
    quotes: tuple[QuotedEvidence, ...] = Field(repr=False)
    reason_code: ReasonCode | None
    admitted_scope_complete: bool | None


class WorkflowResult(ClosedRecord):
    request_id: str
    outcome: Literal["draft_ready", "not_found", "out_of_scope", "clarification_required", "failed"]
    language: Literal["en", "ar", "ar-JO"]
    parts: tuple[PartResult, ...]
    error_code: str | None
    offline_only: Literal[True] = True
    semantic_grounding_verified: Literal[False] = False
    luna_compatibility_verified: Literal[False] = False


@dataclass(frozen=True)
class BudgetSummary:
    logical_chat_calls: int
    logical_embedding_calls: int
    physical_chat_attempts: int
    physical_embedding_attempts: int
    charged_chat_input: int | None
    charged_embedding_input: int
    charged_output: int
    receipts: tuple[AttemptReceipt, ...]


@dataclass(frozen=True)
class LiteralRequestSpan:
    start: int
    end: int
    quote: str = field(repr=False)


@dataclass(frozen=True)
class PartAnchorBinding:
    part_id: str
    original: LiteralRequestSpan = field(repr=False)
    constraints: tuple[LiteralRequestSpan, ...] = field(repr=False)


@dataclass(frozen=True)
class WorkflowRun:
    request: WorkflowRequest = field(repr=False)
    result: WorkflowResult
    plan: ValidatedPlan | None = field(repr=False)
    evidence: AssembledEvidence | None = field(repr=False)
    stages: tuple[str, ...]
    usage: BudgetSummary
    request_anchors: tuple[PartAnchorBinding, ...] = field(default=(), repr=False)
