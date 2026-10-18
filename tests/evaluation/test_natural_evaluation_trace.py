"""Trace contracts with synthetic ASGI requests; no provider/database connections."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx2 as httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from telescope_rag.graph.contracts import BudgetSummary, RetrievalBatch, RetrievedPart
from telescope_rag.providers.contracts import (
    AttemptReceipt,
    ChatMessage,
    EmbeddingResult,
    StructuredResult,
    UsageReport,
)

SPEC = importlib.util.spec_from_file_location(
    "natural_evaluation_trace", Path(__file__).parents[2] / "scripts/natural_evaluation_trace.py"
)
assert SPEC is not None and SPEC.loader is not None
trace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trace)

SECRET = "synthetic-secret-must-never-be-exported"
VECTOR = (173.234567, 12.345678)


class Reply(BaseModel):
    answer: str


def receipt(kind="chat", *, usage=None):
    return AttemptReceipt(
        operation=1,
        kind=kind,
        attempt=1,
        requested_model="synthetic-model",
        reported_model="synthetic-model",
        provider="synthetic-provider",
        status_code=200,
        outcome="success",
        input_reserved=None if kind == "chat" else 8,
        output_reserved=64 if kind == "chat" else 0,
        count_profile="synthetic-profile",
        count_basis="reported_usage_only" if kind == "chat" else "exact",
        usage=UsageReport() if usage is None else usage,
    )


class FakeCache:
    def __init__(self, hit):
        self.hit = hit
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return VECTOR if self.hit else None


class FakeEmbeddings:
    def __init__(self, error):
        self.calls = []
        self.error = error
        self.returned = None

    async def embed(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        self.returned = EmbeddingResult(
            vectors=(VECTOR,),
            requested_model="synthetic-model",
            dimensions=2,
            format_version="synthetic-v1",
            receipts=(receipt("embedding"),),
        )
        return self.returned


class FakeReader:
    def __init__(self):
        self.calls = []
        self.returned = []

    async def search(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        await asyncio.sleep(0)
        result = (
            SimpleNamespace(
                chunk=SimpleNamespace(chunk_id="dense-support", point_id="point-1"), score=0.75
            ),
        )
        self.returned.append(result)
        return result


class FakeRetriever:
    def __init__(self, cache_hit, error):
        self._cache = FakeCache(cache_hit)
        self._reader = FakeReader()
        self._embeddings = FakeEmbeddings(error)
        self.calls = []
        self.returned = None

    async def retrieve(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        vector = self._cache.get("synthetic-query-hash", "synthetic-config-hash", 2)
        if vector is None:
            result = await self._embeddings.embed(
                ["Synthetic public question"],
                role="query",
                format=SimpleNamespace(version="synthetic-v1"),
                budget=kwargs["budget"],
            )
            vector = result.vectors[0]
        hits = await self._reader.search(vector, limit=5, point_ids=("point-1", "point-2"))
        assert hits is self._reader.returned[-1]
        self.returned = RetrievalBatch(
            snapshot_id=kwargs["snapshot_id"],
            prepared_digest=kwargs["prepared_digest"],
            parts=(RetrievedPart(part_id="p1", chunk_ids=("dense-support", "literal-support")),),
        )
        return self.returned


class FakeChat:
    def __init__(self):
        self.calls = []
        self.returned = []

    async def complete(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        result = StructuredResult(Reply(answer="Synthetic answer"), (receipt(),))
        self.returned.append(result)
        return result


class FakeWorkflow:
    def __init__(self, *, cache_hit=False, error=None, failed=False, pause=None):
        self._retriever = FakeRetriever(cache_hit, error)
        self._chat = FakeChat()
        self.calls = []
        self.returned = []
        self.failed = failed
        self.pause = pause
        self.budget = SimpleNamespace(secret=SECRET)

    async def run(self, request, *, request_id):
        self.calls.append(((request,), {"request_id": request_id}))
        if self.pause is not None:
            self.pause[0].set()
            await self.pause[1].wait()
        result = await self._chat.complete(
            (ChatMessage(role="user", content='{"source_manifest":"not evidence"}'),),
            Reply,
            max_output_tokens=64,
            budget=self.budget,
        )
        assert result is self._chat.returned[-1]
        retrieved = await self._retriever.retrieve(
            [{"part_id": "p1", "text": request["query"], "scope": {"owner_id": "owner-1"}}],
            snapshot_id="snapshot",
            prepared_digest="digest",
            budget=self.budget,
        )
        assert retrieved is self._retriever.returned
        body = {
            "parts": [
                {
                    "part_id": "p1",
                    "eligible_quote_chunk_ids": ["literal-support"],
                    "validated_hours": {"status": "schedule_available"},
                }
            ],
            "untrusted_candidate_rendering": "Synthetic admitted evidence only",
            "untrusted_website_links": [],
        }
        result = await self._chat.complete(
            (
                ChatMessage(role="system", content="Synthetic writer"),
                ChatMessage(role="user", content=json.dumps(body)),
            ),
            Reply,
            max_output_tokens=64,
            budget=self.budget,
        )
        assert result is self._chat.returned[-1]
        evidence = SimpleNamespace(
            prepared_digest="digest",
            groups=(
                SimpleNamespace(
                    group_id="g1",
                    part_occurrences=(("p1", ("literal-support", "other-occurrence")),),
                    context_only_parts=(),
                    occurrences=(
                        SimpleNamespace(
                            chunk_id="literal-support",
                            document_id="doc-1",
                            canonical_url="https://example.invalid/public",
                            snapshot_id="snapshot",
                            doctor_id="owner-1",
                            canonical_doctor_id="owner-1",
                        ),
                    ),
                ),
            ),
            parts=(
                {
                    "part_id": "p1",
                    "occurrence_ids": ["literal-support", "other-occurrence"],
                    "omitted_group_ids": ["dense-group"],
                    "candidate_status": "budget_limited",
                },
            ),
            rendered_text=body["untrusted_candidate_rendering"],
            token_count=14,
            token_profile="synthetic-profile",
            token_basis="synthetic_test",
        )
        output = SimpleNamespace(
            request=request,
            result={
                "request_id": str(request_id),
                "outcome": "failed" if self.failed else "draft_ready",
                "error_code": "deadline_exceeded" if self.failed else None,
            },
            plan={"operations": ["search"]},
            evidence=evidence,
            stages=("plan", "retrieve"),
            usage=BudgetSummary(2, 1, 2, 1, None, 8, 128, (receipt(), receipt())),
            request_anchors=(),
            answer_targets=(),
            computed_hours=(),
            operation_clock=None,
            conversation={"parts": []},
        )
        self.returned.append(output)
        return output


def application(**kwargs):
    app = FastAPI()
    workflow = FakeWorkflow(**kwargs)
    app.state.offline_chat_service = SimpleNamespace(_workflow=workflow)
    app.state.secret = SECRET

    @app.post("/api/v1/chat")
    async def chat(payload: dict):
        run = await app.state.offline_chat_service._workflow.run(payload, request_id=UUID(int=1))
        assert run is workflow.returned[-1]
        return {"answer": "Synthetic answer", "outcome": run.result["outcome"]}

    return app, workflow


async def post(app, query="وين موقع المركز؟"):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test.invalid"
    ) as client:
        return await client.post("/api/v1/chat", json={"query": query})


def test_tracing_preserves_http_calls_results_and_evidence_stage_boundaries():
    async def scenario():
        baseline, original = application()
        expected = await post(baseline)
        app, workflow = application()
        capture = trace.install_capture(app)
        capture.reset("Q01-ar")
        actual = await post(app)
        assert actual.status_code == expected.status_code == 200
        assert actual.json() == expected.json()
        assert workflow.calls == original.calls
        assert len(workflow._chat.calls) == len(original._chat.calls) == 2
        assert len(workflow._retriever.calls) == len(original._retriever.calls) == 1
        assert workflow._retriever._reader.calls == original._retriever._reader.calls
        assert workflow._retriever._cache.calls == original._retriever._cache.calls
        for _, kwargs in workflow._chat.calls + workflow._retriever.calls:
            assert kwargs["budget"] is workflow.budget
        data = capture.snapshot()
        assert data["case_id"] == "Q01-ar" and not data["capture_errors"]
        assert data["workflow_runs"][0]["request"] == {"query": "وين موقع المركز؟"}
        assert data["dense_calls"][0]["requested_limit"] == 5
        assert data["dense_calls"][0]["hits"][0] == {
            "rank": 1,
            "chunk_id": "dense-support",
            "point_id": "point-1",
            "score": 0.75,
        }
        assert data["dense_calls"][0]["part_binding"] == "unavailable"
        assert data["retrieval_calls"][0]["batch"]["parts"][0]["chunk_ids"] == [
            "dense-support",
            "literal-support",
        ]
        writer = data["writer_contexts"][0]["body"]
        assert writer["parts"][0]["eligible_quote_chunk_ids"] == ["literal-support"]
        assert "dense-support" not in writer["untrusted_candidate_rendering"]
        assert len(data["writer_contexts"]) == 1  # planner manifest is never answer context
        assert data["workflow_runs"][0]["evidence"]["parts"][0]["omitted_group_ids"] == [
            "dense-group"
        ]
        assert data["cost"] is None and data["cost_status"] == "unavailable"
        usage = data["workflow_runs"][0]["usage"]
        assert usage["charged_output"] == 128
        assert usage["receipts"][0]["usage"]["output_tokens"] is None
        assert data["cache_reads"][0]["hit"] is False
        assert data["embedding_calls"][0]["texts"] == ["Synthetic public question"]
        encoded = json.dumps(data, allow_nan=False)
        assert SECRET not in encoded and str(VECTOR[0]) not in encoded
        assert "vectors" not in encoded and "headers" not in encoded
        assert all(row["run_index"] == 0 for row in data["chat_calls"])
        data["chat_calls"].clear()
        assert len(capture.snapshot()["chat_calls"]) == 2
        assert trace.install_capture(app) is capture

    asyncio.run(scenario())


def test_cache_hit_skips_embedding_and_reset_does_not_reuse_previous_case_trace():
    async def scenario():
        app, _ = application(cache_hit=True)
        capture = trace.install_capture(app)
        for case_id, query in (("Q01-ar", "وين موقعكم؟"), ("Q01-en", "Where are you?")):
            capture.reset(case_id)
            assert (await post(app, query)).status_code == 200
            data = capture.snapshot()
            assert len(data["workflow_runs"]) == 1 and data["case_id"] == case_id
            assert data["cache_reads"][0]["hit"] is True
            assert not data["embedding_calls"]
            assert data["retrieval_calls"][0]["queries"][0]["text"] == query

    asyncio.run(scenario())


def test_raised_exception_identity_and_cancellation_are_preserved_without_message_leaks():
    async def scenario(error):
        app, _ = application(error=error)
        capture = trace.install_capture(app)
        capture.reset("failure")
        with pytest.raises(type(error)) as caught:
            await post(app)
        assert caught.value is error
        data = capture.snapshot()
        assert data["active_workflows"] == 0
        assert data["workflow_runs"][0]["outcome"] == "raised"
        assert data["embedding_calls"][0]["error_type"] == type(error).__name__
        assert SECRET not in json.dumps(data)
        capture.reset("following-case")
        assert not capture.snapshot()["workflow_runs"]

    for error in (RuntimeError(SECRET), asyncio.CancelledError(SECRET)):
        asyncio.run(scenario(error))


def test_failed_workflow_retains_available_run_and_missing_usage():
    async def scenario():
        app, _ = application(failed=True)
        capture = trace.install_capture(app)
        capture.reset("failed-result")
        response = await post(app)
        assert response.json()["outcome"] == "failed"
        run = capture.snapshot()["workflow_runs"][0]
        assert run["result"]["error_code"] == "deadline_exceeded"
        assert run["usage"]["charged_chat_input"] is None
        assert run["usage"]["receipts"][0]["usage"]["input_tokens"] is None

    asyncio.run(scenario())


def test_reset_refuses_an_active_case_and_concurrent_calls_are_explicitly_flagged():
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        app, _ = application(pause=(started, release))
        capture = trace.install_capture(app)
        capture.reset("active-case")
        first = asyncio.create_task(post(app, "First question"))
        await started.wait()
        with pytest.raises(RuntimeError, match="reset_during_active_request"):
            capture.reset("second-case")
        second = asyncio.create_task(post(app, "Second question"))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)
        data = capture.snapshot()
        assert data["concurrent_run_detected"] and data["active_workflows"] == 0
        assert {row["run_index"] for row in data["retrieval_calls"]} == {0, 1}
        for row in data["retrieval_calls"]:
            expected = "First question" if row["run_index"] == 0 else "Second question"
            assert row["queries"][0]["text"] == expected

    asyncio.run(scenario())


def test_telemetry_serialization_failure_does_not_replace_a_successful_http_result():
    async def scenario():
        app, workflow = application()
        capture = trace.install_capture(app)
        capture.reset("unserializable-run")
        original = trace._run

        def broken_normalizer(result):
            raise ValueError(SECRET)

        trace._run = broken_normalizer
        try:
            assert (await post(app)).status_code == 200
            assert len(workflow.calls) == 1
            data = capture.snapshot()
            assert data["capture_errors"] == [{"hook": "workflow_runs", "error_type": "ValueError"}]
            assert SECRET not in json.dumps(data)
        finally:
            trace._run = original

    asyncio.run(scenario())


class Chunks(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body
        self.closed = False

    async def __aiter__(self):
        yield self.body[:10]
        yield self.body[10:]

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize(
    "costs,total,known,complete",
    [
        ((0.01, 0.02), 0.03, 0.03, True),
        ((0, 0), 0, 0, True),
        ((None, 0.02), None, 0.02, False),
        (("0.01", False), None, None, False),
        ((-0.01, float("inf")), None, None, False),
    ],
)
def test_cost_transport_reads_existing_responses_without_extra_calls_or_body_exports(
    costs, total, known, complete
):
    async def scenario():
        requests, streams = [], []

        def handler(request):
            requests.append(request)
            body = json.dumps(
                {
                    "id": f"gen-synthetic-{len(requests)}",
                    "usage": {"cost": costs[len(requests) - 1]},
                    "private_extra": SECRET,
                }
            ).encode()
            stream = Chunks(body)
            streams.append(stream)
            return httpx.Response(200, stream=stream)

        transport = trace.RecordedCostTransport(httpx.MockTransport(handler))
        app, workflow = application()
        original = workflow._chat.complete

        async def complete_chat(*args, **kwargs):
            async with httpx.AsyncClient(transport=transport) as client:
                response = await client.post(
                    "https://provider.invalid/chat/completions",
                    content=b"synthetic-public-request",
                    headers={"Authorization": f"Bearer {SECRET}"},
                )
                assert response.content == streams[-1].body
            return await original(*args, **kwargs)

        workflow._chat.complete = complete_chat
        capture = trace.install_capture(app)
        transport.capture = capture
        capture.reset("cost-case")
        assert (await post(app)).status_code == 200
        assert len(requests) == 2 and all(stream.closed for stream in streams)
        data = capture.snapshot()
        assert len(data["cost_events"]) == 2
        assert data["cost"] == {
            "reported_usd": total,
            "known_reported_usd": known,
            "complete": complete,
            "basis": "provider_response_usage_cost",
        }
        assert SECRET not in json.dumps(data)
        if complete:
            assert data["cost_events"][0]["generation_id"] == "gen-synthetic-1"

    asyncio.run(scenario())


@pytest.mark.parametrize("partial", [False, True])
def test_cost_capture_bound_or_partial_read_keeps_cost_unknown_and_bytes_unchanged(partial):
    async def scenario():
        body = json.dumps({"usage": {"cost": 0.5}, "extra": SECRET}).encode()
        transport = trace.RecordedCostTransport(
            httpx.MockTransport(lambda request: httpx.Response(200, stream=Chunks(body)))
        )
        if not partial:
            transport.MAX_CAPTURE_BYTES = 5
        # The limit belongs to the stream policy class, not a request parameter.
        old_limit = trace.RecordedCostTransport.MAX_CAPTURE_BYTES
        if not partial:
            trace.RecordedCostTransport.MAX_CAPTURE_BYTES = 5
        app, workflow = application()
        original = workflow._chat.complete

        async def complete_chat(*args, **kwargs):
            async with httpx.AsyncClient(transport=transport) as client:
                if partial:
                    async with client.stream("POST", "https://provider.invalid/embeddings") as r:
                        async for chunk in r.aiter_bytes():
                            assert chunk == body[:10]
                            break
                else:
                    response = await client.post("https://provider.invalid/chat/completions")
                    assert response.content == body
            return await original(*args, **kwargs)

        workflow._chat.complete = complete_chat
        capture = trace.install_capture(app)
        transport.capture = capture
        capture.reset("bounded-cost-case")
        try:
            assert (await post(app)).status_code == 200
            data = capture.snapshot()
            assert data["cost"]["reported_usd"] is None
            assert data["cost"]["complete"] is False
            assert SECRET not in json.dumps(data)
            assert not data["capture_errors"]
        finally:
            trace.RecordedCostTransport.MAX_CAPTURE_BYTES = old_limit

    asyncio.run(scenario())
