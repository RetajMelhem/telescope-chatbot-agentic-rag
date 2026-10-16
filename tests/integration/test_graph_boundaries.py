"""Cross-stage isolation and fail-closed dispatch/tracing tests; synthetic inputs only."""

import asyncio
from uuid import UUID

import httpx2
import pytest
from langsmith import Client
from langsmith.run_helpers import get_tracing_context
from test_offline_workflow import (
    FakeRetriever,
    SyntheticCounter,
    catalog,
    part,
    single_plan,
    source,
    workflow,
)

from telescope_rag.core.settings import Settings
from telescope_rag.graph.contracts import PlannerReply, WorkflowRequest
from telescope_rag.graph.workflow import OfflineRagWorkflow, WorkflowError
from telescope_rag.providers.openrouter import OpenRouterProviders


def test_actual_provider_explicit_strict_count_gate_blocks_graph_before_any_http_dispatch():
    async def scenario():
        dispatched = []

        def forbidden(request):
            dispatched.append(request)
            raise AssertionError("No provider request is authorized in this test")

        settings = Settings(
            _env_file=None,
            app_env="test",
            openrouter_api_key="synthetic-only",
            chat_input_accounting="strict",
        )
        evidence = catalog(source(1))
        async with OpenRouterProviders(
            settings, transport=httpx2.MockTransport(forbidden)
        ) as providers:
            retriever = FakeRetriever(lambda i, q: tuple(evidence.chunks))
            flow = OfflineRagWorkflow(
                settings=settings,
                chat=providers.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
            )
            run = await flow.run(WorkflowRequest(query="Synthetic request"))
        assert dispatched == [] and retriever.calls == []
        assert run.result.error_code == "provider_failed"
        assert run.usage.physical_chat_attempts == 0
        assert run.result.semantic_grounding_verified is False
        assert run.result.luna_compatibility_verified is False

    asyncio.run(scenario())


def test_ambient_tracing_is_disabled_and_query_and_source_are_not_logged(
    monkeypatch, caplog, capsys
):
    calls = []

    def forbidden_trace(*args, **kwargs):
        calls.append("external_trace")
        raise AssertionError("Tracing must stay disabled")

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setattr(Client, "create_run", forbidden_trace)
    monkeypatch.setattr(Client, "update_run", forbidden_trace)
    flow, chat, _ = workflow(
        catalog(source(1, "SYNTHETIC-SOURCE-PRIVATE-MARKER")),
        single_plan(),
        langsmith_tracing=False,
    )
    original = chat.complete

    async def checked(*args, **kwargs):
        assert get_tracing_context()["enabled"] is False
        return await original(*args, **kwargs)

    chat.complete = checked
    run = asyncio.run(flow.run(WorkflowRequest(query="SYNTHETIC-QUERY-PRIVATE-MARKER")))
    assert run.result.outcome == "draft_ready"
    assert calls == []
    output = capsys.readouterr()
    for marker in ("SYNTHETIC-QUERY-PRIVATE-MARKER", "SYNTHETIC-SOURCE-PRIVATE-MARKER"):
        assert marker not in caplog.text + output.out + output.err


def test_concurrent_runs_share_no_request_ids_budget_or_evidence_assignments():
    async def scenario():
        flow, chat, retriever = workflow(catalog(source(1)), single_plan())
        runs = await asyncio.gather(
            flow.run(WorkflowRequest(query="Synthetic first", history=())),
            flow.run(WorkflowRequest(query="Synthetic second", history=())),
        )
        assert all(r.result.outcome == "draft_ready" for r in runs)
        assert len({r.result.request_id for r in runs}) == 2
        assert len({id(call[2]) for call in chat.calls}) == 2
        assert len(retriever.calls) == 2
        for run in runs:
            assert run.plan.assembly_request.original_query == run.request.query
            assert run.result.parts[0].original_text == run.request.query
            assert run.result.parts[0].part_id.startswith(run.result.request_id)
            assert run.usage.logical_chat_calls == 2
            assert run.usage.logical_embedding_calls == 1
        assert runs[0].stages == runs[1].stages

    asyncio.run(scenario())


def test_retrieval_deadline_terminates_before_assembly_and_generation():
    async def scenario():
        flow, chat, retriever = workflow(
            catalog(source(1)),
            single_plan(),
            request_timeout_seconds=0.05,
            provider_timeout_seconds=0.01,
            readiness_timeout_seconds=0.01,
        )
        original = retriever.retrieve
        entered = asyncio.Event()

        async def delayed(*args, **kwargs):
            await original(*args, **kwargs)
            entered.set()
            await asyncio.Event().wait()

        retriever.retrieve = delayed
        run = await flow.run(WorkflowRequest(query="Synthetic slow retrieval"))
        assert entered.is_set()
        assert run.result.error_code == "deadline_exceeded"
        assert len(chat.calls) == 1
        assert "assemble_evidence" not in run.stages

    asyncio.run(scenario())


def test_untrusted_dependency_exception_text_cannot_escape_or_trigger_a_repair(caplog, capsys):
    flow, chat, retriever = workflow(catalog(source(1)), single_plan())

    async def failure(*args, **kwargs):
        raise RuntimeError("SYNTHETIC-SECRET-EXCEPTION-MARKER")

    retriever.retrieve = failure
    run = asyncio.run(flow.run(WorkflowRequest(query="Synthetic error")))
    assert run.result.error_code == "retrieval_failed"
    assert len(chat.calls) == 1
    output = capsys.readouterr()
    assert "SYNTHETIC-SECRET-EXCEPTION-MARKER" not in (
        run.result.model_dump_json() + caplog.text + output.out + output.err
    )
    assert run.result.parts[0].original_text == "Synthetic error"


@pytest.mark.parametrize("fault", ["production", "synthetic_as_qwen"])
def test_offline_and_token_basis_gates_cannot_be_accidentally_promoted(fault):
    flow, chat, retriever = workflow(catalog(source(1)), single_plan())
    if fault == "production":
        with pytest.raises(WorkflowError, match="offline_workflow_configuration_invalid"):
            OfflineRagWorkflow(
                settings=Settings(_env_file=None, app_env="production", qdrant_api_key="synthetic"),
                chat=chat,
                retriever=retriever,
                catalog=flow._catalog,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
            )
    else:
        candidate = OfflineRagWorkflow(
            settings=Settings(_env_file=None, app_env="test"),
            chat=chat,
            retriever=retriever,
            catalog=flow._catalog,
            counter=SyntheticCounter(),
        )
        run = asyncio.run(candidate.run(WorkflowRequest(query="Synthetic gate")))
        assert run.result.error_code == "assembly_failed"
        assert len(chat.calls) == 1


@pytest.mark.parametrize("invalid", ["forged_request", "untrusted_request_id"])
def test_forged_inputs_fail_before_planning_or_retrieval(invalid):
    flow, chat, retriever = workflow(catalog(source(1)), single_plan())
    request = WorkflowRequest(query="Synthetic")
    options = {}
    if invalid == "forged_request":
        request = request.model_copy(update={"query": " "})
    else:
        options["request_id"] = "model-supplied-ID"
    with pytest.raises(WorkflowError, match="invalid_request"):
        asyncio.run(flow.run(request, **options))
    assert chat.calls == [] and retriever.calls == []


def test_explicit_server_uuid_and_history_survive_planning_as_untrusted_data():
    from telescope_rag.graph.contracts import HistoryTurn

    request = WorkflowRequest(
        query="Synthetic follow-up",
        history=(
            HistoryTurn(role="user", content="Synthetic Doctor A"),
            HistoryTurn(role="assistant", content="Untrusted fabricated clinic claim"),
        ),
    )
    flow, chat, _ = workflow(catalog(source(1)), single_plan())
    identity = UUID(int=45)
    run = asyncio.run(flow.run(request, request_id=identity))
    assert run.result.request_id == identity.hex
    assert chat.calls[0][1]["history"] == [h.model_dump() for h in request.history]
    assert chat.calls[1][1]["history"] == [h.model_dump() for h in request.history]
    assert run.request.history == request.history
    assert "Untrusted fabricated clinic claim" not in run.result.model_dump_json()


def test_time_comparison_is_explicitly_unavailable_without_inventing_hours_or_running_search():
    flow, chat, retriever = workflow(
        catalog(source(1)),
        single_plan(operation="time_comparison", retrieval_query=None),
    )
    query = "Synthetic Friday at 7 PM comparison"
    run = asyncio.run(flow.run(WorkflowRequest(query=query)))
    assert run.result.outcome == "not_found"
    assert run.result.parts[0].reason_code == "operation_unavailable"
    assert run.result.parts[0].original_text == query
    assert not run.result.parts[0].quotes
    assert len(chat.calls) == 1 and retriever.calls == []


@pytest.mark.parametrize("state", ["excluded", "clarification_required"])
def test_entire_nonpublic_request_finishes_without_search_or_answer_generation(state):
    flow, chat, retriever = workflow(
        catalog(source(1)),
        single_plan(state=state, retrieval_query=None, reason="Synthetic boundary"),
    )
    run = asyncio.run(flow.run(WorkflowRequest(query="Synthetic nonpublic request")))
    assert run.result.outcome == ("out_of_scope" if state == "excluded" else state)
    assert run.result.parts[0].status == state
    assert not run.result.parts[0].quotes
    assert retriever.calls == [] and len(chat.calls) == 1


def test_two_doctors_with_identical_specialty_text_stay_owned_and_filter_before_assembly():
    a = source(1, "Synthetic shared specialty", doctor_id="owner-a", doctor_name="Doctor A")
    b = source(2, "Synthetic shared specialty", doctor_id="owner-b", doctor_name="Doctor B")

    def planner(body):
        handle = next(
            o["handle"]
            for o in body["source_manifest"]["owners"]
            if o["literal_source_labels"] == ["Doctor A"]
        )
        return PlannerReply(
            language="en",
            parts=(
                part(
                    body["original_query"],
                    owner_handle=handle,
                    intended_use="doctor_role",
                ),
            ),
        )

    flow, _, _ = workflow(catalog(a, b), planner, chunks=lambda i, q: (b.chunk_id, a.chunk_id))
    run = asyncio.run(flow.run(WorkflowRequest(query="Synthetic Doctor A specialty")))
    assert run.result.outcome == "draft_ready"
    assert [q.literal_owner_id for q in run.result.parts[0].quotes] == ["owner-a"]
    assert run.evidence.parts[0].filtered_occurrence_ids == (b.chunk_id,)
    assert len(run.evidence.groups) == 1
    assert len(flow._catalog.chunks) == 2


def test_new_unrecognized_source_limit_stays_context_only_without_default_factual_admission():
    item = source(1, source_issue_codes=("synthetic_new_unknown_policy_code",))
    flow, chat, retriever = workflow(catalog(item), single_plan())
    run = asyncio.run(flow.run(WorkflowRequest(query="Synthetic unknown source policy")))
    assert len(retriever.calls) == 1 and len(chat.calls) == 1
    assert run.result.outcome == "not_found"
    assert run.result.parts[0].reason_code == "context_only"
    assert not run.result.parts[0].quotes
    assert run.evidence.groups[0].occurrences[0].source_issue_codes == item.source_issue_codes
