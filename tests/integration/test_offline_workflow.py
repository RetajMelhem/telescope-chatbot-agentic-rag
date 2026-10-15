"""Synthetic end-to-end LangGraph checks; no real clinic facts or provider/index calls."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from telescope_rag.api.main import create_app
from telescope_rag.core.settings import Settings
from telescope_rag.graph.contracts import (
    AnswerDraft,
    PartDraft,
    PlannerPart,
    PlannerReply,
    QuoteDraft,
    RetrievalBatch,
    RetrievedPart,
    WorkflowRequest,
)
from telescope_rag.graph.workflow import OfflineRagWorkflow
from telescope_rag.ingestion.models import (
    ExtractedDocument,
    PreparedChunk,
    PreparedDocument,
    RawPage,
    SourceSpan,
)
from telescope_rag.ingestion.review import prepared_digest
from telescope_rag.providers.contracts import (
    AttemptReceipt,
    StructuredResult,
    TokenCount,
    UsageReport,
)
from telescope_rag.retrieval.assembly import EvidenceCatalog


class SyntheticCounter:
    verified = True
    version = "synthetic-character-units-not-production-tokens"

    def count(self, text):
        return len(text)


def source(
    number, text="Synthetic result may improve gradually; assessment is required.", **changes
):
    document = changes.pop("document", f"synthetic-document-{number}")
    span = SourceSpan(
        block_id=f"synthetic-span-{number}",
        locator="main > p",
        original_text=text,
        end=len(text),
    )
    return PreparedChunk(
        chunk_id=f"synthetic-chunk-{number}",
        point_id=str(UUID(int=number)),
        document_id=document,
        canonical_url=f"https://telescopecenter.com/synthetic-{document}/",
        page_title="Synthetic fixture",
        snapshot_id="synthetic-offline-snapshot",
        fetched_at=datetime(2026, 10, 16, tzinfo=UTC),
        parent_block_id=f"synthetic-parent-{number}",
        block_type="section",
        language="en",
        section_path=(),
        admission_policy_hash="synthetic-policy",
        source_spans=(span,),
        original_text=text,
        retrieval_text=text,
        content_hash=f"synthetic-content-{number}",
        token_count=8,
        tokenizer_version="synthetic",
        embedding_format_version="synthetic",
        embedding_format_hash="synthetic",
        embedding_ready=True,
        **changes,
    )


def catalog(*chunks):
    grouped = {}
    for chunk in chunks:
        grouped.setdefault(chunk.document_id, []).append(chunk)
    documents = tuple(
        PreparedDocument(
            document=ExtractedDocument(
                page=RawPage(
                    snapshot_id=values[0].snapshot_id,
                    document_id=identity,
                    canonical_url=values[0].canonical_url,
                    fetched_at=values[0].fetched_at,
                    content_hash="synthetic-html-hash",
                    html="<main><p>Synthetic fixture only.</p></main>",
                ),
                title="Synthetic fixture",
                units=(),
            ),
            chunks=tuple(values),
            embedding_ready=True,
        )
        for identity, values in grouped.items()
    )
    return EvidenceCatalog(documents, expected_digest=prepared_digest(documents))


def part(query, **updates):
    fields = {
        "start": 0,
        "end": len(query),
        "state": "public",
        "operation": "search",
        "intended_use": "general_excerpt",
        "retrieval_query": query,
        "document_handles": (),
        "owner_handle": None,
        "block_types": (),
        "source_language": None,
        "reference_text": None,
        "history_indices": (),
        "reason": None,
    }
    fields.update(updates)
    return PlannerPart(**fields)


def charge(budget, kind, output):
    operation = budget.begin(kind)
    count = TokenCount(
        units=10,
        model="synthetic-model",
        profile="synthetic-fixture-not-provider-counts",
        basis="exact",
    )
    reservation = budget.reserve(kind, count, output)
    usage = UsageReport(input_tokens=10, output_tokens=5 if kind == "chat" else None)
    budget.settle(reservation, usage)
    receipt = AttemptReceipt(
        operation=operation,
        kind=kind,
        attempt=1,
        requested_model="synthetic-model",
        reported_model="synthetic-model",
        provider="synthetic-offline-fake",
        status_code=200,
        outcome="success",
        input_reserved=10,
        output_reserved=output,
        count_profile=count.profile,
        count_basis=count.basis,
        usage=usage,
    )
    budget.record(receipt)
    return receipt


class FakeChat:
    def __init__(self, evidence, planner, draft=None):
        self.evidence = evidence
        self.planner = planner
        self.draft = draft
        self.calls = []
        self.entered = None
        self.release = None

    async def complete(self, messages, output_model, *, max_output_tokens, budget):
        body = json.loads(messages[-1].content)
        self.calls.append((output_model, body, budget))
        receipt = charge(budget, "chat", max_output_tokens)
        if output_model is PlannerReply:
            value = self.planner(body)
        else:
            if self.entered is not None:
                self.entered.set()
                await self.release.wait()
            if self.draft is not None:
                value = self.draft(body)
            else:
                value = AnswerDraft(
                    parts=tuple(
                        PartDraft(
                            part_id=item["part_id"],
                            status="candidate",
                            quotes=tuple(
                                QuoteDraft(
                                    chunk_id=identity,
                                    quote=self.evidence.chunks[identity].retrieval_text,
                                )
                                for identity in item["eligible_quote_chunk_ids"]
                            ),
                            reason_code=None,
                        )
                        for item in body["parts"]
                    )
                )
        return StructuredResult(value, (receipt,))


class FakeRetriever:
    def __init__(self, chunks, mutate: Callable | None = None):
        self.chunks = chunks
        self.mutate = mutate
        self.calls = []

    async def retrieve(self, queries, *, snapshot_id, prepared_digest, budget):
        self.calls.append((tuple(queries), budget))
        charge(budget, "embedding", 0)
        value = RetrievalBatch(
            snapshot_id=snapshot_id,
            prepared_digest=prepared_digest,
            parts=tuple(
                RetrievedPart(part_id=query.part_id, chunk_ids=tuple(self.chunks(index, query)))
                for index, query in enumerate(queries)
            ),
        )
        return self.mutate(value) if self.mutate else value


def workflow(evidence, planner, *, draft=None, chunks=None, mutate=None, **settings):
    config = Settings(
        _env_file=None,
        app_env="test",
        provider_max_retries=0,
        max_evidence_tokens=settings.pop("max_evidence_tokens", 12000),
        max_total_input_tokens=settings.pop("max_total_input_tokens", 16000),
        **settings,
    )
    chat = FakeChat(evidence, planner, draft)
    retriever = FakeRetriever(chunks or (lambda i, q: tuple(evidence.chunks)), mutate)
    flow = OfflineRagWorkflow(
        settings=config,
        chat=chat,
        retriever=retriever,
        catalog=evidence,
        counter=SyntheticCounter(),
        token_basis="synthetic_test",
    )
    return flow, chat, retriever


def single_plan(language="en", **updates):
    return lambda body: PlannerReply(
        language=language,
        parts=(part(body["original_query"], **updates),),
    )


@pytest.mark.parametrize(
    "language,query,text",
    [
        ("en", "What does this synthetic source say?", "Synthetic result may improve gradually."),
        ("ar", "ماذا يقول المصدر التجريبي؟", "نص تجريبي: قد تتحسن النتيجة تدريجياً بعد التقييم."),
        ("ar-JO", "شو بحكي المصدر التجريبي؟", "نص تجريبي: ممكن تتحسن النتيجة شوي شوي حسب التقييم."),
    ],
)
def test_actual_graph_two_stage_quotes_preserve_language_and_shared_budget(language, query, text):
    item = source(1, text)
    flow, chat, retriever = workflow(catalog(item), single_plan(language))
    run = asyncio.run(flow.run(WorkflowRequest(query=query)))
    assert run.result.outcome == "draft_ready"
    assert run.result.language == language
    quote = run.result.parts[0].quotes[0]
    assert quote.quote == text
    assert (quote.chunk_id, quote.source_url, quote.document_id) == (
        item.chunk_id,
        item.canonical_url,
        item.document_id,
    )
    assert quote.fetched_at == item.fetched_at
    assert run.result.offline_only
    assert not run.result.semantic_grounding_verified
    assert not run.result.luna_compatibility_verified
    assert not run.plan.semantic_interpretation_verified
    assert not run.evidence.semantic_support_assessed
    assert run.evidence.token_basis == "synthetic_test"
    assert run.stages == (
        "validate_request",
        "plan_query",
        "validate_plan",
        "retrieve_evidence",
        "assemble_evidence",
        "generate_draft",
        "validate_draft",
    )
    assert [entry[0] for entry in chat.calls] == [PlannerReply, AnswerDraft]
    assert chat.calls[0][2] is chat.calls[1][2] is retriever.calls[0][1]
    assert (run.usage.logical_chat_calls, run.usage.logical_embedding_calls) == (2, 1)
    assert (run.usage.physical_chat_attempts, run.usage.physical_embedding_attempts) == (2, 1)
    assert (run.usage.charged_chat_input, run.usage.charged_embedding_input) == (20, 10)
    assert run.usage.charged_output == 10
    assert len(run.usage.receipts) == 3


def test_public_excluded_and_ambiguous_siblings_survive_without_retrieval_cross_assignment():
    query = "Published fact. Private file. Which doctor?"
    segments = [(0, 15), (15, 29), (29, len(query))]
    item = source(1)
    evidence = catalog(item)

    def planner(body):
        return PlannerReply(
            language="en",
            parts=(
                part(query, start=segments[0][0], end=segments[0][1]),
                part(
                    query,
                    start=segments[1][0],
                    end=segments[1][1],
                    state="excluded",
                    retrieval_query=None,
                    reason="Synthetic private-record exclusion.",
                ),
                part(
                    query,
                    start=segments[2][0],
                    end=segments[2][1],
                    state="clarification_required",
                    retrieval_query=None,
                    reason="Synthetic identity ambiguity.",
                ),
            ),
        )

    def draft(body):
        identities = [p["part_id"] for p in body["parts"]]
        return AnswerDraft(
            parts=(
                PartDraft(
                    part_id=identities[0],
                    status="candidate",
                    quotes=(QuoteDraft(chunk_id=item.chunk_id, quote=item.retrieval_text),),
                    reason_code=None,
                ),
                PartDraft(
                    part_id=identities[1],
                    status="excluded",
                    quotes=(),
                    reason_code="scope_excluded",
                ),
                PartDraft(
                    part_id=identities[2],
                    status="clarification_required",
                    quotes=(),
                    reason_code="ambiguous_request",
                ),
            )
        )

    flow, chat, retriever = workflow(evidence, planner, draft=draft)
    run = asyncio.run(flow.run(WorkflowRequest(query=query)))
    assert run.result.outcome == "draft_ready"
    assert [p.status for p in run.result.parts] == [
        "candidate",
        "excluded",
        "clarification_required",
    ]
    assert "".join(p.original_text for p in run.result.parts) == query
    assert len(retriever.calls[0][0]) == 1
    assert [q.part_id for q in retriever.calls[0][0]] == [run.result.parts[0].part_id]
    assert all(not p.quotes for p in run.result.parts[1:])
    assert [p["eligible_quote_chunk_ids"] for p in chat.calls[1][1]["parts"]][1:] == [[], []]


@pytest.mark.parametrize(
    "flag,use",
    [
        ("generic_faq_specific_procedure_scope_unverified", "procedure_specific"),
        ("consultation_offer_applicability_unverified", "consultation_eligibility"),
        ("name_only_profile_no_specialty_or_biography_claim", "profile_detail"),
        ("damaged_description_excluded_heading_only", "service_description"),
        ("parallel_category_membership_unresolved_no_category_assertion", "technique_category"),
        ("synthetic_unknown_policy_flag", "general_excerpt"),
    ],
)
def test_context_only_flags_skip_generation_and_cannot_become_candidate_support(flag, use):
    flow, chat, _ = workflow(
        catalog(source(1, source_issue_codes=(flag,))),
        single_plan(intended_use=use),
    )
    run = asyncio.run(flow.run(WorkflowRequest(query="Synthetic scoped question")))
    assert run.result.outcome == "not_found"
    assert run.result.parts[0].reason_code == "context_only"
    assert not run.result.parts[0].quotes
    assert len(chat.calls) == 1
    assert run.stages[-1] == "finalize_safe"
    assert flag in run.evidence.rendered_text


def test_empty_retrieval_skips_generation_but_preserves_question():
    query = "Synthetic unanswered question"
    flow, chat, _ = workflow(catalog(source(1)), single_plan(), chunks=lambda i, q: ())
    run = asyncio.run(flow.run(WorkflowRequest(query=query)))
    assert run.result.outcome == "not_found"
    assert run.result.parts[0].original_text == query
    assert run.result.parts[0].reason_code == "not_found"
    assert len(chat.calls) == 1


def read_plan(body):
    handle = body["source_manifest"]["documents"][0]["handle"]
    return PlannerReply(
        language="en",
        parts=(
            part(
                body["original_query"],
                operation="read_source",
                retrieval_query=None,
                document_handles=(handle,),
            ),
        ),
    )


def test_complete_read_uses_server_manifest_and_quotes_every_admitted_group_without_search():
    first = source(1, "Synthetic first condition: only after assessment.", document="same")
    second = source(2, "Synthetic second condition: outcomes are not guaranteed.", document="same")
    flow, chat, retriever = workflow(catalog(first, second), read_plan)
    run = asyncio.run(flow.run(WorkflowRequest(query="Read this complete synthetic source")))
    assert run.result.outcome == "draft_ready"
    assert run.result.parts[0].admitted_scope_complete is True
    assert {q.chunk_id for q in run.result.parts[0].quotes} == {first.chunk_id, second.chunk_id}
    assert {q.quote for q in run.result.parts[0].quotes} == {
        first.retrieval_text,
        second.retrieval_text,
    }
    assert not retriever.calls
    assert len(chat.calls) == 2
    assert run.usage.logical_embedding_calls == 0


def test_incomplete_scope_due_to_context_budget_remains_unknown_and_skips_generation():
    first = source(1, "Synthetic first qualified statement.", document="same")
    second = source(2, "Synthetic second qualified statement.", document="same")
    flow, chat, retriever = workflow(catalog(first, second), read_plan, max_evidence_chunks=1)
    run = asyncio.run(flow.run(WorkflowRequest(query="Read all synthetic statements")))
    assert run.result.outcome == "not_found"
    assert run.result.parts[0].admitted_scope_complete is False
    assert run.result.parts[0].reason_code == "scope_incomplete"
    assert len(run.evidence.parts[0].missing_scope_occurrence_ids) == 1
    assert len(chat.calls) == 1
    assert not retriever.calls


def test_complete_scope_draft_cannot_silently_quote_only_one_required_group():
    first, second = source(1, document="same"), source(2, "Synthetic second fact.", document="same")

    def incomplete(body):
        return AnswerDraft(
            parts=(
                PartDraft(
                    part_id=body["parts"][0]["part_id"],
                    status="candidate",
                    quotes=(QuoteDraft(chunk_id=first.chunk_id, quote=first.retrieval_text),),
                    reason_code=None,
                ),
            )
        )

    flow, _, _ = workflow(catalog(first, second), read_plan, draft=incomplete)
    run = asyncio.run(flow.run(WorkflowRequest(query="Complete synthetic page")))
    assert run.result.error_code == "incomplete_source_draft"
    assert run.result.outcome == "failed"
    assert not run.result.parts[0].quotes


@pytest.mark.parametrize("fault", ["unknown_handle", "uncovered_text", "invented_reference"])
def test_invalid_plan_fails_before_retrieval_or_generation(fault):
    query = "Synthetic entire question"

    def planner(body):
        changes = {
            "unknown_handle": {"document_handles": ("d9999",)},
            "uncovered_text": {"end": len(query) - 3},
            "invented_reference": {"reference_text": "not in original query"},
        }[fault]
        return PlannerReply(language="en", parts=(part(query, **changes),))

    flow, chat, retriever = workflow(catalog(source(1)), planner)
    run = asyncio.run(flow.run(WorkflowRequest(query=query)))
    assert run.result.error_code == "invalid_plan"
    assert len(chat.calls) == 1
    assert not retriever.calls
    assert run.result.parts[0].original_text == query


@pytest.mark.parametrize("fault", ["short_quote", "wrong_chunk", "duplicate_quote", "wrong_part"])
def test_draft_cannot_drop_qualifiers_forge_sources_or_duplicate_citations(fault):
    item = source(1)

    def bad_draft(body):
        identity = body["parts"][0]["part_id"]
        quote = QuoteDraft(
            chunk_id="unissued-source" if fault == "wrong_chunk" else item.chunk_id,
            quote="Synthetic result may improve gradually;"
            if fault == "short_quote"
            else item.retrieval_text,
        )
        return AnswerDraft(
            parts=(
                PartDraft(
                    part_id="unissued-part" if fault == "wrong_part" else identity,
                    status="candidate",
                    quotes=(quote, quote) if fault == "duplicate_quote" else (quote,),
                    reason_code=None,
                ),
            )
        )

    flow, chat, _ = workflow(catalog(item), single_plan(), draft=bad_draft)
    run = asyncio.run(flow.run(WorkflowRequest(query="Synthetic qualified statement")))
    expected = {"short_quote": "invalid_quotation", "wrong_part": "invalid_draft"}.get(
        fault,
        "invalid_citation",
    )
    assert run.result.error_code == expected
    assert len(chat.calls) == 2
    assert all(not p.quotes for p in run.result.parts)


@pytest.mark.parametrize("fault", ["snapshot", "digest", "unknown_source", "duplicate_source"])
def test_retriever_response_cannot_substitute_snapshot_or_unauthenticated_membership(fault):
    def corrupt(batch):
        if fault in {"snapshot", "digest"}:
            return batch.model_copy(
                update={
                    "snapshot_id" if fault == "snapshot" else "prepared_digest": "foreign-binding",
                }
            )
        ids = (
            ("foreign-source",)
            if fault == "unknown_source"
            else (
                "synthetic-chunk-1",
                "synthetic-chunk-1",
            )
        )
        return batch.model_copy(
            update={"parts": (RetrievedPart(part_id=batch.parts[0].part_id, chunk_ids=ids),)}
        )

    flow, chat, _ = workflow(catalog(source(1)), single_plan(), mutate=corrupt)
    run = asyncio.run(flow.run(WorkflowRequest(query="Synthetic question")))
    assert run.result.error_code == "retrieval_failed"
    assert len(chat.calls) == 1
    assert run.evidence is None


def test_shared_chat_call_limit_blocks_generation_without_retry_or_fallback():
    flow, chat, retriever = workflow(catalog(source(1)), single_plan(), max_llm_calls=1)
    run = asyncio.run(flow.run(WorkflowRequest(query="Synthetic question")))
    assert run.result.error_code == "provider_failed"
    assert run.usage.logical_chat_calls == run.usage.physical_chat_attempts == 1
    assert run.usage.logical_embedding_calls == 1
    assert len(chat.calls) == 2
    assert len(retriever.calls) == 1
    assert chat.calls[0][2] is chat.calls[1][2]
    assert all(not p.quotes for p in run.result.parts)


def test_draft_cannot_cite_hidden_duplicate_occurrence_not_offered_in_rendering():
    first, hidden = source(1), source(2)

    def hidden_citation(body):
        assert body["parts"][0]["eligible_quote_chunk_ids"] == [first.chunk_id]
        return AnswerDraft(
            parts=(
                PartDraft(
                    part_id=body["parts"][0]["part_id"],
                    status="candidate",
                    quotes=(QuoteDraft(chunk_id=hidden.chunk_id, quote=hidden.retrieval_text),),
                    reason_code=None,
                ),
            )
        )

    flow, _, _ = workflow(catalog(first, hidden), single_plan(), draft=hidden_citation)
    run = asyncio.run(flow.run(WorkflowRequest(query="Synthetic duplicate source question")))
    assert run.result.error_code == "invalid_citation"
    assert not run.result.parts[0].quotes
    assert {c.chunk_id for c in run.evidence.groups[0].occurrences} == {
        first.chunk_id,
        hidden.chunk_id,
    }
    assert run.evidence.rendered_text.count(first.retrieval_text) == 1


def test_scoped_sibling_cannot_reuse_another_parts_representative_citation():
    first, second = source(1), source(2)
    query = "First synthetic source. Second synthetic source."
    boundary = len("First synthetic source.")

    def planner(body):
        handles = {d["source_url"]: d["handle"] for d in body["source_manifest"]["documents"]}
        return PlannerReply(
            language="en",
            parts=(
                part(
                    query,
                    end=boundary,
                    document_handles=(handles[first.canonical_url],),
                    retrieval_query=query[:boundary],
                ),
                part(
                    query,
                    start=boundary,
                    document_handles=(handles[second.canonical_url],),
                    retrieval_query=query[boundary:],
                ),
            ),
        )

    def cross_citation(body):
        assert [p["eligible_quote_chunk_ids"] for p in body["parts"]] == [
            [first.chunk_id],
            [second.chunk_id],
        ]
        return AnswerDraft(
            parts=tuple(
                PartDraft(
                    part_id=p["part_id"],
                    status="candidate",
                    quotes=(QuoteDraft(chunk_id=first.chunk_id, quote=first.retrieval_text),),
                    reason_code=None,
                )
                for p in body["parts"]
            )
        )

    flow, _, _ = workflow(
        catalog(first, second),
        planner,
        draft=cross_citation,
        chunks=lambda index, query: ((first, second)[index].chunk_id,),
    )
    run = asyncio.run(flow.run(WorkflowRequest(query=query)))
    assert run.result.error_code == "invalid_citation"
    assert len(run.evidence.groups) == 1
    assert all(not p.quotes for p in run.result.parts)
    assert dict(run.evidence.groups[0].part_occurrences) == {
        run.result.parts[0].part_id: (first.chunk_id,),
        run.result.parts[1].part_id: (second.chunk_id,),
    }


def test_deadline_cancels_slow_generation_and_returns_content_free_failure():
    async def scenario():
        flow, chat, _ = workflow(
            catalog(source(1)),
            single_plan(),
            request_timeout_seconds=0.2,
            provider_timeout_seconds=0.01,
            readiness_timeout_seconds=0.01,
        )
        chat.entered, chat.release = asyncio.Event(), asyncio.Event()
        run = await flow.run(WorkflowRequest(query="Synthetic slow question"))
        assert chat.entered.is_set()
        return run, chat

    run, chat = asyncio.run(scenario())
    assert run.result.error_code == "deadline_exceeded"
    assert len(chat.calls) == 2
    assert not run.result.parts[0].quotes


def test_caller_cancellation_propagates_without_retries_or_safe_answer_fabrication():
    async def scenario():
        flow, chat, _ = workflow(catalog(source(1)), single_plan())
        chat.entered, chat.release = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(flow.run(WorkflowRequest(query="Synthetic cancelled query")))
        await asyncio.wait_for(chat.entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(chat.calls) == 2

    asyncio.run(scenario())


def test_constructing_offline_graph_does_not_enable_public_api_chat():
    flow, chat, _ = workflow(catalog(source(1)), single_plan())
    assert flow is not None and not chat.calls
    config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
    with TestClient(create_app(config)) as client:
        response = client.post("/api/v1/chat", json={"query": "Synthetic public request"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "chat_not_available"
    assert not chat.calls
