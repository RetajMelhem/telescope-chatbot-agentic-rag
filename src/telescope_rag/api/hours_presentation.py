"""Source-bound offline hours projection; no question parsing or semantic certification."""

from datetime import UTC
from uuid import UUID

from telescope_rag.api.hours_responses import (
    HoursChatResponse,
    HoursResponseQuestion,
    ResponseHours,
)
from telescope_rag.api.presentation import project_response
from telescope_rag.api.responses import ResponseCitation, ResponseKnowledge
from telescope_rag.graph.contracts import WorkflowRun
from telescope_rag.graph.hours_inputs import HoursBindings
from telescope_rag.graph.hours_projection import hours_decision
from telescope_rag.graph.hours_records import ComputedHours
from telescope_rag.retrieval.assembly import EvidenceCatalog

_WEEKDAYS = {
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "ar": ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"),
}
_TEXT = {
    "en": {
        "schedule": "Published hours (Asia/Amman):",
        "within_posted_hours": "The specified time is within the published hours.",
        "outside_posted_hours": "The specified time is outside the published hours.",
        "unknown": "The available public hours evidence does not establish this answer.",
        "ambiguous_subject": "Which center, facility or doctor do you mean?",
        "missing_date": "Which calendar date do you mean?",
        "ambiguous_time": "Do you mean AM or PM?",
        "ambiguous_same": "AM/PM was unspecified; both interpretations give this hours result.",
        "clarification": "Please clarify the local date or time.",
        "closed": "Published as closed",
        "unknown_day": "Unlisted days remain unknown.",
        "midnight": "24:00 (midnight at the end of the day)",
        "next_day": "next day",
        "limits": (
            "This describes published hours. Actual attendance and appointment availability "
            "are not verified. Full source wording and qualifiers are in the cited excerpts."
        ),
        "exceptions": "Unpublished dated or holiday exceptions remain unverified.",
        "valid_from": "Valid from",
        "valid_through": "Valid through",
    },
    "ar": {
        "schedule": "ساعات العمل المنشورة (Asia/Amman):",
        "within_posted_hours": "الوقت المحدد ضمن ساعات العمل المنشورة.",
        "outside_posted_hours": "الوقت المحدد خارج ساعات العمل المنشورة.",
        "unknown": "لا تثبت أدلة ساعات العمل العامة المتاحة إجابة عن هذا الجزء.",
        "ambiguous_subject": "أي مركز أو مرفق أو طبيب تقصد؟",
        "missing_date": "أي تاريخ محدد تقصد؟",
        "ambiguous_time": "هل تقصد صباحاً أم مساءً؟",
        "ambiguous_same": "لم يُحدد صباحاً أو مساءً؛ كلا التفسيرين يعطي النتيجة نفسها لساعات العمل.",
        "clarification": "يرجى توضيح التاريخ أو الوقت المحلي.",
        "closed": "مغلق حسب المنشور",
        "unknown_day": "أيام العمل غير المذكورة تبقى غير معروفة.",
        "midnight": "24:00 (منتصف الليل في نهاية اليوم)",
        "next_day": "اليوم التالي",
        "limits": (
            "هذه معلومات ساعات العمل المنشورة. لم يُتحقق من الحضور الفعلي أو توفر المواعيد. "
            "النص الكامل والقيود محفوظة في مقتطفات المصادر المشار إليها."
        ),
        "exceptions": "الاستثناءات غير المنشورة للتواريخ والعطل غير متحقق منها.",
        "valid_from": "يسري من",
        "valid_through": "يسري حتى",
    },
}


def _clock_text(minutes: int, messages: dict[str, str]) -> str:
    if minutes == 1440:
        return messages["midnight"]
    text = f"{minutes % 1440 // 60:02d}:{minutes % 60:02d}"
    return text + (f" ({messages['next_day']})" if minutes > 1440 else "")


def _answer(summary: ResponseHours, language: str) -> str:
    lang = "en" if language == "en" else "ar"
    messages = _TEXT[lang]
    if summary.status == "schedule_available":
        record = summary.schedules[0]
        rows = [messages["schedule"]]
        grouped: dict[str, list[str]] = {}
        for rule in sorted(record.weekly, key=lambda r: r.weekday):
            value = (
                messages["closed"]
                if rule.state == "closed"
                else "; ".join(
                    f"{_clock_text(i.opens, messages)} – {_clock_text(i.closes, messages)}"
                    for i in rule.intervals
                )
            )
            grouped.setdefault(value, []).append(_WEEKDAYS[lang][rule.weekday])
        rows.extend(", ".join(days) + ": " + value for value, days in grouped.items())
        if len(record.weekly) != 7:
            rows.append(messages["unknown_day"])
        for rule in sorted(record.exceptions, key=lambda r: r.on_date):
            value = (
                messages["closed"]
                if rule.state == "closed"
                else "; ".join(
                    f"{_clock_text(i.opens, messages)} – {_clock_text(i.closes, messages)}"
                    for i in rule.intervals
                )
            )
            rows.append(f"{rule.on_date.isoformat()}: {value}")
        for field in ("valid_from", "valid_through"):
            if getattr(record, field) is not None:
                rows.append(f"{messages[field]}: {getattr(record, field).isoformat()}")
        rows.append(messages["limits"])
        rows.append(messages["exceptions"])
        return "\n".join(rows)
    if summary.status == "clarification_required":
        return messages.get(summary.reason, messages["clarification"])
    if summary.status == "unknown":
        return messages["unknown"]
    rows = [messages[summary.status]]
    rows.extend(t.isoformat() for t in summary.local_candidates)
    if summary.clock_ambiguous:
        # Both candidates are exposed even when their hours outcomes agree.
        rows.append(messages["ambiguous_same"])
    rows.append(messages["limits"])
    if summary.dated_exceptions_unverified:
        rows.append(messages["exceptions"])
    return "\n".join(rows)


def _project_hours(
    run: WorkflowRun,
    catalog: EvidenceCatalog,
    request_id: UUID,
    bindings: HoursBindings,
) -> HoursChatResponse:
    baseline = project_response(run, catalog=catalog, request_id=request_id)
    if (
        bindings.catalog is not catalog
        or run.plan is None
        or run.operation_clock is None
        or run.operation_clock.utcoffset() is None
        or len(run.answer_targets) != len(run.plan.operations)
    ):
        raise ValueError
    expected = tuple(
        p.part_id
        for p, op in zip(run.plan.assembly_request.parts, run.plan.operations, strict=True)
        if p.state == "public" and op == "time_comparison"
    )
    if tuple(r.part_id for r in run.computed_hours) != expected:
        raise ValueError
    operations = {r.part_id: r for r in run.computed_hours}
    questions, citations = [], list(baseline.citations)
    for index, (part, original, target) in enumerate(
        zip(run.plan.assembly_request.parts, baseline.questions, run.answer_targets, strict=True)
    ):
        operation = operations.get(part.part_id)
        if operation is None:
            questions.append(HoursResponseQuestion(**original.model_dump(), hours=None))
            continue
        if (
            type(operation) is not ComputedHours
            or target.part_id != part.part_id
            or target.target.start != part.start
            or target.target.end != part.end
            or target.target.quote != original.question
        ):
            raise ValueError
        rebound = bindings.bind(
            operation.supplied,
            part=part,
            request=run.request,
            reference_text=target.reference_text,
            history_indices=target.history_indices,
            now=run.operation_clock,
        )
        if rebound != operation:
            raise ValueError
        assessment = operation.assessment
        decision = hours_decision(
            operation,
            part=part,
            evidence=run.evidence,
            catalog=catalog,
            max_age=bindings.engine.max_source_age,
            admitted_scope_complete=original.admitted_scope_complete,
        )
        status, reason, proof_present = decision.status, decision.reason, decision.proof_present
        ids = []
        for citation_index, source in enumerate(assessment.evidence if proof_present else (), 1):
            identity = f"C{index + 1}.{citation_index}"
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
                    quote=source.retrieval_text,
                )
            )
            ids.append(identity)
        summary = ResponseHours(
            intent=operation.supplied.intent,
            subject=assessment.subject,
            status=status,
            reason=reason,
            evaluated_at=assessment.evaluated_at,
            local_candidates=()
            if operation.supplied.intent == "schedule"
            else assessment.local_candidates,
            clock_ambiguous=assessment.clock_ambiguous,
            dated_exception_applied=False
            if operation.supplied.intent == "schedule"
            else assessment.dated_exception_applied,
            dated_exceptions_unverified=True
            if operation.supplied.intent == "schedule"
            else assessment.dated_exceptions_unverified,
            schedules=operation.schedules if proof_present else (),
        )
        answer = _answer(summary, baseline.language)
        if ids:
            answer += "\n" + " ".join(f"[{i}]" for i in ids)
        questions.append(
            HoursResponseQuestion(
                **(
                    original.model_dump()
                    | {
                        "status": decision.draft_status,
                        "answer": answer,
                        "citation_ids": tuple(ids),
                        "reason_code": decision.reason_code,
                    }
                ),
                hours=summary,
            )
        )
    status = (
        "draft_ready"
        if any(q.status == "candidate" for q in questions)
        else "clarification_required"
        if any(q.status == "clarification_required" for q in questions)
        else "out_of_scope"
        if all(q.status == "excluded" for q in questions)
        else "not_found"
    )
    if (
        len({c.id for c in citations}) != len(citations)
        or len({c.snapshot_id for c in citations}) > 1
    ):
        raise ValueError
    return HoursChatResponse(
        **(
            baseline.model_dump(exclude={"schema_version", "questions"})
            | {
                "status": status,
                "questions": tuple(questions),
                "citations": tuple(citations),
                "answer": "\n\n".join(
                    f"{i}. {q.question}\n{q.answer}" for i, q in enumerate(questions, 1)
                ),
                "unresolved_questions": tuple(q.id for q in questions if q.status != "candidate"),
                "knowledge": ResponseKnowledge(
                    snapshot_id=citations[0].snapshot_id,
                    prepared_digest=catalog.prepared_digest,
                    fetched_at=min(c.fetched_at for c in citations),
                )
                if citations
                else None,
            }
        )
    )


def project_hours_response(
    run: WorkflowRun,
    *,
    catalog: EvidenceCatalog,
    request_id: UUID,
    bindings: HoursBindings,
) -> HoursChatResponse:
    try:
        return _project_hours(run, catalog, request_id, bindings)
    except Exception:
        raise ValueError("offline_hours_response_invalid") from None
