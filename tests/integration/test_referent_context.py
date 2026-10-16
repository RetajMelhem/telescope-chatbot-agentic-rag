"""Authored context fixtures and mocked graph wires, not measured Luna understanding."""

import asyncio
import json

import httpx2 as httpx
import pytest
from test_anchored_workflow import part, wire
from test_offline_workflow import FakeRetriever, SyntheticCounter, catalog, source
from test_source_scope_profile import fixtures

from scripts.run_luna_planner_screen import (
    payload_hash,
    planner_payload,
    run_packets,
    screen_settings,
)
from telescope_rag.core.settings import Settings
from telescope_rag.graph.anchoring import AnchoredPlannerReply, resolve_anchored_plan
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import (
    AnswerDraft,
    HistoryTurn,
    PartDraft,
    QuoteDraft,
    WorkflowRequest,
)
from telescope_rag.graph.planning import planner_messages
from telescope_rag.graph.target_context import bind_answer_targets
from telescope_rag.graph.workflow import OfflineRagWorkflow, WorkflowError
from telescope_rag.knowledge.source_authority import DirectoryAuthority
from telescope_rag.prompts import planner_contract_v8, planner_referents_v9
from telescope_rag.providers.openrouter import OpenRouterProviders


@pytest.mark.parametrize(
    "language,query",
    [
        ("en", "Report this source only."),
        ("ar", "انقل هذا المصدر فقط."),
        ("ar", "انقل هالمصدر بس."),
    ],
)
def test_v9_changes_only_system_append_and_version_with_identical_schema_manifest_settings(
    language, query
):
    _, evidence, authority = fixtures()
    bindings = SourceBindings(
        evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
    )
    request = WorkflowRequest(query=query, language=language)
    a, b = (
        planner_messages(request, bindings, max_parts=4, profile=p)
        for p in ("purpose_contract", "referent_context")
    )
    assert a[0].content == planner_contract_v8.PLANNER_SYSTEM
    assert b[0].content == a[0].content + planner_referents_v9.REFERENT_CONTEXT_APPEND
    left, right = (json.loads(m[-1].content) for m in (a, b))
    assert left.pop("prompt_version") == planner_contract_v8.PROMPT_VERSION
    assert right.pop("prompt_version") == planner_referents_v9.PROMPT_VERSION
    assert left == right
    config = screen_settings(profile="purpose_contract", output_cap=4096)
    # Shared wire builder supports v9; the generic live CLI's allowlist is unchanged.
    pa, pb = (
        planner_payload(m, config, profile=p, output_cap=4096)
        for p, m in zip(("purpose_contract", "referent_context"), (a, b), strict=True)
    )
    assert {k: v for k, v in pa.items() if k != "messages"} == {
        k: v for k, v in pb.items() if k != "messages"
    }
    assert "reasoning" not in pb


@pytest.mark.parametrize("enabled,authority_present", [(False, True), (True, False)])
def test_new_prompt_requires_matching_contract_and_authority(enabled, authority_present):
    _, evidence, authority = fixtures()
    bindings = SourceBindings(
        evidence,
        purpose_contract=enabled,
        directory_authority=authority if authority_present else None,
    )
    with pytest.raises(ValueError, match="planner_purpose_contract_configuration_mismatch"):
        planner_messages(
            WorkflowRequest(query="Synthetic."), bindings, max_parts=4, profile="referent_context"
        )


@pytest.mark.parametrize(
    "referent", ["Synthetic Service A", "الخدمة التجريبية أ", "الخدمة التجريبية"]
)
def test_literal_reference_retention_does_not_choose_the_right_reference(
    referent,
):
    first = f"Report {referent} on this page."
    second = " What does it say about how it works?"
    request = WorkflowRequest(query=first + second)
    proposal = AnchoredPlannerReply(
        language="en",
        parts=(part(first), part(second, reference_text=referent, retrieval_query=second)),
    )
    numeric, anchors = resolve_anchored_plan(proposal, request, "synthetic")
    assert numeric.parts[1].retrieval_query == second
    with pytest.raises(ValueError, match="retrieval_query_lost_reference_context"):
        bind_answer_targets(proposal, anchors)
    # A page-only reference is syntactically valid but semantically insufficient
    # for a service-specific target. Preserve this known limit without auto-repair.
    wrong = proposal.model_copy(
        update={
            "parts": (
                proposal.parts[0],
                part(second, reference_text="this page", retrieval_query=second + " this page"),
            )
        }
    )
    _, anchors = resolve_anchored_plan(wrong, request, "synthetic")
    targets = bind_answer_targets(wrong, anchors)
    assert targets[1].reference_text == "this page"
    assert referent not in wrong.parts[1].retrieval_query


@pytest.mark.parametrize(
    "language,first,second,referent",
    [
        (
            "en",
            "Does the page name Synthetic Service A?",
            " What does its description establish?",
            "Synthetic Service A",
        ),
        ("ar", "هل تسمي الصفحة الخدمة التجريبية أ؟", " وماذا يثبت وصفها؟", "الخدمة التجريبية أ"),
        ("ar-JO", "الصفحة بتذكر الخدمة التجريبية أ؟", " ووصفها شو بثبت؟", "الخدمة التجريبية أ"),
    ],
)
@pytest.mark.parametrize(
    "missing_reference,source_language", [(False, "en"), (True, "en"), (False, "ar")]
)
def test_v9_graph_preserves_exact_entity_context_and_heading_only_source_limit(
    language, first, second, referent, missing_reference, source_language
):
    async def run():
        items, evidence, authority = fixtures()
        heading = source(
            4,
            referent,
            document="service",
            source_issue_codes=("damaged_description_excluded_heading_only",),
        )
        evidence = catalog(*items, heading)
        authority = authority.model_copy(update={"prepared_digest": evidence.prepared_digest})
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        retriever = FakeRetriever(lambda i, q: (heading.chunk_id,))
        seen = []
        flow = None

        def handler(request):
            payload = json.loads(request.read())
            body = json.loads(payload["messages"][-1]["content"])
            seen.append(body)
            assert body["prompt_version"] == planner_referents_v9.PROMPT_VERSION
            if len(seen) == 1:
                assert payload["messages"][0]["content"] == planner_referents_v9.PLANNER_SYSTEM
                assert payload["response_format"]["json_schema"]["name"] == "AnchoredPlannerReply"
                handle = next(h for h, i in flow._bindings.documents.items() if i == "service")
                value = AnchoredPlannerReply(
                    language=language,
                    parts=(
                        part(
                            first,
                            intended_use="service_name",
                            document_handles=(handle,),
                            source_language=source_language,
                        ),
                        part(
                            second,
                            intended_use="service_description",
                            document_handles=(handle,),
                            source_language=source_language,
                            reference_text=referent,
                            retrieval_query=second
                            if missing_reference
                            else second + " " + referent,
                        ),
                    ),
                )
            else:
                # V9 reuses v8 draft instructions/definitions and per-target context.
                assert body["parts"][1]["reference_context"]["literal_text"] == referent
                assert body["parts"][1]["answer_target"] == second
                assert body["parts"][1]["eligible_quote_chunk_ids"] == []
                value = AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=body["parts"][0]["part_id"],
                            status="candidate",
                            quotes=(
                                QuoteDraft(chunk_id=heading.chunk_id, quote=heading.retrieval_text),
                            ),
                            reason_code=None,
                        ),
                        PartDraft(
                            part_id=body["parts"][1]["part_id"],
                            status="unknown",
                            quotes=(),
                            reason_code="context_only",
                        ),
                    )
                )
            return wire(value)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            flow = OfflineRagWorkflow(
                settings=config,
                chat=p.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="referent_context",
                directory_authority=authority,
            )
            result = await flow.run(
                WorkflowRequest(
                    query=first + second, language="ar" if language == "ar-JO" else language
                )
            )
        if missing_reference:
            assert result.result.error_code == "retrieval_query_lost_reference_context"
            assert len(seen) == 1 and not retriever.calls
        elif source_language == "ar":
            assert result.result.error_code == "planner_source_filters_have_empty_intersection"
            assert len(seen) == 1 and not retriever.calls
        else:
            assert result.result.outcome == "draft_ready" and len(seen) == 2
            query = retriever.calls[0][0][1]
            assert query.text == second + " " + referent
            assert query.scope.document_ids == ("service",) and query.scope.language == "en"
            assert result.answer_targets[1].reference_text == referent
            assert result.result.parts[1].status == "unknown"
            assert result.result.parts[1].reason_code == "context_only"
            assert result.result.parts[0].quotes[0].source_url == heading.canonical_url
        assert not result.result.semantic_grounding_verified
        assert not result.result.luna_compatibility_verified

    asyncio.run(run())


@pytest.mark.parametrize(
    "language,query",
    [
        ("en", "What does her entry publish?"),
        ("ar", "ماذا ينشر مدخلها؟"),
        ("ar-JO", "شو المكتوب بمدخلها؟"),
    ],
)
def test_selected_literal_history_identifies_owner_without_becoming_factual_evidence(
    language, query
):
    async def run():
        item = source(
            1, "Synthetic published detail.", document="main", doctor_id="a", doctor_name="Person A"
        ).model_copy(update={"block_type": "doctor"})
        evidence = catalog(item)
        authority = DirectoryAuthority(
            prepared_digest=evidence.prepared_digest,
            admission_policy_hash="synthetic-policy",
            primary_directory_document_ids=("main",),
        )
        bindings = SourceBindings(
            evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
        )
        request = WorkflowRequest(
            query=query, history=(HistoryTurn(role="user", content="By her I mean Person A."),)
        )
        proposal = AnchoredPlannerReply(
            language=language,
            parts=(
                part(
                    query,
                    reference_text="Person A",
                    history_indices=(0,),
                    retrieval_query=query + " Person A",
                    document_handles=("d0001",),
                    intended_use="profile_detail",
                ),
            ),
        )
        numeric, anchors = resolve_anchored_plan(proposal, request, "synthetic")
        targets = bind_answer_targets(proposal, anchors)
        plan = bindings.validate(numeric, request, "synthetic", max_parts=4)
        assert targets[0].reference_text == "Person A" and targets[0].history_indices == (0,)
        assert plan.retrieval_queries[0].text == query + " Person A"
        assert plan.semantic_interpretation_verified is False

    asyncio.run(run())


@pytest.mark.parametrize("profile", ["referent_context"])
def test_v9_workflow_remains_opt_in_and_requires_explicit_authority(profile):
    _, evidence, _ = fixtures()
    with pytest.raises(WorkflowError, match="offline_workflow_configuration_invalid"):
        OfflineRagWorkflow(
            settings=Settings(_env_file=None, app_env="test"),
            chat=None,
            retriever=None,
            catalog=evidence,
            counter=SyntheticCounter(),
            token_basis="synthetic_test",
            planner_profile=profile,
        )


@pytest.mark.parametrize(
    "language,query",
    [
        ("en", "Which entry did I mean?"),
        ("ar", "أي ملف قصدت؟"),
        ("ar-JO", "أي ملف كنت قاصد؟"),
    ],
)
def test_authored_ambiguous_history_plan_stops_without_retrieval_or_owner_guess(language, query):
    async def run():
        _, evidence, authority = fixtures()
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        seen = []

        def handler(request):
            seen.append(json.loads(request.read()))
            return wire(
                AnchoredPlannerReply(
                    language=language,
                    parts=(
                        part(
                            query,
                            state="clarification_required",
                            retrieval_query=None,
                            history_indices=(0,),
                            reason="Synthetic history identifies two entries; clarify which one.",
                        ),
                    ),
                )
            )

        class ForbiddenRetriever:
            async def retrieve(self, *args, **kwargs):
                raise AssertionError("Ambiguous fixture must not retrieve")

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            result = await OfflineRagWorkflow(
                settings=config,
                chat=p.chat,
                retriever=ForbiddenRetriever(),
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="referent_context",
                directory_authority=authority,
            ).run(
                WorkflowRequest(
                    query=query,
                    history=(HistoryTurn(role="user", content="I meant Person A and Person B."),),
                )
            )
        assert result.result.outcome == "clarification_required" and len(seen) == 1
        assert not result.plan.retrieval_queries and "retrieve_evidence" not in result.stages
        assert result.plan.assembly_request.parts[0].scope.owner_id is None
        assert not result.result.semantic_grounding_verified

    asyncio.run(run())


def test_shared_screen_uses_same_v9_anchored_wire_and_receipts_as_graph(tmp_path):
    async def run():
        _, evidence, authority = fixtures()
        bindings = SourceBindings(
            evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
        )
        request = WorkflowRequest(query="Synthetic self-contained question.")
        config = screen_settings(profile="referent_context", output_cap=4096)
        messages = planner_messages(request, bindings, max_parts=4, profile="referent_context")
        payload = planner_payload(messages, config, profile="referent_context", output_cap=4096)
        packet = {
            "case_id": "synthetic-en",
            "request": request.model_dump(mode="json"),
            "payload": payload,
            "payload_sha256": payload_hash(payload),
        }

        def handler(received):
            assert json.loads(received.read()) == payload
            return wire(AnchoredPlannerReply(language="en", parts=(part(request.query),)))

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            summary = await run_packets(
                [packet],
                bindings,
                config,
                p.chat,
                tmp_path,
                profile="referent_context",
                case_ids=("synthetic-en",),
                inventory=("synthetic-en",),
                output_cap=4096,
            )
        assert summary["schema_valid"] == summary["literal_bindings_valid"] == 1
        row = json.loads((tmp_path / "synthetic-en.json").read_bytes())
        assert row["answer_targets"] and row["request_anchors"] and row["physical_attempts"] == 1
        assert row["semantic_review"] == "pending"

    asyncio.run(run())
