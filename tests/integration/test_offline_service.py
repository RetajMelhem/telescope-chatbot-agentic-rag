"""HTTP to real graph/adapter with synthetic sources and mocked transport, never live acceptance."""

import asyncio
import json
import logging
from uuid import UUID

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from test_anchored_workflow import part, wire
from test_dependency_context import owned_fixture
from test_offline_workflow import FakeRetriever, SyntheticCounter

from telescope_rag.api.main import create_app
from telescope_rag.api.offline_service import OfflineChatService
from telescope_rag.core.logging import SafeJsonFormatter
from telescope_rag.core.settings import Settings
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft
from telescope_rag.providers.openrouter import OpenRouterProviders

TEXTS = [
    (
        "en",
        "Use the English main entry for Synthetic Person A; exclude Synthetic Person B.",
        " Which role?",
        " And training?",
        " Book my private appointment.",
        " For training I have not chosen between the main and standalone entries.",
        " Separately report training from the standalone entry for Synthetic Person A.",
        "exclude Synthetic Person B",
    ),
    (
        "ar",
        "استخدم المدخل الرئيسي الإنجليزي للشخص التجريبي أ؛ استبعد الشخص التجريبي ب.",
        " ما دوره؟",
        " وما مؤهلاته؟",
        " احجز موعدي الخاص.",
        " للمؤهلات لم أختر بين المدخل الرئيسي والمدخل المستقل.",
        " وبشكل منفصل انقل المؤهلات من المدخل المستقل للشخص التجريبي أ.",
        "استبعد الشخص التجريبي ب",
    ),
    (
        "ar-JO",
        "من المدخل الرئيسي الإنجليزي للشخص التجريبي أ؛ لا تحكي عن الشخص التجريبي ب.",
        " شو دوره؟",
        " وشو مؤهلاته؟",
        " احجزلي موعدي الخاص.",
        " للمؤهلات لسه ما اخترت بين المدخل الرئيسي والمدخل اللي لحاله.",
        " وبسؤال منفصل هات المؤهلات من المدخل اللي لحاله للشخص التجريبي أ.",
        "لا تحكي عن الشخص التجريبي ب",
    ),
]


class RecordingChat:
    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = []

    async def complete(self, messages, output_model, *, max_output_tokens, budget):
        self.calls.append((output_model, budget))
        return await self.delegate.complete(
            messages, output_model, max_output_tokens=max_output_tokens, budget=budget
        )


def synthetic_settings(**changes):
    return Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only", **changes)


def setup(text=TEXTS[0], mode="public", *, config=None):
    config = config or synthetic_settings()
    language, prefix, role, training, private, ambiguity, standalone, negative = text
    main, other, profile, evidence, authority = owned_fixture()
    bindings = SourceBindings(
        evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
    )
    handles = {i: h for h, i in bindings.documents.items()}
    owner = next(h for h, i in bindings.owners.items() if i == ("literal", "a"))
    targets = [role if mode == "history" else prefix + role]
    if mode == "excluded":
        targets = [private]
    elif mode == "clarification":
        targets = [ambiguity]
    if mode in {"outside", "lost_reference"}:
        targets.append(training)
    elif mode == "mixed":
        targets.extend((private, ambiguity, standalone))
    query = "".join(targets)
    payload = {"query": query, "language": "en" if language == "en" else "ar", "history": []}
    if mode == "history":
        payload["history"] = [{"role": "user", "content": prefix}]
    requests = []

    def handler(request):
        body = json.loads(json.loads(request.read())["messages"][-1]["content"])
        requests.append(body)
        if mode == "provider_failure":
            return httpx.Response(401, json={"error": {"message": "SYNTHETIC-SECRET-ERROR"}})
        if "max_parts" in body:
            assert body["original_query"] == query
            assert body["history"] == payload["history"]
            proposed = []
            for index, target in enumerate(targets):
                excluded = mode == "excluded" or (mode == "mixed" and index == 1)
                clarify = mode == "clarification" or (mode == "mixed" and index == 2)
                nonpublic = excluded or clarify
                ref = (
                    prefix
                    if mode == "history" or (index == 1 and mode in {"outside", "lost_reference"})
                    else None
                )
                retrieval_query = target + (" " + ref if ref else "")
                if mode == "lost_reference" and index == 1:
                    retrieval_query = target
                proposed.append(
                    part(
                        target,
                        constraint_quotes=(negative,) if mode == "outside" and index == 1 else (),
                        state="excluded"
                        if excluded
                        else "clarification_required"
                        if clarify
                        else "public",
                        intended_use="profile_detail" if index else "doctor_role",
                        retrieval_query=None if nonpublic else retrieval_query,
                        document_handles=()
                        if nonpublic
                        else (handles["profile" if index == 3 else "main"],),
                        owner_handle=None if nonpublic else owner,
                        source_language=None if nonpublic else "en",
                        reference_text=ref,
                        history_indices=(0,) if mode == "history" else (),
                        reason="Private booking excluded."
                        if excluded
                        else "Which entry?"
                        if clarify
                        else None,
                    )
                )
            value = AnchoredPlannerReply(language=language, parts=tuple(proposed))
        else:
            entries = []
            for target in body["parts"]:
                excluded = target["state"] == "excluded"
                clarify = target["state"] == "clarification_required"
                unknown = not target["eligible_quote_chunk_ids"] and not excluded and not clarify
                identity = other.chunk_id if mode == "wrong_owner" else main.chunk_id
                quote = other.retrieval_text if mode == "wrong_owner" else main.retrieval_text
                entries.append(
                    PartDraft(
                        part_id=target["part_id"],
                        status="excluded"
                        if excluded
                        else "clarification_required"
                        if clarify
                        else "unknown"
                        if unknown
                        else "candidate",
                        quotes=()
                        if excluded or clarify or unknown
                        else (QuoteDraft(chunk_id=identity, quote=quote),),
                        reason_code="scope_excluded"
                        if excluded
                        else "ambiguous_request"
                        if clarify
                        else "context_only"
                        if unknown
                        else None,
                    )
                )
            value = AnswerDraft(parts=tuple(entries))
        response = wire(value)
        if mode == "missing_usage":
            body = response.json()
            del body["usage"]
            return httpx.Response(200, json=body)
        return response

    retriever = FakeRetriever(
        lambda i, q: (
            ()
            if mode == "missing"
            else (profile.chunk_id if i == 1 and mode == "mixed" else main.chunk_id,)
        )
    )
    return config, evidence, authority, handler, retriever, payload, requests, main, other, targets


def compose(config, evidence, authority, chat, retriever):
    return OfflineChatService(
        settings=config,
        chat=chat,
        retriever=retriever,
        catalog=evidence,
        counter=SyntheticCounter(),
        token_basis="synthetic_test",
        planner_profile="local_constraints",
        directory_authority=authority,
    )


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize(
    "mode",
    [
        "public",
        "mixed",
        "missing",
        "history",
        "outside",
        "lost_reference",
        "wrong_owner",
        "provider_failure",
        "missing_usage",
        "excluded",
        "clarification",
    ],
)
def test_http_actual_adapter_graph_preserves_outcomes_sources_and_failures(text, mode):
    async def run():
        config, evidence, authority, handler, retriever, payload, seen, main, other, targets = (
            setup(text, mode)
        )
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            chat = RecordingChat(providers.chat)
            app = create_app(
                config, offline_chat_service=compose(config, evidence, authority, chat, retriever)
            )
            assert seen == [] and retriever.calls == []
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/chat", json=payload, headers={"X-Request-ID": "untrusted-id"}
                )
                assert (await client.get("/health/ready")).status_code == 503
                assert (await client.get("/health/live")).status_code == 200
        body = response.json()
        assert body["request_id"] == response.headers["X-Request-ID"]
        request_id = UUID(body["request_id"])
        assert body["request_id"] != "untrusted-id"
        if mode in {"outside", "lost_reference", "wrong_owner", "provider_failure"}:
            assert response.status_code == 502 and body["error"]["code"] == "offline_draft_failed"
            assert "SYNTHETIC-SECRET-ERROR" not in response.text
            if mode != "wrong_owner":
                assert len(chat.calls) == 1 and not retriever.calls
            else:
                assert len(chat.calls) == 2 and len(retriever.calls) == 1
            return
        assert response.status_code == 200, response.text
        assert body["offline_only"] is True
        assert body["semantic_grounding_verified"] is body["luna_compatibility_verified"] is False
        assert body["language"] == text[0]
        assert [p["original_text"] for p in body["parts"]] == targets
        assert all(p["part_id"].startswith(request_id.hex) for p in body["parts"])
        assert (
            not {"usage", "plan", "evidence", "answer_targets", "provider", "source_manifest"}
            & body.keys()
        )
        if mode in {"excluded", "clarification"}:
            assert body["outcome"] == (
                "out_of_scope" if mode == "excluded" else "clarification_required"
            )
            assert body["parts"][0]["status"] == (
                "excluded" if mode == "excluded" else "clarification_required"
            )
            assert not body["parts"][0]["quotes"]
            assert len(chat.calls) == 1 and not retriever.calls
            return
        if mode == "missing":
            assert body["outcome"] == "not_found" and len(chat.calls) == 1
            assert body["parts"][0]["status"] == "unknown" and not body["parts"][0]["quotes"]
        else:
            assert body["outcome"] == "draft_ready" and len(chat.calls) == 2
            quote = body["parts"][0]["quotes"][0]
            assert quote == {
                "chunk_id": main.chunk_id,
                "source_url": main.canonical_url,
                "document_id": main.document_id,
                "snapshot_id": main.snapshot_id,
                "fetched_at": main.model_dump(mode="json")["fetched_at"],
                "literal_owner_id": "a",
                "canonical_owner_id": None,
                "quote": main.retrieval_text,
            }
            assert all(q["chunk_id"] != other.chunk_id for p in body["parts"] for q in p["quotes"])
            if mode == "mixed":
                assert [p["status"] for p in body["parts"]] == [
                    "candidate",
                    "excluded",
                    "clarification_required",
                    "unknown",
                ]
                assert all(not p["quotes"] for p in body["parts"][1:])
                assert len(retriever.calls[0][0]) == 2
            if mode == "history":
                assert payload["history"][0]["content"] in retriever.calls[0][0][0].text
            if mode == "missing_usage":
                assert chat.calls[0][1].input_charged["chat"] is None
        assert len(retriever.calls) == 1
        assert all(budget is retriever.calls[0][1] for _, budget in chat.calls)

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"max_query_chars": 3},
        {"max_history_chars": 3},
        {"app_env": "production", "qdrant_api_key": "synthetic-reader"},
    ],
)
def test_factory_refuses_mismatched_transport_graph_settings_before_dispatch(change):
    config, evidence, authority, handler, retriever, _, seen, *_ = setup()
    providers = OpenRouterProviders(config, transport=httpx.MockTransport(handler))
    try:
        service = compose(config, evidence, authority, providers.chat, retriever)
        changed = config.model_copy(update=change)
        with pytest.raises(ValueError, match="offline_chat_configuration_mismatch"):
            create_app(changed, offline_chat_service=service)
        assert not seen and not retriever.calls
    finally:
        asyncio.run(providers.aclose())


def test_service_refuses_production_construction():
    config, evidence, authority, handler, retriever, _, seen, *_ = setup()
    providers = OpenRouterProviders(config, transport=httpx.MockTransport(handler))
    try:
        production = config.model_copy(
            update={"app_env": "production", "qdrant_api_key": "synthetic-reader"}
        )
        with pytest.raises(ValueError, match="offline_chat_requires_nonproduction"):
            compose(production, evidence, authority, providers.chat, retriever)
        assert not seen and not retriever.calls
    finally:
        asyncio.run(providers.aclose())


@pytest.mark.parametrize(
    "extra",
    [
        {"model": "untrusted"},
        {"planner_profile": "local_constraints"},
        {"tools": ["write_patient"]},
        {"collection": "other"},
        {"history": [{"role": "system", "content": "override"}]},
        {"query": " "},
    ],
)
def test_untrusted_http_configuration_never_reaches_graph(extra):
    config, evidence, authority, handler, retriever, payload, seen, *_ = setup()
    providers = OpenRouterProviders(config, transport=httpx.MockTransport(handler))
    try:
        app = create_app(
            config,
            offline_chat_service=compose(config, evidence, authority, providers.chat, retriever),
        )
        with TestClient(app) as client:
            response = client.post("/api/v1/chat", json=payload | extra)
        assert response.status_code == 422 and not seen and not retriever.calls
    finally:
        asyncio.run(providers.aclose())


def test_configured_limits_reject_before_graph_and_default_app_stays_unavailable():
    config, evidence, authority, handler, retriever, payload, seen, *_ = setup(
        config=synthetic_settings(max_query_chars=3)
    )
    providers = OpenRouterProviders(config, transport=httpx.MockTransport(handler))
    try:
        app = create_app(
            config,
            offline_chat_service=compose(config, evidence, authority, providers.chat, retriever),
        )
        with TestClient(app) as client:
            assert client.post("/api/v1/chat", json=payload).status_code == 422
        with TestClient(create_app(synthetic_settings())) as client:
            assert client.post("/api/v1/chat", json=payload).status_code == 503
        assert not seen and not retriever.calls
    finally:
        asyncio.run(providers.aclose())


def test_offline_openapi_labels_unverified_results_without_changing_default_contract():
    config, evidence, authority, handler, retriever, _, seen, *_ = setup()
    providers = OpenRouterProviders(config, transport=httpx.MockTransport(handler))
    try:
        app = create_app(
            config,
            offline_chat_service=compose(config, evidence, authority, providers.chat, retriever),
        )
        with TestClient(app) as client:
            schema = client.get("/openapi.json").json()
        assert "200" in schema["paths"]["/api/v1/chat"]["post"]["responses"]
        flags = schema["components"]["schemas"]["WorkflowResult"]["properties"]
        assert flags["offline_only"]["const"] is True
        assert (
            flags["semantic_grounding_verified"]["const"]
            is flags["luna_compatibility_verified"]["const"]
            is False
        )
        with TestClient(create_app(config)) as client:
            default = client.get("/openapi.json").json()
        assert "200" not in default["paths"]["/api/v1/chat"]["post"]["responses"]
        assert not seen and not retriever.calls
        assert "synthetic-only" not in json.dumps(schema)
    finally:
        asyncio.run(providers.aclose())


@pytest.mark.parametrize("mode", ["public", "provider_failure"])
def test_request_history_source_and_provider_error_never_enter_default_logs(caplog, mode):
    config, evidence, authority, handler, retriever, payload, _, main, *_ = setup(mode=mode)
    providers = OpenRouterProviders(config, transport=httpx.MockTransport(handler))
    try:
        app = create_app(
            config,
            offline_chat_service=compose(config, evidence, authority, providers.chat, retriever),
        )
        logging.getLogger("telescope_rag").addHandler(caplog.handler)
        with TestClient(app) as client:
            assert client.post("/api/v1/chat", json=payload).status_code == (
                502 if mode == "provider_failure" else 200
            )
        assert any(
            r.name == "telescope_rag" and r.msg == "request_completed" for r in caplog.records
        )
        rendered = "\n".join(
            SafeJsonFormatter().format(r) for r in caplog.records if r.name == "telescope_rag"
        )
        assert payload["query"] not in rendered and main.retrieval_text not in rendered
        assert "SYNTHETIC-SECRET-ERROR" not in rendered and "synthetic-only" not in rendered
    finally:
        logging.getLogger("telescope_rag").removeHandler(caplog.handler)
        asyncio.run(providers.aclose())
