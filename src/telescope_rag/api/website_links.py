"""Independent publication of question-scoped, source-proven outgoing links."""

from telescope_rag.api.hours_responses import HoursChatResponse, ResponseWebsiteLink
from telescope_rag.graph.contracts import WorkflowRun
from telescope_rag.knowledge.public_links import PublicLinksCatalog


def project_website_links(
    response: HoursChatResponse,
    run: WorkflowRun,
    catalog: PublicLinksCatalog,
) -> HoursChatResponse:
    if run.plan is None:
        raise ValueError("website_links_plan_missing")
    entries = {p.part_id: p for p in run.conversation.parts} if run.conversation else {}
    questions, links = [], []
    for index, question in enumerate(response.questions):
        part = run.plan.assembly_request.parts[index]
        allowed = set(catalog.eligible(part, run.plan.operations[index]))
        # Recheck fixed outcomes separately from the model's support selections.
        if question.status != "candidate" and not (
            question.status == "unknown" and question.reason_code == "not_found"
        ):
            allowed.clear()
        entry = entries.get(question.id)
        selected = (
            tuple(
                dict.fromkeys(
                    identity
                    for sentence in entry.sentences
                    for identity in getattr(sentence, "website_link_ids", ())
                )
            )
            if entry
            else ()
        )
        if any(identity not in allowed for identity in selected) or (
            selected and (entry.status != "candidate" or entry.reason_code is not None)
        ):
            raise ValueError("website_links_scope_mismatch")
        if selected:
            question = question.model_copy(
                update={
                    "status": "candidate",
                    "reason_code": None,
                    "website_link_ids": selected,
                }
            )
            links.extend(
                ResponseWebsiteLink(**catalog.links[i].model_dump(), question_id=question.id)
                for i in selected
            )
        questions.append(question)
    status = (
        "draft_ready"
        if any(q.status == "candidate" for q in questions)
        else "clarification_required"
        if any(q.status == "clarification_required" for q in questions)
        else "out_of_scope"
        if all(q.status == "excluded" for q in questions)
        else "not_found"
    )
    return response.model_copy(
        update={
            "questions": tuple(questions),
            "website_links": tuple(links),
            "website_links_digest": catalog.digest,
            "status": status,
            "unresolved_questions": tuple(q.id for q in questions if q.status != "candidate"),
        }
    )
