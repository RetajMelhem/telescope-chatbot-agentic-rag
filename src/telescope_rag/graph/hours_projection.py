"""Shared source-bound hours decision used before writing and again at publication."""

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from telescope_rag.graph.contracts import DraftStatus, ReasonCode
from telescope_rag.graph.hours_records import ComputedHours
from telescope_rag.retrieval.assembly import (
    AssembledEvidence,
    EvidenceCatalog,
    RequestPart,
    limited_to_context,
)


def listing_state(operation: ComputedHours, *, max_age: timedelta) -> tuple[str, str]:
    """Compare reviewed records, never infer a schedule from text or today's result."""
    if operation.query.subject is None:
        return "clarification_required", "ambiguous_subject"
    if not operation.schedules:
        return "unknown", "missing_hours"
    now = operation.assessment.evaluated_at
    if any(c.fetched_at > now for c in operation.assessment.evidence):
        return "unknown", "source_from_future"
    if any(now - c.fetched_at > max_age for c in operation.assessment.evidence):
        return "unknown", "stale_hours"
    local_day = now.astimezone(ZoneInfo("Asia/Amman")).date()
    for record in operation.schedules:
        if record.conditional:
            return "unknown", "conditional_hours"
        if (record.valid_from and local_day < record.valid_from) or (
            record.valid_through and local_day > record.valid_through
        ):
            return "unknown", "outside_effective_dates"
    signatures = {
        (
            tuple(r.model_dump_json() for r in sorted(record.weekly, key=lambda r: r.weekday)),
            tuple(r.model_dump_json() for r in sorted(record.exceptions, key=lambda r: r.on_date)),
            record.valid_from,
            record.valid_through,
            record.timezone,
        )
        for record in operation.schedules
    }
    if len(signatures) != 1:
        return "unknown", "conflicting_hours"
    return "schedule_available", "published_schedule"


@dataclass(frozen=True)
class HoursDecision:
    status: str
    reason: str
    proof_present: bool

    @property
    def draft_status(self) -> DraftStatus:
        if self.status in {"schedule_available", "within_posted_hours", "outside_posted_hours"}:
            return "candidate"
        return "clarification_required" if self.status == "clarification_required" else "unknown"

    @property
    def reason_code(self) -> ReasonCode | None:
        if self.draft_status == "candidate":
            return None
        if self.draft_status == "clarification_required":
            return "ambiguous_request"
        return "scope_incomplete" if self.reason == "scope_incomplete" else "not_found"


def hours_decision(
    operation: ComputedHours,
    *,
    part: RequestPart,
    evidence: AssembledEvidence | None,
    catalog: EvidenceCatalog,
    max_age: timedelta,
    admitted_scope_complete: bool | None,
) -> HoursDecision:
    assessment = operation.assessment
    status, reason = (
        listing_state(operation, max_age=max_age)
        if operation.supplied.intent == "schedule"
        else (assessment.status, assessment.reason)
    )
    offered = set()
    if evidence is not None:
        for group in evidence.groups:
            ids = dict(group.part_occurrences).get(part.part_id, ())
            if ids and part.part_id not in group.context_only_parts:
                offered.add(ids[0])
    needed = {c.chunk_id for c in assessment.evidence}
    proof_present = (
        needed <= offered
        and needed <= set(catalog.scope_members(part.scope))
        and all(
            catalog.chunks[c.chunk_id] == c and not limited_to_context(c, part.intended_use)
            for c in assessment.evidence
        )
        and admitted_scope_complete is not False
    )
    if not proof_present:
        status, reason = "unknown", "scope_incomplete"
    return HoursDecision(status, reason, proof_present)
