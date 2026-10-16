"""Authored multilingual graph fixtures; no measured model interpretation or live I/O."""

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
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft, WorkflowRequest
from telescope_rag.graph.planning import planner_messages
from telescope_rag.graph.target_context import bind_answer_targets
from telescope_rag.graph.workflow import OfflineRagWorkflow
from telescope_rag.knowledge.source_authority import DirectoryAuthority
from telescope_rag.prompts import (
    planner_contract_v8,
    planner_dependencies_v10,
    planner_referents_v9,
)
from telescope_rag.providers.openrouter import OpenRouterProviders


@pytest.mark.parametrize(
    "language,query", [("en", "Report it."), ("ar", "انقل النص."), ("ar", "هات النص.")]
)
def test_opt_in_replaces_only_dependency_instruction_and_version(language, query):
    _, evidence, authority = fixtures()
    bindings = SourceBindings(
        evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
    )
    request = WorkflowRequest(query=query, language=language)
    old, new = (
        planner_messages(request, bindings, max_parts=4, profile=p)
        for p in ("referent_context", "dependency_context")
    )
    assert old[0].content == planner_referents_v9.PLANNER_SYSTEM
    assert (
        new[0].content
        == planner_contract_v8.PLANNER_SYSTEM + planner_dependencies_v10.DEPENDENCY_CONTEXT_APPEND
    )
    left, right = (json.loads(m[-1].content) for m in (old, new))
    assert left.pop("prompt_version") == planner_referents_v9.PROMPT_VERSION
    assert right.pop("prompt_version") == planner_dependencies_v10.PROMPT_VERSION
    assert left == right
    config = screen_settings(profile="referent_context", output_cap=4096)
    a, b = (
        planner_payload(m, config, profile=p, output_cap=4096)
        for m, p in zip((old, new), ("referent_context", "dependency_context"), strict=True)
    )
    assert {k: v for k, v in a.items() if k != "messages"} == {
        k: v for k, v in b.items() if k != "messages"
    }
    assert "reasoning" not in b


@pytest.mark.parametrize("enabled,authority_present", [(False, True), (True, False)])
def test_contract_and_authority_remain_required(enabled, authority_present):
    _, evidence, authority = fixtures()
    bindings = SourceBindings(
        evidence,
        purpose_contract=enabled,
        directory_authority=authority if authority_present else None,
    )
    with pytest.raises(ValueError, match="planner_purpose_contract_configuration_mismatch"):
        planner_messages(
            WorkflowRequest(query="Synthetic."), bindings, max_parts=4, profile="dependency_context"
        )


TEXTS = [
    (
        "en",
        "Use the English main entry only for Synthetic Person A; "
        "exclude Synthetic Person B. Which role?",
        " And training?",
        " Instead use the English standalone entry for training.",
    ),
    (
        "ar",
        "استخدم المدخل الرئيسي الإنجليزي فقط للشخص التجريبي أ؛ استبعد الشخص التجريبي ب. ما دوره؟",
        " وما مؤهلاته؟",
        " أما المؤهلات فاستخدم لها المدخل الإنجليزي المستقل.",
    ),
    (
        "ar-JO",
        "من المدخل الرئيسي الإنجليزي بس للشخص التجريبي أ؛ لا تحكي عن الشخص التجريبي ب. شو دوره؟",
        " وشو مؤهلاته؟",
        " بس للمؤهلات استخدم المدخل الإنجليزي اللي لحاله.",
    ),
]


def owned_fixture():
    main = source(
        1,
        "Synthetic Person A; explicit role and training.",
        document="main",
        doctor_id="a",
        doctor_name="Synthetic Person A",
    ).model_copy(update={"block_type": "doctor"})
    other = source(
        2,
        "Synthetic Person B; different role and training.",
        document="main",
        doctor_id="b",
        doctor_name="Synthetic Person B",
    ).model_copy(update={"block_type": "doctor"})
    profile = source(
        3,
        "Synthetic Person A",
        document="profile",
        doctor_id="a",
        doctor_name="Synthetic Person A",
        source_issue_codes=("name_only_profile_no_specialty_or_biography_claim",),
    ).model_copy(update={"block_type": "doctor"})
    evidence = catalog(main, other, profile)
    authority = DirectoryAuthority(
        prepared_digest=evidence.prepared_digest,
        admission_policy_hash="synthetic-policy",
        primary_directory_document_ids=("main",),
    )
    return main, other, profile, evidence, authority


@pytest.mark.parametrize(
    "first,second",
    [
        (
            "Use the main directory for Person A then Person B. Which roles?",
            " And training for each?",
        ),
        ("استخدم الدليل الرئيسي للشخص أ ثم الشخص ب. ما دورهما؟", " وما مؤهلات كل منهما؟"),
        ("من الدليل الرئيسي للشخص أ وبعدين الشخص ب. شو أدوارهم؟", " ومؤهلات كل واحد؟"),
    ],
)
def test_authored_ordered_group_keeps_distinct_owners_without_single_owner_guess(first, second):
    main, other, profile, evidence, authority = owned_fixture()
    bindings = SourceBindings(
        evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
    )
    handle = next(h for h, i in bindings.documents.items() if i == "main")
    request = WorkflowRequest(query=first + second)
    proposal = AnchoredPlannerReply(
        language="en",
        parts=(
            part(first, document_handles=(handle,), intended_use="doctor_role"),
            part(
                second,
                document_handles=(handle,),
                intended_use="profile_detail",
                reference_text=first,
                retrieval_query=second + " " + first,
            ),
        ),
    )
    numeric, anchors = resolve_anchored_plan(proposal, request, "synthetic-group")
    targets = bind_answer_targets(proposal, anchors)
    plan = bindings.validate(numeric, request, "synthetic-group", max_parts=4)
    assert targets[1].reference_text == first
    scope = plan.assembly_request.parts[1].scope
    assert scope.owner_id is None
    members = evidence.scope_members(scope)
    assert set(members) == {main.chunk_id, other.chunk_id}
    assert profile.chunk_id not in members
    assert {evidence.chunks[i].doctor_id for i in members} == {"a", "b"}
    assert plan.retrieval_queries[1].text == second + " " + first


@pytest.mark.parametrize("language,first,follow,override", TEXTS)
@pytest.mark.parametrize("mode", ["inherit", "override", "missing_reference", "empty_language"])
def test_authored_source_context_and_override_survive_full_graph(
    language, first, follow, override, mode
):
    async def run():
        main, other, profile, evidence, authority = owned_fixture()
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        second = override if mode == "override" else follow
        retriever = FakeRetriever(lambda i, q: (main.chunk_id, other.chunk_id, profile.chunk_id))
        seen = []
        flow = None

        def handler(request):
            payload = json.loads(request.read())
            body = json.loads(payload["messages"][-1]["content"])
            seen.append(body)
            assert body["prompt_version"] == planner_dependencies_v10.PROMPT_VERSION
            if len(seen) == 1:
                assert payload["messages"][0]["content"] == planner_dependencies_v10.PLANNER_SYSTEM
                handle = {i: h for h, i in flow._bindings.documents.items()}
                owner = next(h for h, i in flow._bindings.owners.items() if i == ("literal", "a"))
                value = AnchoredPlannerReply(
                    language=language,
                    parts=(
                        part(
                            first,
                            intended_use="doctor_role",
                            document_handles=(handle["main"],),
                            owner_handle=owner,
                            source_language="en",
                        ),
                        part(
                            second,
                            intended_use="profile_detail",
                            document_handles=(handle["profile" if mode == "override" else "main"],),
                            owner_handle=owner,
                            source_language="ar" if mode == "empty_language" else "en",
                            reference_text=first,
                            retrieval_query=second
                            if mode == "missing_reference"
                            else second + " " + first,
                        ),
                    ),
                )
            else:
                assert body["original_query"] == first + second
                target = body["parts"][1]
                assert target["answer_target"] == second
                assert target["reference_context"]["literal_text"] == first
                assert target["reference_context"]["role"] == "interpretation_only"
                assert body["source_manifest"]["purpose_contract"]
                if mode == "override":
                    assert target["eligible_quote_chunk_ids"] == []
                else:
                    assert target["eligible_quote_chunk_ids"] == [main.chunk_id]
                value = AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=body["parts"][0]["part_id"],
                            status="candidate",
                            quotes=(QuoteDraft(chunk_id=main.chunk_id, quote=main.retrieval_text),),
                            reason_code=None,
                        ),
                        PartDraft(
                            part_id=target["part_id"],
                            status="unknown" if mode == "override" else "candidate",
                            quotes=()
                            if mode == "override"
                            else (QuoteDraft(chunk_id=main.chunk_id, quote=main.retrieval_text),),
                            reason_code="context_only" if mode == "override" else None,
                        ),
                    )
                )
            return wire(value)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            flow = OfflineRagWorkflow(
                settings=config,
                chat=providers.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="dependency_context",
                directory_authority=authority,
            )
            result = await flow.run(
                WorkflowRequest(query=first + second, language="en" if language == "en" else "ar")
            )
        if mode in {"missing_reference", "empty_language"}:
            expected = (
                "retrieval_query_lost_reference_context"
                if mode == "missing_reference"
                else "planner_source_filters_have_empty_intersection"
            )
            assert result.result.error_code == expected
            assert len(seen) == 1 and not retriever.calls
        else:
            assert result.result.outcome == "draft_ready", result.result
            assert len(seen) == 2
            queries = retriever.calls[0][0]
            assert queries[1].text == second + " " + first
            assert queries[1].scope.document_ids == ("profile" if mode == "override" else "main",)
            assert queries[1].scope.owner_id == "a" and queries[1].scope.language == "en"
            assert result.result.parts[1].status == (
                "unknown" if mode == "override" else "candidate"
            )
            assert all(q.chunk_id != other.chunk_id for p in result.result.parts for q in p.quotes)
            assert result.result.parts[0].quotes[0].source_url == main.canonical_url
            assert result.result.parts[0].quotes[0].literal_owner_id == "a"
        assert not result.result.semantic_grounding_verified
        assert not result.result.luna_compatibility_verified

    asyncio.run(run())


@pytest.mark.parametrize(
    "language,first,second",
    [
        (
            "en",
            "Report the main entry for Synthetic Person A.",
            " Which of the two entries did I mean for training?",
        ),
        ("ar", "انقل المدخل الرئيسي للشخص التجريبي أ.", " أي المدخلين قصدت للمؤهلات؟"),
        ("ar-JO", "هات المدخل الرئيسي للشخص التجريبي أ.", " أي واحد من المدخلين قصدي للمؤهلات؟"),
    ],
)
def test_same_person_ambiguous_source_preserves_clear_sibling_without_retrieving_ambiguity(
    language, first, second
):
    async def run():
        main, _, _, evidence, authority = owned_fixture()
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        retriever = FakeRetriever(lambda i, q: (main.chunk_id,))
        seen = []
        flow = None

        def handler(request):
            body = json.loads(json.loads(request.read())["messages"][-1]["content"])
            seen.append(body)
            if len(seen) == 1:
                handle = next(h for h, i in flow._bindings.documents.items() if i == "main")
                value = AnchoredPlannerReply(
                    language=language,
                    parts=(
                        part(first, document_handles=(handle,)),
                        part(
                            second,
                            state="clarification_required",
                            retrieval_query=None,
                            reason="Two entries of the same person; which source?",
                        ),
                    ),
                )
            else:
                assert body["parts"][1]["state"] == "clarification_required"
                assert body["parts"][1]["eligible_quote_chunk_ids"] == []
                value = AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=body["parts"][0]["part_id"],
                            status="candidate",
                            quotes=(QuoteDraft(chunk_id=main.chunk_id, quote=main.retrieval_text),),
                            reason_code=None,
                        ),
                        PartDraft(
                            part_id=body["parts"][1]["part_id"],
                            status="clarification_required",
                            quotes=(),
                            reason_code="ambiguous_request",
                        ),
                    )
                )
            return wire(value)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            flow = OfflineRagWorkflow(
                settings=config,
                chat=providers.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="dependency_context",
                directory_authority=authority,
            )
            result = await flow.run(WorkflowRequest(query=first + second))
        assert result.result.outcome == "draft_ready", result.result
        assert len(seen) == 2 and len(retriever.calls[0][0]) == 1
        assert retriever.calls[0][0][0].text == first
        assert result.result.parts[0].status == "candidate"
        assert result.result.parts[1].status == "clarification_required"
        assert not result.result.parts[1].quotes
        assert not result.result.semantic_grounding_verified

    asyncio.run(run())


def test_shared_screen_retains_unreviewed_status_for_mock_dependency_response(tmp_path):
    async def run():
        _, evidence, authority = fixtures()
        bindings = SourceBindings(
            evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
        )
        request = WorkflowRequest(query="Report the literal source.")
        config = screen_settings(profile="dependency_context", output_cap=4096)
        payload = planner_payload(
            planner_messages(request, bindings, max_parts=4, profile="dependency_context"),
            config,
            profile="dependency_context",
            output_cap=4096,
        )
        packet = {
            "case_id": "synthetic-en",
            "request": request.model_dump(mode="json"),
            "payload": payload,
            "payload_sha256": payload_hash(payload),
        }

        def handler(received):
            assert json.loads(received.read()) == payload
            return wire(AnchoredPlannerReply(language="en", parts=(part(request.query),)))

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            summary = await run_packets(
                [packet],
                bindings,
                config,
                providers.chat,
                tmp_path,
                profile="dependency_context",
                case_ids=("synthetic-en",),
                inventory=("synthetic-en",),
                output_cap=4096,
            )
        assert summary["schema_valid"] == summary["literal_bindings_valid"] == 1
        row = json.loads((tmp_path / "synthetic-en.json").read_bytes())
        assert row["physical_attempts"] == 1 and row["answer_targets"]
        assert row["semantic_review"] == "pending"

    asyncio.run(run())
