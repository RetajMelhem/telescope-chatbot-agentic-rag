"""Literal field/scoped source bindings; no natural-language date or identity parser."""

import json
from datetime import date, datetime
from types import MappingProxyType

from pydantic import Field

from telescope_rag.graph.anchoring import AnchoredPlannerPart, AnchoredPlannerReply
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.graph.hours_records import ComputedHours, HoursFieldBinding, HoursInput
from telescope_rag.knowledge.hours import HoursQuery, HoursSubject, PublicHoursPlan
from telescope_rag.knowledge.time_calculations import PublicHoursCatalog
from telescope_rag.retrieval.assembly import EvidenceCatalog, RequestPart


class HoursPlannerPart(AnchoredPlannerPart):
    hours: HoursInput | None


class HoursPlannerReply(AnchoredPlannerReply):
    parts: tuple[HoursPlannerPart, ...] = Field(min_length=1, max_length=4)


class HoursBindings:
    def __init__(
        self,
        plan: PublicHoursPlan,
        catalog: EvidenceCatalog,
        sources: SourceBindings,
        engine: PublicHoursCatalog,
    ):
        self.plan, self.catalog, self.engine = plan, catalog, engine
        subjects = {
            (r.subject.kind, r.subject.id, r.subject.owner_kind): r.subject for r in plan.schedules
        }
        for kind, identity in sources.owners.values():
            subjects[("doctor", identity, kind)] = HoursSubject(
                kind="doctor", id=identity, owner_kind=kind
            )
        if len(subjects) > 512:
            raise ValueError("hours_manifest_exceeds_bound")
        self.subjects = MappingProxyType(
            {f"h{i}": subjects[k] for i, k in enumerate(sorted(subjects), 1)}
        )
        manifest = []
        for handle, subject in self.subjects.items():
            names = sorted(
                {
                    c.doctor_name if subject.owner_kind == "literal" else c.canonical_doctor_name
                    for c in catalog.chunks.values()
                    if subject.kind == "doctor"
                    and (c.doctor_id if subject.owner_kind == "literal" else c.canonical_doctor_id)
                    == subject.id
                }
                - {None}
            )
            manifest.append(
                {
                    "handle": handle,
                    "kind": subject.kind,
                    "labels": names or [subject.kind],
                    "owner_handle": next(
                        (
                            h
                            for h, value in sources.owners.items()
                            if value == (subject.owner_kind, subject.id)
                        ),
                        None,
                    ),
                    "reviewed_hours_record_present": bool(engine.records_for(subject)),
                }
            )
        self.manifest_json = json.dumps(
            {"version": "public-hours-handles-v1", "subjects": manifest}, ensure_ascii=False
        )
        if len(self.manifest_json.encode()) > 96000:
            raise ValueError("hours_manifest_exceeds_bound")

    def bind(
        self,
        supplied: HoursInput,
        *,
        part: RequestPart,
        request: WorkflowRequest,
        reference_text: str | None,
        history_indices: tuple[int, ...],
        now: datetime,
    ) -> ComputedHours:
        supplied = HoursInput.model_validate_json(supplied.model_dump_json())
        if part.state != "public" or part.intended_use != "general_excerpt":
            raise ValueError("hours_input_scope_invalid")
        subject = self.subjects.get(supplied.subject_handle)
        if supplied.subject_handle is not None and subject is None:
            raise ValueError("hours_subject_unissued")
        if part.scope.owner_id is not None and (
            subject is None
            or subject.kind != "doctor"
            or (subject.owner_kind, subject.id) != (part.scope.owner_kind, part.scope.owner_id)
        ):
            raise ValueError("hours_subject_scope_mismatch")
        bindings = []
        for name in ("subject_quote", "date_quote", "time_quote"):
            quote = getattr(supplied, name)
            if quote is None:
                continue
            offset = 0
            if quote.origin == "part":
                text = request.query[part.start : part.end]
                offset = part.start
                if quote.history_index is not None:
                    raise ValueError("hours_field_origin_invalid")
            elif quote.origin == "query_reference":
                if quote.history_index is not None or not reference_text:
                    raise ValueError("hours_field_origin_invalid")
                offset = request.query.find(reference_text)
                if offset < 0 or request.query.find(reference_text, offset + 1) >= 0:
                    raise ValueError("hours_reference_ambiguous")
                text = reference_text
            else:
                if quote.history_index not in history_indices or quote.history_index is None:
                    raise ValueError("hours_field_origin_invalid")
                text = request.history[quote.history_index].content
            start = text.find(quote.quote)
            if start < 0 or text.find(quote.quote, start + 1) >= 0:
                raise ValueError("hours_field_anchor_invalid")
            bindings.append(
                HoursFieldBinding(
                    name,
                    quote.origin,
                    quote.history_index,
                    offset + start,
                    offset + start + len(quote.quote),
                    quote.quote,
                )
            )
        selected = self.engine.records_for(subject)
        allowed = set(self.catalog.scope_members(part.scope))
        selected = tuple(r for r in selected if {e.chunk_id for e in r.evidence} <= allowed)
        if len({e.chunk_id for r in selected for e in r.evidence}) > 16:
            raise ValueError("hours_source_inventory_exceeds_bound")
        day = None
        if supplied.date_value is not None:
            day = date.fromisoformat(supplied.date_value)
            if day.isoformat() != supplied.date_value:
                raise ValueError("hours_date_not_canonical")
        query = HoursQuery(
            subject=subject,
            mode="local" if supplied.intent == "local" else "now",
            local_date=day,
            hour=supplied.hour,
            minute=supplied.minute or 0,
            clock_basis=supplied.clock_basis,
        )
        assessment = self.engine.evaluate(
            query, now=now, record_ids=tuple(r.record_id for r in selected)
        )
        return ComputedHours(
            part.part_id, supplied, part.scope, query, tuple(bindings), selected, assessment
        )
