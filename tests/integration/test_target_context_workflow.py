"""Actual graph/adapter with authored multilingual mock plans; no semantic score."""

import asyncio
import json

import httpx2 as httpx
import pytest
from test_anchored_workflow import part, wire
from test_offline_workflow import FakeRetriever, SyntheticCounter, catalog, source

from telescope_rag.core.settings import Settings
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft, WorkflowRequest
from telescope_rag.graph.workflow import OfflineRagWorkflow
from telescope_rag.providers.openrouter import OpenRouterProviders

CASES = (
    (
        "en",
        "The named page advertises an offer: am I eligible?",
        " Report its fee notice, keeping the before-starting qualification.",
        " Decide my medical suitability.",
        "The named page",
    ),
    (
        "ar",
        "تعلن الصفحة المذكورة عن عرض: هل يشملني؟",
        " انقل تنبيه الرسوم مع شرط توضيح التفاصيل قبل البدء.",
        " قرر ملاءمتي الطبية.",
        "الصفحة المذكورة",
    ),
    (
        "ar-JO",
        "الصفحة اللي حكينا عنها معلنة عرض: بيشملني؟",
        " احكيلي تنبيه الكشفية ومعه شرط التفاصيل قبل ما نبلش.",
        " احسملي إذا الإجراء بناسبني طبياً.",
        "الصفحة اللي حكينا عنها",
    ),
)


@pytest.mark.parametrize("language,eligibility,fee,clinical,reference", CASES)
@pytest.mark.parametrize("missing_usage", [False, True])
def test_targets_context_source_policy_and_citations_stay_part_owned(
    language, eligibility, fee, clinical, reference, missing_usage
):
    async def run():
        item = source(
            1,
            "Synthetic separate fee; details explained before starting.",
            source_issue_codes=("consultation_fee_offer_reconciliation_unverified",),
        )
        evidence = catalog(item)
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        retriever = FakeRetriever(lambda i, q: (item.chunk_id,))
        seen = []

        def handler(request):
            payload = json.loads(request.read())
            body = json.loads(payload["messages"][-1]["content"])
            seen.append(body)
            assert "reasoning" not in payload
            if len(seen) == 1:
                assert body["prompt_version"] == "offline-rag-planner-answer-targets-v5"
                reply = AnchoredPlannerReply(
                    language=language,
                    parts=(
                        part(eligibility, intended_use="consultation_eligibility"),
                        part(
                            fee,
                            intended_use="service_description",
                            reference_text=reference,
                            retrieval_query=reference + fee,
                        ),
                        part(
                            clinical,
                            state="excluded",
                            retrieval_query=None,
                            reason="Synthetic individual medical decision is excluded.",
                        ),
                    ),
                )
            else:
                parts = body["parts"]
                assert [p["answer_target"] for p in parts] == [eligibility, fee, clinical]
                assert parts[1]["reference_context"] == {
                    "literal_text": reference,
                    "history_indices": [],
                    "role": "interpretation_only",
                }
                assert eligibility not in parts[1]["answer_target"]
                assert parts[0]["eligible_quote_chunk_ids"] == []
                assert parts[1]["eligible_quote_chunk_ids"] == [item.chunk_id]
                assert "Address only" in payload["messages"][0]["content"]
                reply = AnswerDraft(
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
                            quotes=(QuoteDraft(chunk_id=item.chunk_id, quote=item.retrieval_text),),
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
            return wire(reply, missing_usage=missing_usage)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            flow = OfflineRagWorkflow(
                settings=config,
                chat=p.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="answer_targets",
            )
            run = await flow.run(WorkflowRequest(query=eligibility + fee + clinical))
        assert [p.status for p in run.result.parts] == ["unknown", "candidate", "excluded"]
        assert len(run.answer_targets) == len(run.request_anchors) == 3
        assert run.answer_targets[1].target.quote == fee
        assert run.answer_targets[1].reference_text == reference
        assert run.result.parts[1].quotes[0].quote == item.retrieval_text
        assert run.result.parts[1].quotes[0].source_url == item.canonical_url
        assert run.usage.physical_chat_attempts == 2
        assert run.usage.charged_chat_input == (None if missing_usage else 40)
        assert not run.plan.semantic_interpretation_verified
        assert not run.result.semantic_grounding_verified
        assert retriever.calls[0][0][1].text == reference + fee

    asyncio.run(run())


def test_missing_reference_stops_before_retrieval_or_draft():
    async def run():
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        retriever = FakeRetriever(lambda i, q: ())
        query = "Keep this source context. Report its posted role."

        def handler(request):
            return wire(
                AnchoredPlannerReply(
                    language="en",
                    parts=(
                        part("Keep this source context."),
                        part(" Report its posted role.", reference_text="this source context"),
                    ),
                )
            )

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            result = await OfflineRagWorkflow(
                settings=config,
                chat=p.chat,
                retriever=retriever,
                catalog=catalog(source(1)),
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="answer_targets",
            ).run(WorkflowRequest(query=query))
        assert result.result.error_code == "retrieval_query_lost_reference_context"
        assert result.usage.physical_chat_attempts == 1 and retriever.calls == []
        assert result.answer_targets == result.request_anchors == ()

    asyncio.run(run())
