"""Display validated proposed source URLs without promoting them to evidence."""

from telescope_rag.api.hours_responses import HoursChatResponse
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import WorkflowRun
from telescope_rag.graph.source_choices import SourceChoicePlan, SourcePageChoiceBinding
from telescope_rag.ingestion.collection import canonical_url
from telescope_rag.retrieval.assembly import EvidenceCatalog

_MESSAGES = {
    "en": (
        "Which webpage should I use? Choose a URL below, or provide the exact Telescope page URL."
    ),
    "ar": "أي صفحة تريدني أن أستخدم؟ اختر رابطًا أدناه أو أرسل رابط صفحة تلسكوب المقصودة بالضبط.",
}


def project_source_choices(
    response: HoursChatResponse,
    run: WorkflowRun,
    *,
    catalog: EvidenceCatalog,
    bindings: SourceBindings,
) -> HoursChatResponse:
    """Rebind question/snapshot/document ownership; never emit arbitrary model text."""
    try:
        if type(run.plan) is not SourceChoicePlan or bindings._catalog is not catalog:
            raise ValueError
        records = run.plan.source_page_choices
        if len(records) > len(response.questions) or len({r.part_id for r in records}) != len(
            records
        ):
            raise ValueError
        parts = {p.part_id: p for p in run.plan.assembly_request.parts}
        questions = {q.id: q for q in response.questions}
        replacements = {}
        for record in records:
            if (
                type(record) is not SourcePageChoiceBinding
                or record.part_id not in parts
                or record.part_id not in questions
                or parts[record.part_id].state != "clarification_required"
                or questions[record.part_id].status != "clarification_required"
                or questions[record.part_id].reason_code != "ambiguous_request"
                or questions[record.part_id].question
                != run.plan.assembly_request.original_query[
                    parts[record.part_id].start : parts[record.part_id].end
                ]
                or questions[record.part_id].citation_ids
                or any(c.question_id == record.part_id for c in response.citations)
                or questions[record.part_id].hours is not None
                or record.snapshot_id != next(iter(catalog.chunks.values())).snapshot_id
                or record.prepared_digest != catalog.prepared_digest
                or not 2 <= len(record.document_handles) <= 4
                or len(set(record.document_handles)) != len(record.document_handles)
                or any(h not in bindings.documents for h in record.document_handles)
                or tuple(bindings.documents[h] for h in record.document_handles)
                != record.document_ids
            ):
                raise ValueError
            urls = []
            for identity in record.document_ids:
                members = [c for c in catalog.chunks.values() if c.document_id == identity]
                if not members or len({c.canonical_url for c in members}) != 1:
                    raise ValueError
                url = members[0].canonical_url
                if canonical_url(url) != url:
                    raise ValueError
                urls.append(url)
            if len(set(urls)) != len(urls):
                raise ValueError
            message = _MESSAGES["en" if response.language == "en" else "ar"]
            replacements[record.part_id] = message + "\n" + "\n".join(urls)
        projected = tuple(
            q.model_copy(update={"answer": replacements[q.id]}) if q.id in replacements else q
            for q in response.questions
        )
        return response.model_copy(
            update={
                "questions": projected,
                "answer": "\n\n".join(
                    f"{i}. {q.question}\n{q.answer}" for i, q in enumerate(projected, 1)
                ),
            }
        )
    except Exception:
        raise ValueError("offline_source_choice_response_invalid") from None
