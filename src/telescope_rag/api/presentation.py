"""Pure literal projection, never semantic admission, translation or answer generation."""

from datetime import UTC
from uuid import UUID

from telescope_rag.api.responses import (
    OfflineChatResponse,
    ResponseCitation,
    ResponseKnowledge,
    ResponseQuestion,
)
from telescope_rag.graph.contracts import WorkflowRequest, WorkflowResult, WorkflowRun
from telescope_rag.retrieval.assembly import AssemblyRequest, EvidenceCatalog, limited_to_context

_MESSAGES = {
    "en": {
        "candidate": "Source excerpt:",
        "not_found": "No usable public evidence was found for this part in the retrieved material.",
        "scope_excluded": "This part is outside the public website information service.",
        "ambiguous_request": "Please clarify this part of your question.",
        "context_only": "The retrieved material provides context but does not establish an answer.",
        "scope_incomplete": "The requested source scope was not completely represented.",
        "operation_unavailable": "A verified hours calculation is not available for this part.",
        "budget_limited": "The evidence limit prevented a complete evaluation of this part.",
        "draft_unavailable": "A validated draft is not available for this part.",
        "review": (
            "Offline draft for review; semantic support and live model compatibility "
            "remain unverified."
        ),
    },
    "ar": {
        "candidate": "مقتطف من المصدر:",
        "not_found": "لم يُعثر على أدلة عامة صالحة لهذا الجزء ضمن المواد المسترجعة.",
        "scope_excluded": "هذا الجزء خارج نطاق خدمة معلومات الموقع العام.",
        "ambiguous_request": "يرجى توضيح هذا الجزء من سؤالك.",
        "context_only": "توفّر المادة المسترجعة سياقاً لكنها لا تثبت إجابة عن هذا الجزء.",
        "scope_incomplete": "لم تُمثّل جميع المواد ضمن نطاق المصدر المطلوب.",
        "operation_unavailable": "لا يتوفر حساب متحقق منه لساعات العمل لهذا الجزء.",
        "budget_limited": "منع حد الأدلة إجراء تقييم كامل لهذا الجزء.",
        "draft_unavailable": "لا تتوفر مسودة متحقق منها لهذا الجزء.",
        "review": (
            "مسودة للمراجعة دون اتصال؛ لم يُتحقق بعد من الدعم الدلالي أو توافق النموذج الفعلي."
        ),
    },
}


def _project(run: WorkflowRun, catalog: EvidenceCatalog, request_id: UUID) -> OfflineChatResponse:
    if type(run) is not WorkflowRun or type(request_id) is not UUID or run.plan is None:
        raise ValueError
    request = WorkflowRequest.model_validate_json(run.request.model_dump_json())
    result = WorkflowResult.model_validate_json(run.result.model_dump_json())
    plan, evidence = run.plan, run.evidence
    assembly = AssemblyRequest.model_validate_json(plan.assembly_request.model_dump_json())
    parts = assembly.parts
    if (
        result.request_id != request_id.hex
        or result.error_code is not None
        or result.outcome == "failed"
        or result.language != plan.language
        or assembly.original_query != request.query
        or len(result.parts) != len(parts)
        or len(plan.operations) != len(parts)
        or tuple(p.part_id for p in result.parts)
        != tuple(f"{request_id.hex}-p{i}" for i in range(1, len(parts) + 1))
        or tuple(p.part_id for p in result.parts) != tuple(p.part_id for p in parts)
    ):
        raise ValueError
    if evidence is not None and (
        evidence.prepared_digest != catalog.prepared_digest
        or tuple(p.part_id for p in evidence.parts) != tuple(p.part_id for p in parts)
    ):
        raise ValueError
    expected_outcome = (
        "draft_ready"
        if any(p.status == "candidate" for p in result.parts)
        else "clarification_required"
        if any(p.status == "clarification_required" for p in result.parts)
        else "out_of_scope"
        if all(p.status == "excluded" for p in result.parts)
        else "not_found"
    )
    if result.outcome != expected_outcome:
        raise ValueError
    messages = _MESSAGES["en" if result.language == "en" else "ar"]
    questions, citations = [], []
    for index, (part, entry) in enumerate(zip(parts, result.parts, strict=True)):
        receipt = evidence.parts[index] if evidence is not None else None
        complete = receipt.admitted_scope_complete if receipt is not None else None
        if (
            entry.original_text != request.query[part.start : part.end]
            or entry.admitted_scope_complete != complete
            or (receipt is not None and receipt.original_text != entry.original_text)
            or (receipt is not None and receipt.state != part.state)
        ):
            raise ValueError
        if part.state != "public":
            expected_reason = "scope_excluded" if part.state == "excluded" else "ambiguous_request"
            if entry.status != part.state or entry.reason_code != expected_reason or entry.quotes:
                raise ValueError
        elif entry.status not in {"candidate", "unknown"}:
            raise ValueError
        allowed = {}
        if evidence is not None and part.state == "public" and complete is not False:
            for group in evidence.groups:
                ids = dict(group.part_occurrences).get(part.part_id, ())
                # Recheck the graph's offered citation capability, including
                # per-question context restrictions. Sidecar copies are not new citations.
                if ids and part.part_id not in group.context_only_parts:
                    allowed[ids[0]] = group.group_id
        if entry.status == "candidate":
            if (
                entry.reason_code is not None
                or not entry.quotes
                or len(entry.quotes) > 16
                or plan.operations[index] == "time_comparison"
                or len({q.chunk_id for q in entry.quotes}) != len(entry.quotes)
                or any(q.chunk_id not in allowed for q in entry.quotes)
                or (
                    part.scope.complete
                    and (
                        complete is not True
                        or {allowed[q.chunk_id] for q in entry.quotes} != set(allowed.values())
                    )
                )
            ):
                raise ValueError
        elif entry.quotes or entry.reason_code is None:
            raise ValueError
        elif part.state == "public" and entry.reason_code in {
            "scope_excluded",
            "ambiguous_request",
        }:
            raise ValueError
        if part.state == "public" and entry.status == "unknown":
            expected_reason = "not_found"
            if plan.operations[index] == "time_comparison":
                expected_reason = "operation_unavailable"
            elif complete is False:
                expected_reason = "scope_incomplete"
            elif not allowed and receipt is not None:
                if receipt.context_only:
                    expected_reason = "context_only"
                elif receipt.omitted_group_ids and not receipt.group_ids:
                    expected_reason = "budget_limited"
            if entry.reason_code != expected_reason:
                raise ValueError
        scope = set(catalog.scope_members(part.scope)) if entry.quotes else set()
        ids, excerpts = [], []
        for quote_index, quoted in enumerate(entry.quotes, start=1):
            source = catalog.chunks[quoted.chunk_id]
            if (
                source.chunk_id not in scope
                or limited_to_context(source, part.intended_use)
                or quoted.quote != source.retrieval_text
                or quoted.source_url != source.canonical_url
                or quoted.document_id != source.document_id
                or quoted.snapshot_id != source.snapshot_id
                or quoted.fetched_at != source.fetched_at
                or quoted.literal_owner_id != source.doctor_id
                or quoted.canonical_owner_id != source.canonical_doctor_id
                or source.fetched_at.utcoffset() is None
            ):
                raise ValueError
            identity = f"C{index + 1}.{quote_index}"
            citations.append(
                ResponseCitation(
                    id=identity,
                    question_id=part.part_id,
                    chunk_id=source.chunk_id,
                    document_id=source.document_id,
                    parent_block_id=source.parent_block_id,
                    url=source.canonical_url,
                    title=source.page_title,
                    section=source.section_path,
                    source_language=source.language,
                    fetched_at=source.fetched_at.astimezone(UTC),
                    snapshot_id=source.snapshot_id,
                    literal_owner_id=source.doctor_id,
                    literal_owner_name=source.doctor_name,
                    canonical_owner_id=source.canonical_doctor_id,
                    canonical_owner_name=source.canonical_doctor_name,
                    source_issue_codes=source.source_issue_codes,
                    quote=quoted.quote,
                )
            )
            ids.append(identity)
            excerpts.append(quoted.quote + f"\n[{identity}]")
        answer = messages["candidate" if entry.status == "candidate" else entry.reason_code]
        if excerpts:
            answer += "\n" + "\n\n".join(excerpts)
        questions.append(
            ResponseQuestion(
                id=part.part_id,
                question=entry.original_text,
                status=entry.status,
                answer=answer,
                citation_ids=tuple(ids),
                reason_code=entry.reason_code,
                admitted_scope_complete=entry.admitted_scope_complete,
            )
        )
    snapshots = {c.snapshot_id for c in citations}
    if len(snapshots) > 1:
        raise ValueError
    return OfflineChatResponse(
        request_id=str(request_id),
        status=result.outcome,
        language=result.language,
        answer="\n\n".join(f"{i}. {q.question}\n{q.answer}" for i, q in enumerate(questions, 1)),
        questions=tuple(questions),
        citations=tuple(citations),
        unresolved_questions=tuple(q.id for q in questions if q.status != "candidate"),
        knowledge=ResponseKnowledge(
            snapshot_id=citations[0].snapshot_id,
            prepared_digest=catalog.prepared_digest,
            fetched_at=min(c.fetched_at for c in citations),
        )
        if citations
        else None,
        review_notice=messages["review"],
    )


def project_response(
    run: WorkflowRun, *, catalog: EvidenceCatalog, request_id: UUID
) -> OfflineChatResponse:
    """Rebind literal results; fail without repairing, summarizing or assigning semantic truth."""
    try:
        return _project(run, catalog, request_id)
    except Exception:
        raise ValueError("offline_response_invalid") from None
