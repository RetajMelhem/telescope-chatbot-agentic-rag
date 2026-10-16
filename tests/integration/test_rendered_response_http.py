"""Opt-in rendered HTTP responses with actual graph/adapters and mocked services."""

import asyncio
import json
import logging
from uuid import UUID

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from test_offline_service import TEXTS, RecordingChat, compose, setup

from telescope_rag.api import offline_service as service_module
from telescope_rag.api.main import create_app
from telescope_rag.core.logging import SafeJsonFormatter
from telescope_rag.providers.openrouter import OpenRouterProviders


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize(
    "mode",
    [
        "public",
        "mixed",
        "missing",
        "history",
        "excluded",
        "clarification",
        "wrong_owner",
        "provider_failure",
        "missing_usage",
    ],
)
def test_rendered_http_preserves_every_question_and_unverified_source_claim(text, mode):
    async def run():
        config, evidence, authority, handler, retriever, payload, seen, main, other, targets = (
            setup(text, mode)
        )
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            chat = RecordingChat(providers.chat)
            app = create_app(
                config,
                offline_chat_service=compose(config, evidence, authority, chat, retriever),
                offline_response_format="rendered",
            )
            assert not seen and not retriever.calls
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/chat", json=payload, headers={"X-Request-ID": "not-trusted"}
                )
                assert (await client.get("/health/ready")).status_code == 503
                assert (await client.get("/health/live")).status_code == 200
        body = response.json()
        assert body["request_id"] == response.headers["X-Request-ID"] != "not-trusted"
        identifier = UUID(body["request_id"])
        if mode in {"wrong_owner", "provider_failure"}:
            assert response.status_code == 502 and body["error"]["code"] == "offline_draft_failed"
            assert "SYNTHETIC-SECRET-ERROR" not in response.text
            return
        assert response.status_code == 200, response.text
        assert body["schema_version"] == "offline-response-v1"
        assert body["answer_format"] == "plain_text"
        assert body["language"] == text[0]
        assert body["offline_only"] is True
        assert body["semantic_grounding_verified"] is body["luna_compatibility_verified"] is False
        assert [q["question"] for q in body["questions"]] == targets
        assert all(q["id"].startswith(identifier.hex) for q in body["questions"])
        assert (
            not {"usage", "plan", "history", "evidence", "source_manifest", "parts"} & body.keys()
        )
        for q in body["questions"]:
            assert q["question"] in body["answer"] and q["answer"] in body["answer"]
            matching = [c for c in body["citations"] if c["question_id"] == q["id"]]
            assert q["citation_ids"] == [c["id"] for c in matching]
            if q["status"] == "candidate":
                assert q["reason_code"] is None and matching
            else:
                assert q["reason_code"] is not None and not matching
        assert body["unresolved_questions"] == [
            q["id"] for q in body["questions"] if q["status"] != "candidate"
        ]
        if mode in {"excluded", "clarification", "missing"}:
            assert not body["citations"] and body["knowledge"] is None
            assert len(chat.calls) == 1
            assert (
                body["status"]
                == {
                    "excluded": "out_of_scope",
                    "clarification": "clarification_required",
                    "missing": "not_found",
                }[mode]
            )
        else:
            assert body["status"] == "draft_ready" and len(chat.calls) == 2
            c = body["citations"][0]
            assert c["quote"] == main.retrieval_text and main.retrieval_text in body["answer"]
            assert c["url"] == main.canonical_url and c["literal_owner_id"] == "a"
            assert c["literal_owner_name"] == main.doctor_name
            assert c["title"] == main.page_title and c["section"] == list(main.section_path)
            assert c["source_language"] == main.language and c["source_issue_codes"] == []
            assert all(c["chunk_id"] != other.chunk_id for c in body["citations"])
            assert body["knowledge"]["prepared_digest"] == evidence.prepared_digest
            if mode == "mixed":
                assert [q["status"] for q in body["questions"]] == [
                    "candidate",
                    "excluded",
                    "clarification_required",
                    "unknown",
                ]
                assert body["questions"][-1]["reason_code"] == "context_only"
            if mode == "history":
                assert payload["history"][0]["content"] in retriever.calls[0][0][0].text
        if retriever.calls:
            assert all(budget is retriever.calls[0][1] for _, budget in chat.calls)
        assert (
            "Source excerpt:" in body["answer"] if text[0] == "en" and body["citations"] else True
        )
        if text[0] != "en":
            assert "مسودة" in body["review_notice"]

    asyncio.run(run())


def test_rendered_openapi_is_closed_and_cannot_advertise_approved_answers_or_enable_defaults():
    config, evidence, authority, handler, retriever, payload, seen, *_ = setup()
    providers = OpenRouterProviders(config, transport=httpx.MockTransport(handler))
    try:
        service = compose(config, evidence, authority, providers.chat, retriever)
        app = create_app(config, offline_chat_service=service, offline_response_format="rendered")
        with TestClient(app) as client:
            schema = client.get("/openapi.json").json()
        wire = schema["components"]["schemas"]["OfflineChatResponse"]
        assert wire["additionalProperties"] is False
        fields = wire["properties"]
        assert "answered" not in fields["status"]["enum"]
        assert fields["offline_only"]["const"] is True
        assert fields["semantic_grounding_verified"]["const"] is False
        assert fields["answer_format"]["const"] == "plain_text"
        assert "synthetic-only" not in json.dumps(schema)
        with TestClient(create_app(config)) as client:
            default = client.get("/openapi.json").json()
            assert client.post("/api/v1/chat", json=payload).status_code == 503
        assert "200" not in default["paths"]["/api/v1/chat"]["post"]["responses"]
        with TestClient(create_app(config, offline_chat_service=service)) as client:
            old = client.get("/openapi.json").json()
        assert "WorkflowResult" in old["components"]["schemas"]
        assert "OfflineChatResponse" not in old["components"]["schemas"]
        assert not seen and not retriever.calls
    finally:
        asyncio.run(providers.aclose())


@pytest.mark.parametrize(
    "change", ["no_service", "invalid_format", "production", "request_override"]
)
def test_response_selection_requires_explicit_trusted_nonproduction_construction(change):
    config, evidence, authority, handler, retriever, payload, seen, *_ = setup()
    providers = OpenRouterProviders(config, transport=httpx.MockTransport(handler))
    try:
        service = compose(config, evidence, authority, providers.chat, retriever)
        if change == "no_service":
            with pytest.raises(ValueError, match="offline_response_configuration_invalid"):
                create_app(config, offline_response_format="rendered")
        elif change == "invalid_format":
            with pytest.raises(ValueError, match="offline_response_configuration_invalid"):
                create_app(
                    config, offline_chat_service=service, offline_response_format="unapproved"
                )
        elif change == "production":
            with pytest.raises(ValueError, match="offline_chat_configuration_mismatch"):
                create_app(
                    config.model_copy(update={"app_env": "production"}),
                    offline_chat_service=service,
                    offline_response_format="rendered",
                )
        else:
            app = create_app(
                config, offline_chat_service=service, offline_response_format="rendered"
            )
            with TestClient(app) as client:
                assert (
                    client.post(
                        "/api/v1/chat", json={**payload, "offline_response_format": "rendered"}
                    ).status_code
                    == 422
                )
        assert not seen and not retriever.calls
    finally:
        asyncio.run(providers.aclose())


def test_projection_failure_is_sanitized_without_extra_calls_or_sensitive_logs(monkeypatch, caplog):
    def reject(*args, **kwargs):
        raise ValueError("SYNTHETIC-PROJECTION-SECRET")

    monkeypatch.setattr(service_module, "project_response", reject)
    config, evidence, authority, handler, retriever, payload, seen, main, *_ = setup()
    providers = OpenRouterProviders(config, transport=httpx.MockTransport(handler))
    try:
        app = create_app(
            config,
            offline_chat_service=compose(config, evidence, authority, providers.chat, retriever),
            offline_response_format="rendered",
        )
        logging.getLogger("telescope_rag").addHandler(caplog.handler)
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", json=payload)
        assert (
            response.status_code == 502
            and response.json()["error"]["code"] == "offline_response_failed"
        )
        assert len(seen) == 2 and len(retriever.calls) == 1
        logs = "\n".join(
            SafeJsonFormatter().format(r) for r in caplog.records if r.name == "telescope_rag"
        )
        assert logs
        for sensitive in (
            "SYNTHETIC-PROJECTION-SECRET",
            "synthetic-only",
            payload["query"],
            main.retrieval_text,
        ):
            assert sensitive not in logs and sensitive not in response.text
    finally:
        logging.getLogger("telescope_rag").removeHandler(caplog.handler)
        asyncio.run(providers.aclose())


def test_rendered_response_and_draft_share_identical_provider_wires_for_the_same_request():
    async def run():
        captures = []
        for response_format in ("draft", "rendered"):
            config, evidence, authority, handler, retriever, payload, seen, *_ = setup(mode="mixed")
            async with OpenRouterProviders(
                config, transport=httpx.MockTransport(handler)
            ) as providers:
                service = compose(config, evidence, authority, providers.chat, retriever)
                # The same application-issued UUID controls literal part IDs;
                # HTTP middleware still issues fresh UUIDs in the other tests.
                from telescope_rag.api.schemas import ChatRequest

                request = ChatRequest.model_validate(payload)
                if response_format == "draft":
                    await service.draft(request, request_id=UUID(int=67))
                else:
                    await service.respond(request, request_id=UUID(int=67))
                captures.append(seen)
        assert captures[0] == captures[1] and len(captures[0]) == 2

    asyncio.run(run())


def test_concurrent_rendered_requests_keep_request_ids_citation_links_and_budgets_separate():
    async def run():
        config, evidence, authority, handler, retriever, payload, _, *_ = setup()
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            chat = RecordingChat(providers.chat)
            service = compose(config, evidence, authority, chat, retriever)
            app = create_app(
                config, offline_chat_service=service, offline_response_format="rendered"
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                responses = await asyncio.gather(
                    *(client.post("/api/v1/chat", json=payload) for _ in range(2))
                )
        assert all(r.status_code == 200 for r in responses)
        bodies = [r.json() for r in responses]
        assert bodies[0]["request_id"] != bodies[1]["request_id"]
        assert len({id(b) for _, b in chat.calls}) == 2
        assert len(chat.calls) == 4 and len(retriever.calls) == 2
        for body in bodies:
            q, c = body["questions"][0], body["citations"][0]
            assert q["id"].startswith(UUID(body["request_id"]).hex)
            assert c["question_id"] == q["id"] and q["citation_ids"] == [c["id"]]
        assert bodies[0]["questions"][0]["id"] != bodies[1]["questions"][0]["id"]

    asyncio.run(run())


def test_cancelled_rendered_request_joins_provider_without_projection_retry_or_search(monkeypatch):
    async def run():
        config, evidence, authority, _, retriever, payload, _, *_ = setup()
        entered, cancelled = asyncio.Event(), asyncio.Event()
        attempts = []

        async def blocked(request):
            attempts.append(request.url.path)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        def forbidden_projection(*args, **kwargs):
            pytest.fail("Projection cannot run before a graph result exists")

        monkeypatch.setattr(service_module, "project_response", forbidden_projection)
        async with OpenRouterProviders(config, transport=httpx.MockTransport(blocked)) as providers:
            app = create_app(
                config,
                offline_chat_service=compose(
                    config, evidence, authority, providers.chat, retriever
                ),
                offline_response_format="rendered",
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                task = asyncio.create_task(client.post("/api/v1/chat", json=payload))
                async with asyncio.timeout(5):
                    await entered.wait()
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                    await cancelled.wait()
        assert attempts == ["/api/v1/chat/completions"] and not retriever.calls

    asyncio.run(run())
