"""Trusted profile selection through real HTTP/graph/adapter; synthetic evidence only."""

import asyncio
import json

import httpx2 as httpx
import pytest
from test_anchored_workflow import wire
from test_hours_graph import NOW, fixtures, hours_part, inputs, quote
from test_offline_service import RecordingChat
from test_offline_workflow import FakeRetriever, SyntheticCounter

from telescope_rag.api.hours_service import HoursChatService
from telescope_rag.api.main import create_app
from telescope_rag.core.settings import Settings
from telescope_rag.graph.hours_contract import ContractHoursPlannerReply
from telescope_rag.graph.hours_inputs import HoursPlannerReply
from telescope_rag.knowledge.hours import hours_plan_digest
from telescope_rag.providers.openrouter import OpenRouterProviders

OPENING = "When does the center open?"
VERSIONS = {
    "v12": "offline-rag-planner-hours-v12",
    "identity_links_v13": "offline-rag-planner-hours-identity-context-v13",
    "contracts_v14": "offline-rag-planner-hours-contract-v14",
}


def configuration():
    return Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")


def service_for(chat, profile=None, *, config=None):
    evidence, authority, plan, _ = fixtures()
    retriever = FakeRetriever(lambda i, q: ())
    service = HoursChatService(
        settings=config or configuration(),
        chat=chat,
        retriever=retriever,
        catalog=evidence,
        counter=SyntheticCounter(),
        directory_authority=authority,
        hours_plan=plan,
        expected_hours_plan_digest=hours_plan_digest(plan),
        token_basis="synthetic_test",
        clock=lambda: NOW,
        **({"hours_profile": profile} if profile is not None else {}),
    )
    return service, retriever


def public_weekly(service, text=OPENING):
    return HoursPlannerReply(
        language="en",
        parts=(hours_part(text, inputs(service._workflow)),),
    )


@pytest.mark.parametrize("profile", [None, "v12", "identity_links_v13", "contracts_v14"])
def test_trusted_profile_reaches_http_weekly_answer_with_its_own_wire(profile):
    async def run():
        config, seen = configuration(), []

        def handler(request):
            payload = json.loads(request.read())
            seen.append(payload)
            return wire(public_weekly(service))

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            chat = RecordingChat(providers.chat)
            service, retriever = service_for(chat, profile, config=config)
            app = create_app(config, offline_chat_service=service, offline_response_format="hours")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/chat", json={"query": OPENING})
                ready = await client.get("/health/ready")
                schema = (await client.get("/openapi.json")).json()
        assert response.status_code == 200 and ready.status_code == 503
        reply = response.json()
        assert reply["request_id"] == response.headers["X-Request-ID"]
        question = reply["questions"][0]
        assert question["question"] == OPENING
        assert question["hours"]["status"] == "schedule_available"
        assert "09:00" in question["answer"] and "Friday: 14:00" in question["answer"]
        assert "midnight at the end of the day" in question["answer"]
        assert len(reply["citations"]) == 2
        assert {c["source_language"] for c in reply["citations"]} == {"en", "ar"}
        assert all(c["question_id"] == question["id"] for c in reply["citations"])
        assert reply["offline_only"] and not reply["semantic_grounding_verified"]
        assert not reply["luna_compatibility_verified"] and not retriever.calls
        assert len(seen) == len(chat.calls) == 1
        active = profile or "v12"
        assert chat.calls[0][0] is (
            ContractHoursPlannerReply if active == "contracts_v14" else HoursPlannerReply
        )
        body = json.loads(seen[0]["messages"][-1]["content"])
        assert body["prompt_version"] == VERSIONS[active]
        assert body["original_query"] == OPENING
        assert seen[0]["max_completion_tokens"] == 1000
        assert set(schema["components"]["schemas"]["ChatRequest"]["properties"]) == {
            "query",
            "language",
            "history",
        }

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["clock", "hours_search", "doctor_scope"])
def test_v14_http_rejects_invalid_plan_once_without_repair_or_scope_fallback(failure):
    async def run():
        config, seen = configuration(), []
        text = "the center 2026-10-16 at 12:00 AM"

        def handler(request):
            seen.append(json.loads(request.read()))
            workflow = service._workflow
            supplied = inputs(workflow, subject_text="the center")
            proposed = hours_part(text, supplied).model_dump(mode="json")
            if failure == "clock":
                proposed["hours"].update(
                    intent="local",
                    date_value="2026-10-16",
                    hour=0,
                    minute=0,
                    clock_basis="am",
                    date_quote=quote("2026-10-16").model_dump(mode="json"),
                    time_quote=quote("12:00 AM").model_dump(mode="json"),
                )
            elif failure == "hours_search":
                proposed["retrieval_query"] = text
            else:
                doctor = next(
                    h for h, s in workflow.hours_bindings.subjects.items() if s.kind == "doctor"
                )
                contact = next(h for h, d in workflow._bindings.documents.items() if d == "contact")
                proposed["hours"]["subject_handle"] = doctor
                proposed["document_handles"] = [contact]
            return httpx.Response(
                200,
                json={
                    "model": "openai/gpt-6-luna",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"language": "en", "parts": [proposed]}),
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 12},
                },
            )

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            chat = RecordingChat(providers.chat)
            service, retriever = service_for(chat, "contracts_v14", config=config)
            app = create_app(config, offline_chat_service=service, offline_response_format="hours")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/chat", json={"query": text})
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "offline_draft_failed"
        assert text not in response.text and not retriever.calls
        assert len(seen) == len(chat.calls) == 1

    asyncio.run(run())


class ForbiddenChat:
    async def complete(self, *args, **kwargs):
        raise AssertionError("this_request_must_not_dispatch")


@pytest.mark.parametrize("field", ["hours_profile", "planner_profile"])
def test_public_request_cannot_select_the_trusted_profile(field):
    async def run():
        config = configuration()
        service, retriever = service_for(ForbiddenChat(), "contracts_v14", config=config)
        app = create_app(config, offline_chat_service=service, offline_response_format="hours")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/chat", json={"query": OPENING, field: "v12"})
        assert response.status_code == 422 and not retriever.calls
        assert response.json()["error"]["code"] == "invalid_request"
        assert OPENING not in response.text

    asyncio.run(run())


def test_unknown_trusted_profile_fails_before_dispatch():
    with pytest.raises(ValueError, match="hours_profile_invalid"):
        service_for(ForbiddenChat(), "unapproved-profile")


@pytest.mark.parametrize("profile", ["v12", "contracts_v14"])
def test_explicit_profile_keeps_production_composition_and_default_api_closed(profile):
    config = configuration()
    service, _ = service_for(ForbiddenChat(), profile, config=config)
    production = config.model_copy(update={"app_env": "production"})
    with pytest.raises(ValueError, match="offline_chat_configuration_mismatch"):
        create_app(production, offline_chat_service=service, offline_response_format="hours")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_app(config)), base_url="http://test"
        ) as client:
            assert (await client.post("/api/v1/chat", json={"query": OPENING})).status_code == 503
            assert (await client.get("/health/ready")).status_code == 503

    asyncio.run(run())


def test_concurrent_services_keep_profile_and_request_budget_isolated():
    async def run():
        config, seen = configuration(), []
        services = {}

        def handler(request):
            body = json.loads(json.loads(request.read())["messages"][-1]["content"])
            profile = next(p for p in services if VERSIONS[p] == body["prompt_version"])
            seen.append(profile)
            return wire(public_weekly(services[profile]))

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            chat = RecordingChat(providers.chat)
            clients = []
            for profile in ("v12", "contracts_v14"):
                service, _ = service_for(chat, profile, config=config)
                services[profile] = service
                app = create_app(
                    config, offline_chat_service=service, offline_response_format="hours"
                )
                clients.append(
                    httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")
                )
            try:
                responses = await asyncio.gather(
                    *(client.post("/api/v1/chat", json={"query": OPENING}) for client in clients)
                )
            finally:
                for client in clients:
                    await client.aclose()
        assert all(r.status_code == 200 for r in responses)
        assert len({r.json()["request_id"] for r in responses}) == 2
        assert set(seen) == {"v12", "contracts_v14"} and len(seen) == 2
        assert chat.calls[0][1] is not chat.calls[1][1]
        assert {call[0] for call in chat.calls} == {HoursPlannerReply, ContractHoursPlannerReply}

    asyncio.run(run())
