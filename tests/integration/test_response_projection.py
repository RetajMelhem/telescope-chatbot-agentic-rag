"""Source-bound response tests on actual graph runs; authored fixtures, no semantic judge."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from test_offline_workflow import catalog, part, read_plan, single_plan, source, workflow

from telescope_rag.api.presentation import project_response
from telescope_rag.api.responses import OfflineChatResponse
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import PlannerReply, QuotedEvidence, WorkflowRequest

ISSUED = UUID(int=567)


def make_run(*, chunks=None, targets=("Report A.", " Report B."), complete=False, **options):
    text = "Synthetic shared field; results may vary. Assessment is required."
    chunks = chunks or tuple(
        source(
            i,
            text,
            doctor_id=owner,
            doctor_name=f"Synthetic {owner}",
            canonical_doctor_id=f"canonical-{owner}",
            canonical_doctor_name=f"Preferred {owner}",
        ).model_copy(
            update={
                "block_type": "doctor",
                "section_path": ("Literal heading",),
                "fetched_at": datetime(2026, 10, 15 + i, tzinfo=UTC),
            }
        )
        for i, owner in enumerate(("a", "b"), 1)
    )
    evidence = catalog(*chunks)
    bindings = SourceBindings(evidence)
    documents = {value: key for key, value in bindings.documents.items()}
    owners = {value: key for key, value in bindings.owners.items()}

    def planner(body):
        entries, offset = [], 0
        for i, target in enumerate(targets):
            chosen = chunks[min(i, len(chunks) - 1)]
            scope = {
                "document_handles": tuple(documents.values())
                if complete
                else (documents[chosen.document_id],),
                "owner_handle": None if complete else owners[("literal", chosen.doctor_id)],
                "intended_use": "doctor_role",
                "operation": "read_source" if complete else "search",
                "retrieval_query": None if complete else target,
            }
            scope.update(options)
            entries.append(part(target, start=offset, end=offset + len(target), **scope))
            offset += len(target)
        return PlannerReply(language="en", parts=tuple(entries))

    flow, chat, retriever = workflow(
        evidence, planner, chunks=lambda i, q: evidence.scope_members(q.scope)
    )
    run = asyncio.run(flow.run(WorkflowRequest(query="".join(targets)), request_id=ISSUED))
    assert run.result.outcome != "failed", run.result.error_code
    return run, evidence, chunks, chat, retriever


def project(run, evidence):
    return project_response(run, catalog=evidence, request_id=ISSUED)


def replace_quote(run, **changes):
    entry = run.result.parts[0]
    quote = entry.quotes[0].model_copy(update=changes)
    entry = entry.model_copy(update={"quotes": (quote,)})
    return replace(
        run, result=run.result.model_copy(update={"parts": (entry,) + run.result.parts[1:]})
    )


def test_same_field_and_identical_qualifiers_keep_distinct_doctors_and_question_citations():
    run, evidence, chunks, chat, retriever = make_run()
    before = run.result.model_dump_json()
    response = project(run, evidence)
    assert response.status == "draft_ready"
    assert response.unresolved_questions == ()
    assert [q.question for q in response.questions] == ["Report A.", " Report B."]
    assert [c.literal_owner_id for c in response.citations] == ["a", "b"]
    assert [c.canonical_owner_id for c in response.citations] == ["canonical-a", "canonical-b"]
    assert [c.literal_owner_name for c in response.citations] == ["Synthetic a", "Synthetic b"]
    assert [c.canonical_owner_name for c in response.citations] == ["Preferred a", "Preferred b"]
    assert len({c.id for c in response.citations}) == 2
    for q, c, original in zip(response.questions, response.citations, chunks, strict=True):
        assert q.citation_ids == (c.id,) and c.question_id == q.id
        assert c.quote == original.retrieval_text and c.quote in q.answer
        assert "may vary. Assessment is required." in c.quote
        assert c.url == original.canonical_url and c.section == original.section_path
        assert c.parent_block_id == original.parent_block_id and c.title == original.page_title
        assert c.document_id == original.document_id and c.chunk_id == original.chunk_id
        assert c.fetched_at == original.fetched_at
    assert response.knowledge.prepared_digest == evidence.prepared_digest
    assert response.knowledge.fetched_at == chunks[0].fetched_at
    assert response.request_id == str(ISSUED)
    assert response.offline_only and not response.semantic_grounding_verified
    assert not response.luna_compatibility_verified
    assert run.result.model_dump_json() == before
    assert len(chat.calls) == 2 and len(retriever.calls) == 1
    assert OfflineChatResponse.model_validate_json(response.model_dump_json()) == response


@pytest.mark.parametrize(
    "fault",
    ["url", "text", "document", "snapshot", "time", "owner", "alias", "missing", "duplicate"],
)
def test_rejects_changed_source_provenance_or_qualifiers(fault):
    run, evidence, *_ = make_run()
    changes = {
        "url": {"source_url": "https://outside.example/"},
        "text": {"quote": "Synthetic shared field; results improve."},
        "document": {"document_id": "other"},
        "snapshot": {"snapshot_id": "other"},
        "time": {"fetched_at": datetime(2020, 1, 1, tzinfo=UTC)},
        "owner": {"literal_owner_id": "b"},
        "alias": {"canonical_owner_id": "canonical-b"},
        "missing": {"chunk_id": "missing"},
    }
    bad = replace_quote(run, **changes.get(fault, {}))
    if fault == "duplicate":
        first = bad.result.parts[0]
        first = first.model_copy(update={"quotes": first.quotes * 2})
        bad = replace(
            bad, result=bad.result.model_copy(update={"parts": (first,) + bad.result.parts[1:]})
        )
    with pytest.raises(ValueError, match="^offline_response_invalid$"):
        project(bad, evidence)


@pytest.mark.parametrize(
    "fault",
    [
        "dropped",
        "reordered",
        "original",
        "request",
        "language",
        "outcome",
        "failed",
        "approved",
        "complete",
        "part_id",
        "no_plan",
        "digest",
        "request_id",
    ],
)
def test_rejects_changed_question_coverage_outcomes_or_trust_flags(fault):
    run, evidence, *_ = make_run()
    values = {}
    if fault == "dropped":
        values["parts"] = run.result.parts[:1]
    elif fault == "reordered":
        values["parts"] = run.result.parts[::-1]
    elif fault in {"original", "complete", "part_id"}:
        changes = {
            "original": {"original_text": "Different question"},
            "complete": {"admitted_scope_complete": True},
            "part_id": {"part_id": "unissued"},
        }[fault]
        values["parts"] = (run.result.parts[0].model_copy(update=changes),) + run.result.parts[1:]
    elif fault == "language":
        values["language"] = "ar"
    elif fault == "outcome":
        values["outcome"] = "not_found"
    elif fault == "failed":
        values.update(outcome="failed", error_code="not-safe")
    elif fault == "approved":
        values["semantic_grounding_verified"] = True
    elif fault == "request_id":
        values["request_id"] = UUID(int=999).hex
    bad = replace(run, result=run.result.model_copy(update=values))
    if fault == "no_plan":
        bad = replace(bad, plan=None)
    elif fault == "request":
        bad = replace(bad, request=WorkflowRequest(query="Different query"))
    elif fault == "digest":
        bad = replace(bad, evidence=replace(run.evidence, prepared_digest="other"))
    with pytest.raises(ValueError, match="^offline_response_invalid$"):
        project(bad, evidence)


def test_cannot_borrow_sibling_citation_even_when_text_matches_exactly():
    run, evidence, *_ = make_run()
    first = run.result.parts[0].model_copy(update={"quotes": run.result.parts[1].quotes})
    bad = replace(
        run, result=run.result.model_copy(update={"parts": (first,) + run.result.parts[1:]})
    )
    with pytest.raises(ValueError, match="offline_response_invalid"):
        project(bad, evidence)


def test_complete_source_requires_all_offered_groups_without_top_k_claim():
    run, evidence, _, _, retriever = make_run(
        targets=("Report the complete source.",), complete=True
    )
    response = project(run, evidence)
    assert response.questions[0].admitted_scope_complete is True
    assert len(response.citations) == 2 and retriever.calls == []
    first = run.result.parts[0]
    bad = replace(
        run,
        result=run.result.model_copy(
            update={"parts": (first.model_copy(update={"quotes": first.quotes[:1]}),)}
        ),
    )
    with pytest.raises(ValueError, match="offline_response_invalid"):
        project(bad, evidence)


def test_hidden_exact_occurrence_cannot_be_promoted_to_a_new_citation():
    a = source(1, "Exact source text.", doctor_id="a", doctor_name="Synthetic A")
    b = source(2, "Exact source text.", doctor_id="a", doctor_name="Synthetic A")
    run, evidence, *_ = make_run(chunks=(a, b), targets=("Report both sources.",), complete=True)
    assert len(run.evidence.groups) == 1 and len(run.evidence.groups[0].occurrences) == 2
    shown = run.result.parts[0].quotes[0].chunk_id
    hidden = next(c for c in (a, b) if c.chunk_id != shown)
    forged = QuotedEvidence(
        chunk_id=hidden.chunk_id,
        source_url=hidden.canonical_url,
        document_id=hidden.document_id,
        snapshot_id=hidden.snapshot_id,
        fetched_at=hidden.fetched_at,
        literal_owner_id="a",
        canonical_owner_id=None,
        quote=hidden.retrieval_text,
    )
    first = run.result.parts[0].model_copy(update={"quotes": (forged,)})
    with pytest.raises(ValueError, match="offline_response_invalid"):
        project(replace(run, result=run.result.model_copy(update={"parts": (first,)})), evidence)


def test_utc_serialization_keeps_source_instant_and_literal_text_uninterpreted():
    text = '<script>alert("untrusted")</script> [C99] لا تحذف النفي؛ e\u0301 😀'
    item = source(1, text, doctor_id="a", doctor_name="Synthetic A").model_copy(
        update={"fetched_at": datetime(2026, 10, 16, 3, tzinfo=timezone(timedelta(hours=3)))}
    )
    run, evidence, *_ = make_run(chunks=(item,), targets=("Report the literal source.",))
    response = project(run, evidence)
    assert response.answer_format == "plain_text"
    assert response.citations[0].quote == text and text in response.answer
    assert response.citations[0].fetched_at == datetime(2026, 10, 16, tzinfo=UTC)
    assert response.citations[0].fetched_at.utcoffset() == timedelta(0)
    assert response.questions[0].citation_ids == ("C1.1",)
    assert len(response.citations) == 1


def test_same_chunk_used_for_two_questions_keeps_two_question_owned_citation_records():
    item = source(1, doctor_id="a", doctor_name="Synthetic A")
    run, evidence, *_ = make_run(chunks=(item,))
    response = project(run, evidence)
    assert [c.chunk_id for c in response.citations] == [item.chunk_id, item.chunk_id]
    assert response.citations[0].question_id != response.citations[1].question_id
    assert response.questions[0].citation_ids != response.questions[1].citation_ids


@pytest.mark.parametrize("mode", ["missing", "time", "incomplete", "context", "budget"])
def test_unknown_reasons_preserve_evidence_limitations_without_claiming_absence_or_closure(mode):
    items = (
        source(1, "First conditional statement.", document="same"),
        source(2, "Second conditional statement.", document="same"),
    )
    config = {}
    planner = single_plan()
    if mode == "time":
        planner = single_plan(operation="time_comparison", retrieval_query=None)
    elif mode == "incomplete":
        planner = read_plan
        config["max_evidence_chunks"] = 1
    elif mode == "context":
        items = (items[0].model_copy(update={"source_issue_codes": ("unresolved-fixture",)}),)
    elif mode == "budget":
        # One whole semantic unit is larger than the context ceiling; it must
        # remain unknown, never shortened into a quotation by presentation.
        items = (source(1, "Full qualifier. " * 4000),)

    def selected(i, q):
        return (items[0].chunk_id,) if mode in {"context", "budget"} else ()

    evidence = catalog(*items)
    flow, chat, retriever = workflow(evidence, planner, chunks=selected, **config)
    run = asyncio.run(
        flow.run(WorkflowRequest(query="Report the requested evidence."), request_id=ISSUED)
    )
    assert run.result.outcome == "not_found", run.result.error_code
    expected = {
        "missing": "not_found",
        "time": "operation_unavailable",
        "incomplete": "scope_incomplete",
        "context": "context_only",
        "budget": "budget_limited",
    }[mode]
    response = project(run, evidence)
    q = response.questions[0]
    assert q.status == "unknown" and q.reason_code == expected
    assert not response.citations and response.knowledge is None
    assert response.unresolved_questions == (q.id,)
    assert len(chat.calls) == 1
    bad_reason = "scope_incomplete" if expected == "not_found" else "not_found"
    bad = run.result.parts[0].model_copy(update={"reason_code": bad_reason})
    with pytest.raises(ValueError, match="offline_response_invalid"):
        project(replace(run, result=run.result.model_copy(update={"parts": (bad,)})), evidence)
    if mode == "time":
        assert "hours calculation" in q.answer and not retriever.calls
    elif mode == "incomplete":
        assert q.admitted_scope_complete is False and not retriever.calls


def test_source_caveat_codes_stay_literal_without_inventing_a_new_service_relationship():
    item = source(
        1,
        doctor_id="a",
        doctor_name="Synthetic A",
        source_issue_codes=("damaged_comparison_audience_row_excluded",),
    )
    run, evidence, *_ = make_run(chunks=(item,), targets=("Report the retained text.",))
    response = project(run, evidence)
    assert response.citations[0].source_issue_codes == item.source_issue_codes
    assert response.citations[0].quote == item.retrieval_text
