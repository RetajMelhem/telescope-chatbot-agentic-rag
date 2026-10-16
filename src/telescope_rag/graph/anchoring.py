"""Exact request-text binding; no language classification, fuzzy matches or repair."""

from typing import Annotated, Literal

from pydantic import Field

from telescope_rag.graph.contracts import (
    ClosedRecord,
    LiteralRequestSpan,
    PartAnchorBinding,
    PlannerPart,
    PlannerReply,
    WorkflowRequest,
)
from telescope_rag.ingestion.models import BlockKind
from telescope_rag.retrieval.assembly import IntendedUse

OriginalQuote = Annotated[str, Field(min_length=1, max_length=4000)]


class AnchoredPlannerPart(ClosedRecord):
    original_text: OriginalQuote = Field(repr=False)
    constraint_quotes: tuple[OriginalQuote, ...] = Field(max_length=8, repr=False)
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


class AnchoredPlannerReply(ClosedRecord):
    language: Literal["en", "ar", "ar-JO"]
    parts: tuple[AnchoredPlannerPart, ...] = Field(min_length=1, max_length=4)


class AnchorError(ValueError):
    """Stable application codes only; original query/model text is never an error."""


def unique_original_span(original: str, quote: str) -> LiteralRequestSpan:
    if not quote.strip():
        raise AnchorError("empty_original_text_anchor")
    start = original.find(quote)
    if start < 0:
        raise AnchorError("original_text_anchor_not_found")
    # Advancing one character also detects overlapping occurrences, e.g. ana in banana.
    if original.find(quote, start + 1) >= 0:
        raise AnchorError("ambiguous_original_text_anchor")
    return LiteralRequestSpan(start, start + len(quote), quote)


def resolve_anchored_plan(
    reply: AnchoredPlannerReply, request: WorkflowRequest, request_id: str
) -> tuple[PlannerReply, tuple[PartAnchorBinding, ...]]:
    """Derive offsets without changing a model's states, queries or source selections.

    SourceBindings.validate must still check scope, history and complete coverage.
    Neither successful resolution nor complete coverage proves semantic correctness.
    """
    parts, receipts = [], []
    for index, proposal in enumerate(reply.parts, 1):
        original = unique_original_span(request.query, proposal.original_text)
        if len(set(proposal.constraint_quotes)) != len(proposal.constraint_quotes):
            raise AnchorError("duplicate_constraint_anchor")
        constraints = tuple(
            unique_original_span(request.query, text) for text in proposal.constraint_quotes
        )
        if any(not original.start <= c.start < c.end <= original.end for c in constraints):
            raise AnchorError("constraint_outside_original_part")
        if (
            proposal.state == "public"
            and proposal.operation == "search"
            and (
                proposal.retrieval_query is None
                or proposal.original_text not in proposal.retrieval_query
            )
        ):
            raise AnchorError("retrieval_query_lost_original_part")
        # No appending, rephrasing, trimming, normalizing or semantic state repair.
        fields = proposal.model_dump(exclude={"original_text", "constraint_quotes"})
        parts.append(PlannerPart(start=original.start, end=original.end, **fields))
        receipts.append(PartAnchorBinding(f"{request_id}-p{index}", original, constraints))
    return PlannerReply(language=reply.language, parts=tuple(parts)), tuple(receipts)
