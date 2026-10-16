"""Authored contract/graph regressions, never a model semantic accuracy score."""

import asyncio
import json

import httpx2 as httpx
import pytest
from test_anchored_workflow import part, wire
from test_dependency_context import owned_fixture
from test_offline_workflow import FakeRetriever, SyntheticCounter

from scripts.run_luna_planner_screen import (
    payload_hash,
    planner_payload,
    run_packets,
    screen_settings,
)
from telescope_rag.core.settings import Settings
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import (
    AnswerDraft,
    HistoryTurn,
    PartDraft,
    QuoteDraft,
    WorkflowRequest,
)
from telescope_rag.graph.planning import planner_messages
from telescope_rag.graph.workflow import OfflineRagWorkflow
from telescope_rag.prompts import planner_constraints_v11, planner_dependencies_v10
from telescope_rag.providers.openrouter import OpenRouterProviders

TEXTS = [
    (
        "en",
        "Use only the English main entry for Synthetic Person A; exclude Synthetic Person B.",
        " Which role for Synthetic Person A?",
        " And training?",
        " For training use the English standalone entry instead.",
        " Book a private appointment.",
        "exclude Synthetic Person B",
    ),
    (
        "ar",
        "استخدم المدخل الرئيسي الإنجليزي فقط للشخص التجريبي أ؛ استبعد الشخص التجريبي ب.",
        " ما دور الشخص التجريبي أ؟",
        " وما مؤهلاته؟",
        " للمؤهلات استخدم المدخل الإنجليزي المستقل بدلاً منه.",
        " احجز موعداً خاصاً.",
        "استبعد الشخص التجريبي ب",
    ),
    (
        "ar-JO",
        "من المدخل الرئيسي الإنجليزي بس للشخص التجريبي أ؛ لا تحكي عن الشخص التجريبي ب.",
        " شو دور الشخص التجريبي أ؟",
        " وشو مؤهلاته؟",
        " بس للمؤهلات استخدم المدخل الإنجليزي اللي لحاله.",
        " احجزلي موعد خاص.",
        "لا تحكي عن الشخص التجريبي ب",
    ),
]


@pytest.mark.parametrize("text", TEXTS)
def test_candidate_changes_only_system_append_and_version(text):
    _, _, _, evidence, authority = owned_fixture()
    bindings = SourceBindings(
        evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
    )
    request = WorkflowRequest(query=text[1] + text[2] + text[3])
    old, new = (
        planner_messages(request, bindings, max_parts=4, profile=p)
        for p in ("dependency_context", "local_constraints")
    )
    assert old[0].content == planner_dependencies_v10.PLANNER_SYSTEM
    assert new[0].content == old[0].content + planner_constraints_v11.LOCAL_CONSTRAINTS_APPEND
    left, right = (json.loads(m[-1].content) for m in (old, new))
    assert left.pop("prompt_version") == planner_dependencies_v10.PROMPT_VERSION
    assert right.pop("prompt_version") == planner_constraints_v11.PROMPT_VERSION
    assert left == right
    config = screen_settings(profile="local_constraints", output_cap=4096)
    a, b = (
        planner_payload(m, config, profile=p, output_cap=4096)
        for m, p in zip((old, new), ("dependency_context", "local_constraints"), strict=True)
    )
    assert {k: v for k, v in a.items() if k != "messages"} == {
        k: v for k, v in b.items() if k != "messages"
    }
    assert "reasoning" not in b
    assert b["response_format"]["json_schema"]["strict"] is True


@pytest.mark.parametrize("enabled,authority_present", [(False, True), (True, False)])
def test_candidate_still_requires_purpose_contract_and_authority(enabled, authority_present):
    _, _, _, evidence, authority = owned_fixture()
    bindings = SourceBindings(
        evidence,
        purpose_contract=enabled,
        directory_authority=authority if authority_present else None,
    )
    with pytest.raises(ValueError, match="planner_purpose_contract_configuration_mismatch"):
        planner_messages(
            WorkflowRequest(query="Synthetic."), bindings, max_parts=4, profile="local_constraints"
        )


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize(
    "mode",
    [
        "leading",
        "trailing",
        "history",
        "override",
        "outside",
        "lost_reference",
        "coverage",
        "mixed",
    ],
)
def test_actual_graph_preserves_locality_context_coverage_scope_and_owner(text, mode):
    async def run():
        language, prefix, role, training, override, private, negative = text
        main, other, profile, evidence, authority = owned_fixture()
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        seen = []
        retriever = FakeRetriever(
            lambda i, q: (profile.chunk_id if i == 1 and mode == "override" else main.chunk_id,)
        )
        first, second = prefix + role, training
        if mode == "trailing":
            first, second = role, training + " " + prefix
        elif mode == "history":
            first = role
        elif mode == "override":
            second += override
        request = WorkflowRequest(
            query=first + second + (private if mode == "mixed" else ""),
            language="en" if language == "en" else "ar",
            history=(HistoryTurn(role="user", content=prefix),) if mode == "history" else (),
        )
        flow = None

        def handler(received):
            payload = json.loads(received.read())
            body = json.loads(payload["messages"][-1]["content"])
            seen.append(body)
            assert body["prompt_version"] == planner_constraints_v11.PROMPT_VERSION
            if len(seen) == 1:
                handles = {i: h for h, i in flow._bindings.documents.items()}
                owner = next(h for h, i in flow._bindings.owners.items() if i == ("literal", "a"))
                first_ref = prefix if mode in {"trailing", "history"} else None
                local_first = (negative,) if mode not in {"trailing", "history", "coverage"} else ()
                local_second = (negative,) if mode in {"trailing", "outside"} else ()
                first_query = first + (" " + prefix if first_ref else "")
                second_ref = prefix
                second_query = second + " " + prefix
                if mode == "lost_reference":
                    second_query = second
                planned = [
                    part(
                        role if mode == "coverage" else first,
                        constraint_quotes=local_first,
                        intended_use="doctor_role",
                        retrieval_query=first_query,
                        reference_text=first_ref,
                        history_indices=(0,) if mode == "history" else (),
                        document_handles=(handles["main"],),
                        owner_handle=owner,
                        source_language="en",
                    ),
                    part(
                        second,
                        constraint_quotes=local_second,
                        intended_use="profile_detail",
                        retrieval_query=second_query,
                        reference_text=second_ref,
                        history_indices=(0,) if mode == "history" else (),
                        document_handles=(handles["profile" if mode == "override" else "main"],),
                        owner_handle=owner,
                        source_language="en",
                    ),
                ]
                if mode == "mixed":
                    planned.append(
                        part(
                            private,
                            state="excluded",
                            retrieval_query=None,
                            reason="Private booking is excluded.",
                        )
                    )
                return wire(AnchoredPlannerReply(language=language, parts=tuple(planned)))
            assert body["parts"][0]["answer_target"] == first
            assert body["parts"][1]["answer_target"] == second
            assert body["parts"][1]["constraint_quotes"] == (
                list((negative,)) if mode == "trailing" else []
            )
            assert body["parts"][1]["reference_context"]["literal_text"] == prefix
            assert body["parts"][1]["reference_context"]["role"] == "interpretation_only"
            assert body["parts"][1]["reference_context"]["history_indices"] == (
                [0] if mode == "history" else []
            )
            parts = []
            for index, target in enumerate(body["parts"]):
                excluded = index == 2
                unknown = index == 1 and mode == "override"
                if excluded:
                    assert target["eligible_quote_chunk_ids"] == []
                parts.append(
                    PartDraft(
                        part_id=target["part_id"],
                        status="excluded" if excluded else "unknown" if unknown else "candidate",
                        quotes=()
                        if excluded or unknown
                        else (QuoteDraft(chunk_id=main.chunk_id, quote=main.retrieval_text),),
                        reason_code="scope_excluded"
                        if excluded
                        else "context_only"
                        if unknown
                        else None,
                    )
                )
            return wire(AnswerDraft(parts=tuple(parts)))

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            flow = OfflineRagWorkflow(
                settings=config,
                chat=providers.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="local_constraints",
                directory_authority=authority,
            )
            result = await flow.run(request)
        if mode in {"outside", "lost_reference", "coverage"}:
            assert len(seen) == 1 and not retriever.calls
            if mode != "coverage":
                assert (
                    result.result.error_code
                    == {
                        "outside": "constraint_outside_original_part",
                        "lost_reference": "retrieval_query_lost_reference_context",
                    }[mode]
                )
            else:
                assert result.result.error_code == "invalid_plan"
        else:
            assert result.result.outcome == "draft_ready", result.result
            assert len(seen) == 2 and len(retriever.calls) == 1
            queries = retriever.calls[0][0]
            assert len(queries) == 2
            assert all(negative in q.text and q.scope.owner_id == "a" for q in queries)
            assert queries[0].scope.document_ids == ("main",)
            assert queries[1].scope.document_ids == ("profile" if mode == "override" else "main",)
            assert all(q.chunk_id != other.chunk_id for p in result.result.parts for q in p.quotes)
            assert result.result.parts[0].quotes[0].literal_owner_id == "a"
            assert result.result.parts[0].quotes[0].source_url == main.canonical_url
            assert result.result.parts[1].status == (
                "unknown" if mode == "override" else "candidate"
            )
            if mode == "mixed":
                assert (
                    result.result.parts[2].status == "excluded"
                    and not result.result.parts[2].quotes
                )
        assert not result.result.semantic_grounding_verified
        assert not result.result.luna_compatibility_verified

    asyncio.run(run())


def test_shared_screen_records_mock_candidate_as_pending_not_semantically_verified(tmp_path):
    async def run():
        _, _, _, evidence, authority = owned_fixture()
        bindings = SourceBindings(
            evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
        )
        request = WorkflowRequest(query="Report the source.")
        config = screen_settings(profile="local_constraints", output_cap=4096)
        payload = planner_payload(
            planner_messages(request, bindings, max_parts=4, profile="local_constraints"),
            config,
            profile="local_constraints",
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
                profile="local_constraints",
                case_ids=("synthetic-en",),
                inventory=("synthetic-en",),
                output_cap=4096,
            )
        assert summary["schema_valid"] == summary["literal_bindings_valid"] == 1
        row = json.loads((tmp_path / "synthetic-en.json").read_bytes())
        assert row["physical_attempts"] == 1 and row["answer_targets"]
        assert row["semantic_review"] == "pending"

    asyncio.run(run())
