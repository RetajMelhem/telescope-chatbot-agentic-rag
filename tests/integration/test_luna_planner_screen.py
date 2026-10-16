"""Development-only screen contracts with synthetic inputs and forbidden live I/O."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx2 as httpx
import pytest
from test_offline_workflow import catalog, single_plan, source

from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.providers.openrouter import OpenRouterProviders

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts import run_luna_planner_screen as screen


def preparation():
    bindings = SourceBindings(catalog(source(1)))
    cases = [
        SimpleNamespace(
            case_id=identity,
            split="development",
            request=WorkflowRequest(query="Synthetic question; retain its negation: do not book."),
        )
        for identity in screen.DEVELOPMENT_IDS
    ]
    # A reserved case must never enter the exported inputs, even with tempting gold.
    cases.append(SimpleNamespace(case_id="PL02-en", split="reserved_evaluation"))
    return bindings, screen.development_packets(cases, bindings)


def reply(request, *, usage=True, invalid_binding=False):
    payload = json.loads(request.read())
    body = json.loads(payload["messages"][-1]["content"])
    proposal = single_plan()(body).model_dump(mode="json")
    if invalid_binding:
        proposal["parts"][0]["document_handles"] = ["not-issued"]
    return httpx.Response(
        200,
        json={
            "model": "openai/gpt-6-luna",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(proposal),
                    },
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 12} if usage else None,
        },
    )


@pytest.mark.parametrize("usage", [True, False])
def test_exact_six_development_inputs_match_actual_adapter_and_have_no_gold(tmp_path, usage):
    bindings, packets = preparation()
    assert tuple(p["case_id"] for p in packets) == screen.DEVELOPMENT_IDS
    assert all(set(p) == {"case_id", "request", "payload", "payload_sha256"} for p in packets)
    config = screen.screen_settings()
    seen = []

    def handler(request):
        actual = json.loads(request.read())
        assert actual == packets[len(seen)]["payload"]
        assert actual["response_format"]["json_schema"]["name"] == "PlannerReply"
        assert actual["max_completion_tokens"] == 1000
        seen.append(actual)
        return reply(request, usage=usage)

    async def run():
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            return await screen.run_packets(packets, bindings, config, p.chat, tmp_path)

    summary = asyncio.run(run())
    assert len(seen) == summary["physical_attempts"] == summary["cases_attempted"] == 6
    assert summary["schema_valid"] == summary["literal_bindings_valid"] == 6
    assert not summary["semantic_review_completed"] and not summary["production_ready"]
    assert summary["embedding_calls"] == summary["qdrant_calls"] == 0
    assert summary["answer_generation_calls"] == summary["reserved_evaluation_requests"] == 0
    for packet in packets:
        saved = json.loads((tmp_path / f"{packet['case_id']}.json").read_bytes())
        assert saved["reported_input_tokens"] == (20 if usage else None)
        assert saved["receipts"][0]["input_reserved"] is None
        assert "synthetic-screen-preparation" not in json.dumps(saved)


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
def test_fatal_protocol_or_credit_failure_stops_without_retry(tmp_path, status):
    bindings, packets = preparation()
    config = screen.screen_settings()
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"error": "synthetic"})

    async def run():
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            return await screen.run_packets(packets, bindings, config, p.chat, tmp_path)

    summary = asyncio.run(run())
    assert summary["cases_attempted"] == summary["physical_attempts"] == len(seen) == 1
    assert summary["schema_valid"] == summary["literal_bindings_valid"] == 0


def test_schema_success_is_distinct_from_literal_or_semantic_acceptance(tmp_path):
    bindings, packets = preparation()
    config = screen.screen_settings()

    async def run():
        async with OpenRouterProviders(
            config, transport=httpx.MockTransport(lambda r: reply(r, invalid_binding=True))
        ) as p:
            return await screen.run_packets(packets, bindings, config, p.chat, tmp_path)

    summary = asyncio.run(run())
    assert summary["schema_valid"] == 6 and summary["literal_bindings_valid"] == 0
    assert {r["error_code"] for r in summary["case_results"]} == {
        "planner_unknown_or_duplicate_binding"
    }
    assert not summary["semantic_review_completed"]


@pytest.mark.parametrize("tamper", ["payload", "reserved_case"])
def test_input_tampering_stops_before_dispatch(tmp_path, tamper):
    bindings, packets = preparation()
    if tamper == "payload":
        packets[0]["request"]["query"] += " changed"
    else:
        packets[0]["case_id"] = "PL02-en"

    class Forbidden:
        async def complete(self, *args, **kwargs):
            raise AssertionError("No dispatch permitted")

    with pytest.raises(ValueError, match="screen_payload_changed|development_inventory_mismatch"):
        asyncio.run(
            screen.run_packets(packets, bindings, screen.screen_settings(), Forbidden(), tmp_path)
        )


def test_started_screen_cannot_dispatch_again(tmp_path, monkeypatch):
    bindings, packets = preparation()
    plan = {"packets": packets}
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (tmp_path / "started.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(screen, "build_plan", lambda root: (plan, bindings))
    monkeypatch.setattr(screen.subprocess, "check_output", lambda *a, **k: "")
    monkeypatch.setattr("sys.argv", ["screen", "--output", str(tmp_path), "--execute"])

    def forbidden():
        raise AssertionError("Must reject repeat before loading keys")

    monkeypatch.setattr(screen, "load_settings", forbidden)
    with pytest.raises(FileExistsError):
        asyncio.run(screen.main())
