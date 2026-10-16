"""Authored multilingual plans and mocked HTTP; no measured Luna understanding."""

import asyncio
import json

import httpx2 as httpx
import pytest
from test_offline_workflow import FakeRetriever, SyntheticCounter, catalog, charge, source

from telescope_rag.core.settings import Settings
from telescope_rag.graph.anchoring import AnchoredPlannerPart, AnchoredPlannerReply
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft, WorkflowRequest
from telescope_rag.graph.workflow import OfflineRagWorkflow
from telescope_rag.providers.contracts import StructuredResult
from telescope_rag.providers.openrouter import OpenRouterProviders


def part(text, **changes):
    return AnchoredPlannerPart(
        **(
            dict(
                original_text=text,
                constraint_quotes=(),
                state="public",
                operation="search",
                intended_use="general_excerpt",
                retrieval_query=text,
                document_handles=(),
                owner_handle=None,
                block_types=(),
                source_language=None,
                reference_text=None,
                history_indices=(),
                reason=None,
            )
            | changes
        )
    )


def wire(value, *, missing_usage=False):
    return httpx.Response(
        200,
        json={
            "model": "openai/gpt-6-luna",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": value.model_dump_json()},
                }
            ],
            "usage": None if missing_usage else {"prompt_tokens": 20, "completion_tokens": 12},
        },
    )


@pytest.mark.parametrize(
    "language,query,constraint,text",
    [
        (
            "en",
            "State the public label only; do not message anyone.",
            "do not message anyone",
            "Synthetic source label; no action performed.",
        ),
        (
            "ar",
            "اذكر النص المنشور فقط؛ لا تراسل أحداً.",
            "لا تراسل أحداً",
            "نص مصدر تجريبي؛ دون تنفيذ أي إجراء.",
        ),
        (
            "ar-JO",
            "بس أعطيني النص المعلن؛ ما تبعت لحدا.",
            "ما تبعت لحدا",
            "نص تجريبي معلن؛ ما فيه إجراء.",
        ),
    ],
)
@pytest.mark.parametrize("missing_usage", [False, True])
def test_actual_graph_and_adapter_keep_unique_original_text_constraints_and_citations(
    language, query, constraint, text, missing_usage
):
    async def run():
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        item = source(1, text).model_copy(update={"language": "en" if language == "en" else "ar"})
        evidence = catalog(item)
        retriever = FakeRetriever(lambda i, q: (item.chunk_id,))
        seen = []

        def handle(request):
            payload = json.loads(request.read())
            body = json.loads(payload["messages"][-1]["content"])
            seen.append((payload, body))
            assert body["original_query"] == query
            assert "reasoning" not in payload
            if len(seen) == 1:
                assert payload["response_format"]["json_schema"]["name"] == "AnchoredPlannerReply"
                assert body["source_manifest"]["documents"][0]["available_block_types"] == [
                    "section"
                ]
                value = AnchoredPlannerReply(
                    language=language, parts=(part(query, constraint_quotes=(constraint,)),)
                )
            else:
                supplied = body["parts"][0]
                assert supplied["original_text"] == query and supplied["constraint_quotes"] == [
                    constraint
                ]
                assert (
                    supplied["state"] == "public" and supplied["intended_use"] == "general_excerpt"
                )
                value = AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=supplied["part_id"],
                            status="candidate",
                            quotes=(QuoteDraft(chunk_id=item.chunk_id, quote=text),),
                            reason_code=None,
                        ),
                    )
                )
            return wire(value, missing_usage=missing_usage)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handle)) as providers:
            flow = OfflineRagWorkflow(
                settings=config,
                chat=providers.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="literal_anchors",
            )
            result = await flow.run(WorkflowRequest(query=query))
        assert result.result.outcome == "draft_ready" and len(seen) == 2
        assert result.result.parts[0].original_text == query
        assert result.result.parts[0].quotes[0].source_url == item.canonical_url
        assert result.result.parts[0].quotes[0].quote == text
        assert result.request_anchors[0].part_id == result.result.parts[0].part_id
        assert result.request_anchors[0].original.quote == query
        assert result.request_anchors[0].constraints[0].quote == constraint
        assert retriever.calls[0][0][0].text == query
        assert result.usage.charged_chat_input == (None if missing_usage else 40)
        assert result.usage.charged_embedding_input == 10
        assert result.result.offline_only and not result.plan.semantic_interpretation_verified
        assert (
            not result.result.semantic_grounding_verified
            and not result.result.luna_compatibility_verified
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "query,anchor,retrieval_query,expected",
    [
        ("repeat / repeat", "repeat", "repeat", "ambiguous_original_text_anchor"),
        ("Original text.", "changed text", "changed text", "original_text_anchor_not_found"),
        (
            "Keep all; do not act.",
            "Keep all; do not act.",
            "Keep all",
            "retrieval_query_lost_original_part",
        ),
        ("First. Second.", "First.", "First.", "invalid_plan"),
    ],
)
def test_invalid_anchoring_stops_before_retrieval_without_guessing_or_repair(
    query, anchor, retrieval_query, expected
):
    async def run():
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        evidence = catalog(source(1))
        retriever = FakeRetriever(lambda i, q: ())
        seen = []

        def handle(request):
            seen.append(request)
            return wire(
                AnchoredPlannerReply(
                    language="en", parts=(part(anchor, retrieval_query=retrieval_query),)
                )
            )

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handle)) as p:
            flow = OfflineRagWorkflow(
                settings=config,
                chat=p.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="literal_anchors",
            )
            result = await flow.run(WorkflowRequest(query=query))
        assert len(seen) == 1 and not retriever.calls and not result.request_anchors
        assert result.result.outcome == "failed" and result.result.error_code == expected
        assert result.result.parts[0].original_text == query
        assert not result.result.parts[0].quotes

    asyncio.run(run())


@pytest.mark.parametrize(
    "language,fragments",
    [
        (
            "en",
            (
                "Can the published offer apply to my request?",
                " State the published fee notice with its qualification.",
                " Choose a treatment for my personal condition.",
            ),
        ),
        (
            "ar",
            (
                "هل يشمل العرض المنشور طلبي؟",
                " اذكر إشعار الرسوم المنشور مع شرطه.",
                " اختر لي علاجاً لحالتي الشخصية.",
            ),
        ),
        (
            "ar-JO",
            (
                "العرض المعلن بشمل طلبي؟",
                " احكيلي إشعار الرسوم المعلن مع شرطه.",
                " اختارلي علاج لحالتي أنا.",
            ),
        ),
    ],
)
def test_authored_distinct_purposes_keep_context_only_public_and_excluded_siblings_separate(
    language, fragments
):
    async def run():
        query = "".join(fragments)
        item = source(
            1,
            "Synthetic separate fee notice; the qualification remains.",
            source_issue_codes=("consultation_fee_offer_reconciliation_unverified",),
        )
        evidence = catalog(item)
        retriever = FakeRetriever(lambda i, q: (item.chunk_id,))
        config = Settings(_env_file=None, app_env="test")

        class AuthoredChat:
            def __init__(self):
                self.calls = []

            async def complete(self, messages, output_model, *, max_output_tokens, budget):
                self.calls.append((json.loads(messages[-1].content), budget))
                receipt = charge(budget, "chat", max_output_tokens)
                if output_model is AnchoredPlannerReply:
                    value = AnchoredPlannerReply(
                        language=language,
                        parts=(
                            part(fragments[0], intended_use="consultation_eligibility"),
                            part(fragments[1], intended_use="general_excerpt"),
                            part(
                                fragments[2],
                                state="excluded",
                                retrieval_query=None,
                                intended_use="procedure_specific",
                                reason="Synthetic personal clinical selection request is excluded.",
                            ),
                        ),
                    )
                else:
                    parts = self.calls[-1][0]["parts"]
                    assert [p["original_text"] for p in parts] == list(fragments)
                    assert [p["intended_use"] for p in parts] == [
                        "consultation_eligibility",
                        "general_excerpt",
                        "procedure_specific",
                    ]
                    value = AnswerDraft(
                        parts=(
                            PartDraft(
                                part_id=parts[0]["part_id"],
                                status="unknown",
                                quotes=(),
                                reason_code="context_only",
                            ),
                            PartDraft(
                                part_id=parts[1]["part_id"],
                                status="candidate",
                                quotes=(
                                    QuoteDraft(chunk_id=item.chunk_id, quote=item.retrieval_text),
                                ),
                                reason_code=None,
                            ),
                            PartDraft(
                                part_id=parts[2]["part_id"],
                                status="excluded",
                                quotes=(),
                                reason_code="scope_excluded",
                            ),
                        )
                    )
                return StructuredResult(value, (receipt,))

        chat = AuthoredChat()
        flow = OfflineRagWorkflow(
            settings=config,
            chat=chat,
            retriever=retriever,
            catalog=evidence,
            counter=SyntheticCounter(),
            token_basis="synthetic_test",
            planner_profile="literal_anchors",
        )
        result = await flow.run(WorkflowRequest(query=query))
        assert [p.status for p in result.result.parts] == ["unknown", "candidate", "excluded"]
        assert [p.original_text for p in result.result.parts] == list(fragments)
        assert result.result.parts[0].reason_code == "context_only"
        assert len(result.request_anchors) == 3
        assert len(retriever.calls) == 1 and len(retriever.calls[0][0]) == 2
        assert all(budget is retriever.calls[0][1] for _, budget in chat.calls)
        assert not result.plan.semantic_interpretation_verified

    asyncio.run(run())


@pytest.mark.parametrize("swap_citations", [False, True])
def test_same_field_doctors_retain_distinct_owners_and_sibling_citation_boundaries(swap_citations):
    async def run():
        text = "Synthetic shared field label."
        items = (
            source(1, text, doctor_id="doctor-a", doctor_name="Synthetic Doctor A"),
            source(2, text, doctor_id="doctor-b", doctor_name="Synthetic Doctor B"),
        )
        fragments = (
            "Read Synthetic Doctor A's published role.",
            " Read Synthetic Doctor B's published role.",
        )
        query = "".join(fragments)
        evidence = catalog(*items)
        retriever = FakeRetriever(lambda i, q: tuple(s.chunk_id for s in items))
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")

        def handle(request):
            payload = json.loads(request.read())
            body = json.loads(payload["messages"][-1]["content"])
            if payload["response_format"]["json_schema"]["name"] == "AnchoredPlannerReply":
                owners = {
                    tuple(o["literal_source_labels"]): o["handle"]
                    for o in body["source_manifest"]["owners"]
                }
                value = AnchoredPlannerReply(
                    language="en",
                    parts=tuple(
                        part(
                            fragment,
                            intended_use="doctor_role",
                            owner_handle=owners[(item.doctor_name,)],
                        )
                        for fragment, item in zip(fragments, items, strict=True)
                    ),
                )
            else:
                value = AnswerDraft(
                    parts=tuple(
                        PartDraft(
                            part_id=provided["part_id"],
                            status="candidate",
                            quotes=(
                                QuoteDraft(
                                    chunk_id=items[1 - i if swap_citations else i].chunk_id,
                                    quote=text,
                                ),
                            ),
                            reason_code=None,
                        )
                        for i, provided in enumerate(body["parts"])
                    )
                )
            return wire(value)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handle)) as p:
            flow = OfflineRagWorkflow(
                settings=config,
                chat=p.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="literal_anchors",
            )
            result = await flow.run(WorkflowRequest(query=query))
        assert len(result.evidence.groups) == 2
        assert len(result.request_anchors) == 2
        if swap_citations:
            assert (
                result.result.outcome == "failed" and result.result.error_code == "invalid_citation"
            )
            assert not any(p.quotes for p in result.result.parts)
        else:
            assert result.result.outcome == "draft_ready"
            assert [p.quotes[0].literal_owner_id for p in result.result.parts] == [
                "doctor-a",
                "doctor-b",
            ]
            assert [p.original_text for p in result.result.parts] == list(fragments)
            assert [p.quotes[0].source_url for p in result.result.parts] == [
                s.canonical_url for s in items
            ]

    asyncio.run(run())


def test_concurrent_anchor_receipts_and_reported_budgets_stay_request_owned():
    async def run():
        item = source(1, "Synthetic concurrent source.")
        evidence = catalog(item)
        retriever = FakeRetriever(lambda i, q: (item.chunk_id,))
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        queries = (
            "Synthetic request A; keep its constraint.",
            "Synthetic request B; keep its constraint.",
        )

        async def handle(request):
            await asyncio.sleep(0)
            payload = json.loads(request.read())
            body = json.loads(payload["messages"][-1]["content"])
            if payload["response_format"]["json_schema"]["name"] == "AnchoredPlannerReply":
                value = AnchoredPlannerReply(
                    language="en",
                    parts=(
                        part(body["original_query"], constraint_quotes=("keep its constraint",)),
                    ),
                )
            else:
                value = AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=body["parts"][0]["part_id"],
                            status="candidate",
                            quotes=(QuoteDraft(chunk_id=item.chunk_id, quote=item.retrieval_text),),
                            reason_code=None,
                        ),
                    )
                )
            return wire(value)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handle)) as p:
            flow = OfflineRagWorkflow(
                settings=config,
                chat=p.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="literal_anchors",
            )
            results = await asyncio.gather(*(flow.run(WorkflowRequest(query=q)) for q in queries))
        assert len({r.request_anchors[0].part_id for r in results}) == 2
        for result, query in zip(results, queries, strict=True):
            assert result.result.outcome == "draft_ready"
            assert (
                result.request_anchors[0].original.quote
                == result.result.parts[0].original_text
                == query
            )
            assert (
                result.usage.charged_chat_input == 40 and result.usage.physical_chat_attempts == 2
            )
            assert len(result.usage.receipts) == 3
        assert retriever.calls[0][1] is not retriever.calls[1][1]

    asyncio.run(run())


@pytest.mark.parametrize("missing_usage", [False, True])
def test_explicit_graph_output_capacity_supports_reasoning_without_disabling_it(missing_usage):
    async def run():
        item = source(1, "Synthetic source for declared capacity.")
        evidence = catalog(item)
        retriever = FakeRetriever(lambda i, q: (item.chunk_id,))
        config = Settings(
            _env_file=None,
            app_env="test",
            openrouter_api_key="synthetic-only",
            max_total_output_tokens=6144,
            request_timeout_seconds=60,
            provider_timeout_seconds=30,
        )
        query = "Keep this original question and its qualifier."
        caps = []

        def handle(request):
            payload = json.loads(request.read())
            body = json.loads(payload["messages"][-1]["content"])
            caps.append(payload["max_completion_tokens"])
            assert "reasoning" not in payload
            if len(caps) == 1:
                value = AnchoredPlannerReply(language="en", parts=(part(query),))
            else:
                value = AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=body["parts"][0]["part_id"],
                            status="candidate",
                            quotes=(QuoteDraft(chunk_id=item.chunk_id, quote=item.retrieval_text),),
                            reason_code=None,
                        ),
                    )
                )
            data = wire(value, missing_usage=missing_usage).json()
            if not missing_usage and len(caps) == 1:
                data["usage"] = {
                    "prompt_tokens": 20,
                    "completion_tokens": 1500,
                    "completion_tokens_details": {"reasoning_tokens": 1000},
                }
            return httpx.Response(200, json=data)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handle)) as p:
            flow = OfflineRagWorkflow(
                settings=config,
                chat=p.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="literal_anchors",
                planner_output_tokens=4096,
                draft_output_tokens=2048,
            )
            result = await flow.run(WorkflowRequest(query=query))
        assert caps == [4096, 2048] and result.result.outcome == "draft_ready"
        assert result.usage.charged_output == (6144 if missing_usage else 1512)
        assert result.usage.charged_chat_input == (None if missing_usage else 40)
        assert result.usage.physical_chat_attempts == 2 and len(result.request_anchors) == 1

    asyncio.run(run())
