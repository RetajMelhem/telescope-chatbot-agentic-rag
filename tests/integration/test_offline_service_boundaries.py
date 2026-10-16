"""Real HTTP cancellation, concurrency and explicit resource ownership with injected fakes."""

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import httpx2 as httpx
from fastapi.testclient import TestClient
from test_anchored_workflow import part, wire
from test_dependency_context import owned_fixture
from test_offline_service import RecordingChat, compose, setup, synthetic_settings
from test_offline_workflow import FakeRetriever

from telescope_rag.api.main import create_app
from telescope_rag.core import middleware as middleware_module
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft
from telescope_rag.providers.openrouter import OpenRouterProviders


def test_concurrent_http_requests_keep_owners_ids_and_request_budgets_separate():
    async def run():
        config = synthetic_settings()
        main, other, _, evidence, authority = owned_fixture()
        bindings = SourceBindings(
            evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
        )
        handle = next(h for h, i in bindings.documents.items() if i == "main")
        owners = {i[1]: h for h, i in bindings.owners.items() if i[0] == "literal"}
        requests = {
            "Report Synthetic Person A.": ("a", main),
            "انقل نص الشخص التجريبي ب.": ("b", other),
        }
        planned = []
        both_entered = asyncio.Event()

        async def handler(received):
            body = json.loads(json.loads(received.read())["messages"][-1]["content"])
            if "max_parts" in body:
                owner, _ = requests[body["original_query"]]
                planned.append(owner)
                if len(planned) == 2:
                    both_entered.set()
                await both_entered.wait()
                return wire(
                    AnchoredPlannerReply(
                        language="en" if owner == "a" else "ar",
                        parts=(
                            part(
                                body["original_query"],
                                intended_use="doctor_role",
                                document_handles=(handle,),
                                owner_handle=owners[owner],
                            ),
                        ),
                    )
                )
            return wire(
                AnswerDraft(
                    parts=tuple(
                        PartDraft(
                            part_id=p["part_id"],
                            status="candidate",
                            quotes=tuple(
                                QuoteDraft(chunk_id=i, quote=evidence.chunks[i].retrieval_text)
                                for i in p["eligible_quote_chunk_ids"]
                            ),
                            reason_code=None,
                        )
                        for p in body["parts"]
                    )
                )
            )

        retriever = FakeRetriever(
            lambda i, q: (main.chunk_id if q.scope.owner_id == "a" else other.chunk_id,)
        )
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            chat = RecordingChat(providers.chat)
            app = create_app(
                config, offline_chat_service=compose(config, evidence, authority, chat, retriever)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                responses = await asyncio.gather(
                    *(client.post("/api/v1/chat", json={"query": q}) for q in requests)
                )
        assert len(planned) == 2 and len(chat.calls) == 4 and len(retriever.calls) == 2
        assert len({r.json()["request_id"] for r in responses}) == 2
        assert len({id(b) for _, b in retriever.calls}) == 2
        for response, (query, (owner, chunk)) in zip(responses, requests.items(), strict=True):
            assert response.status_code == 200
            body = response.json()
            assert body["request_id"] == response.headers["X-Request-ID"]
            assert body["parts"][0]["original_text"] == query
            assert body["parts"][0]["part_id"].startswith(UUID(body["request_id"]).hex)
            assert body["parts"][0]["quotes"][0]["chunk_id"] == chunk.chunk_id
            assert body["parts"][0]["quotes"][0]["literal_owner_id"] == owner
        for _, budget in retriever.calls:
            assert sum(b is budget for _, b in chat.calls) == 2

    asyncio.run(run())


def test_injected_provider_lifetime_remains_caller_owned_and_startup_does_not_dispatch():
    config, evidence, authority, handler, retriever, _, seen, *_ = setup()

    class TrackedTransport(httpx.MockTransport):
        closes = 0

        async def aclose(self):
            self.closes += 1
            await super().aclose()

    transport = TrackedTransport(handler)
    providers = OpenRouterProviders(config, transport=transport)
    try:
        app = create_app(
            config,
            offline_chat_service=compose(config, evidence, authority, providers.chat, retriever),
        )
        with TestClient(app) as client:
            assert client.get("/health/live").status_code == 200
            assert client.get("/openapi.json").status_code == 200
        assert not seen and not retriever.calls and transport.closes == 0
    finally:
        asyncio.run(providers.aclose())
    assert transport.closes == 1


def test_http_timeout_cancels_inflight_planning_without_retrieval_or_retry(monkeypatch):
    async def run():
        config, evidence, authority, _, retriever, payload, *_ = setup(
            config=synthetic_settings(request_timeout_seconds=5, provider_timeout_seconds=5)
        )
        timeouts = []
        attempts = []
        cancelled = asyncio.Event()

        def record_timeout(delay):
            value = asyncio.timeout(delay)
            timeouts.append(value)
            return value

        monkeypatch.setattr(middleware_module, "asyncio", SimpleNamespace(timeout=record_timeout))

        async def handler(received):
            attempts.append(1)
            assert len(timeouts) == 1
            timeouts[0].reschedule(asyncio.get_running_loop().time())
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            app = create_app(
                config,
                offline_chat_service=compose(
                    config, evidence, authority, providers.chat, retriever
                ),
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/chat", json=payload)
        assert response.status_code == 504 and response.json()["error"]["code"] == "request_timeout"
        assert cancelled.is_set() and timeouts[0].expired() and attempts == [1]
        assert not retriever.calls

    asyncio.run(run())


def test_offline_http_body_limit_preserves_cors_and_blocks_before_dispatch():
    config, evidence, authority, handler, retriever, payload, seen, *_ = setup(
        config=synthetic_settings(max_request_body_bytes=64)
    )
    providers = OpenRouterProviders(config, transport=httpx.MockTransport(handler))
    try:
        app = create_app(
            config,
            offline_chat_service=compose(config, evidence, authority, providers.chat, retriever),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/chat", json=payload, headers={"Origin": "https://telescopecenter.com"}
            )
        assert response.status_code == 413
        assert response.headers["Access-Control-Allow-Origin"] == "https://telescopecenter.com"
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
        assert not seen and not retriever.calls
    finally:
        asyncio.run(providers.aclose())
