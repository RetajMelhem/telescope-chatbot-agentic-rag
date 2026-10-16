"""Synthetic once-only dispatch checks; semantic judgments remain a separate review."""

import asyncio
import copy
import json

import httpx2 as httpx
import pytest
from test_luna_planner_screen import reply
from test_source_scope_profile import fixtures

from scripts import run_dependency_comparison as paired
from scripts.run_luna_planner_screen import payload_hash, planner_payload, screen_settings
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.graph.planning import planner_messages
from telescope_rag.providers.openrouter import OpenRouterProviders


def prepared():
    _, catalog, authority = fixtures()
    bindings = {
        a: SourceBindings(
            catalog,
            include_block_types=True,
            directory_authority=authority,
            purpose_contract=True,
        )
        for a in paired.ARMS
    }
    settings = screen_settings(profile="dependency_context", output_cap=4096)
    ids = ("synthetic-en", "synthetic-ar", "synthetic-ar-JO")
    packets = []
    for n, (identity, query) in enumerate(
        zip(
            ids,
            (
                "Report the synthetic wording only.",
                "انقل النص التجريبي فقط.",
                "انقل النص التجريبي بس.",
            ),
            strict=True,
        )
    ):
        request = WorkflowRequest(query=query)
        for arm in paired.ARMS if n % 2 == 0 else paired.ARMS[::-1]:
            payload = planner_payload(
                planner_messages(request, bindings[arm], max_parts=4, profile=paired.PROFILES[arm]),
                settings,
                profile=paired.PROFILES[arm],
                output_cap=4096,
            )
            packets.append(
                {
                    "case_id": identity,
                    "arm": arm,
                    "request": request.model_dump(mode="json"),
                    "payload": payload,
                    "payload_sha256": payload_hash(payload),
                }
            )
    return {"case_ids": ids, "packets": packets}, bindings, settings


@pytest.mark.parametrize("usage", [True, False])
def test_exact_adapter_wires_both_profiles_keep_anchors_targets_and_unknown_usage(tmp_path, usage):
    plan, bindings, settings = prepared()
    seen = []

    def handler(request):
        assert json.loads(request.read()) == plan["packets"][len(seen)]["payload"]
        seen.append(request)
        return reply(request, usage=usage)

    async def run():
        async with OpenRouterProviders(settings, transport=httpx.MockTransport(handler)) as p:
            return await paired.run_comparison(plan, bindings, settings, p.chat, tmp_path)

    summary = asyncio.run(run())
    assert summary["attempted"] == summary["physical_attempts"] == 6 == len(seen)
    assert summary["schema_valid"] == summary["literal_valid"] == 6
    assert not summary["semantic_review_completed"] and not summary["production_ready"]
    assert all(
        summary[k] == 0
        for k in (
            "embedding_calls",
            "qdrant_calls",
            "answer_generation_calls",
            "reserved_evaluation_requests",
        )
    )
    for packet in plan["packets"]:
        path = tmp_path / packet["arm"] / packet["case_id"] / f"{packet['case_id']}.json"
        row = json.loads(path.read_bytes())
        assert row["request_anchors"] and row["answer_targets"]
        assert row["reported_input_tokens"] == (20 if usage else None)
        assert row["semantic_review"] == "pending"


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
def test_fatal_http_response_stops_both_arms_without_retry(tmp_path, status):
    plan, bindings, settings = prepared()
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"error": "synthetic"})

    async def run():
        async with OpenRouterProviders(settings, transport=httpx.MockTransport(handler)) as p:
            return await paired.run_comparison(plan, bindings, settings, p.chat, tmp_path)

    summary = asyncio.run(run())
    assert summary["attempted"] == 1 == len(seen) and summary["stopped_fatal"]


def test_body_timeout_remains_unknown_and_is_not_retried(tmp_path):
    plan, bindings, settings = prepared()
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            raise httpx.ReadTimeout("synthetic ambiguous upstream completion")
        return reply(request)

    async def run():
        async with OpenRouterProviders(settings, transport=httpx.MockTransport(handler)) as p:
            return await paired.run_comparison(plan, bindings, settings, p.chat, tmp_path)

    summary = asyncio.run(run())
    assert len(seen) == 6 and summary["schema_valid"] == 5
    row = json.loads((tmp_path / "control/synthetic-en/synthetic-en.json").read_bytes())
    assert row["proposal"] is None and row["reported_input_tokens"] is None
    assert row["physical_attempts"] == 1 and row["error_code"] == "provider_timeout"


def test_new_profile_retains_distinct_empty_filter_error(tmp_path):
    plan, bindings, settings = prepared()

    def handler(request):
        response = reply(request)
        body = response.json()
        proposal = json.loads(body["choices"][0]["message"]["content"])
        proposal["parts"][0]["document_handles"] = ["d0001"]
        proposal["parts"][0]["source_language"] = "ar"
        body["choices"][0]["message"]["content"] = json.dumps(proposal)
        return httpx.Response(200, json=body)

    async def run():
        async with OpenRouterProviders(settings, transport=httpx.MockTransport(handler)) as p:
            return await paired.run_comparison(plan, bindings, settings, p.chat, tmp_path)

    summary = asyncio.run(run())
    assert summary["schema_valid"] == 6 and summary["literal_valid"] == 0
    row = json.loads((tmp_path / "dependency_context/synthetic-en/synthetic-en.json").read_bytes())
    assert row["error_code"] == "planner_source_filters_have_empty_intersection"


@pytest.mark.parametrize(
    "tamper",
    [
        "order",
        "request",
        "schema",
        "model",
        "system",
        "late",
        "hash",
        "gold",
        "missing",
        "duplicate",
    ],
)
def test_complete_list_tampering_rejects_before_first_dispatch(tmp_path, tamper):
    plan, bindings, settings = prepared()
    packet = plan["packets"][-1]
    if tamper == "order":
        plan["packets"].reverse()
    elif tamper == "request":
        packet["request"]["query"] = "tampered"
    elif tamper == "hash":
        packet["payload_sha256"] = "tampered"
    elif tamper == "gold":
        packet["gold"] = "must never enter wire"
    elif tamper == "missing":
        plan["packets"].pop()
    elif tamper == "duplicate":
        plan["case_ids"] = [*plan["case_ids"], plan["case_ids"][0]]
    else:
        if tamper == "schema":
            packet["payload"]["response_format"] = {}
        elif tamper == "model":
            packet["payload"]["model"] = "wrong-model"
        elif tamper == "system":
            packet["payload"]["messages"][0]["content"] += " tampered"
        else:
            body = json.loads(packet["payload"]["messages"][-1]["content"])
            body["source_manifest"]["invented"] = "tampered"
            packet["payload"]["messages"][-1]["content"] = json.dumps(body)
        packet["payload_sha256"] = payload_hash(packet["payload"])

    class Forbidden:
        async def complete(self, *args, **kwargs):
            raise AssertionError("Must reject complete list before first dispatch")

    with pytest.raises(ValueError, match="dependency_"):
        asyncio.run(paired.run_comparison(plan, bindings, settings, Forbidden(), tmp_path))
    assert not list(tmp_path.iterdir())


def test_60_pairs_alternate_arms_without_changing_any_payload(tmp_path):
    plan, _, _ = prepared()
    template = copy.deepcopy(plan["packets"][:2])
    ids = tuple(f"synthetic-{i}" for i in range(60))
    pairs = []
    for n, identity in enumerate(ids):
        for original in template if n % 2 == 0 else template[::-1]:
            item = copy.deepcopy(original)
            item["case_id"] = identity
            pairs.append(item)
    assert len(pairs) == len({(p["case_id"], p["arm"]) for p in pairs}) == 120
    assert [p["arm"] for p in pairs[:4]] == [
        "control",
        "dependency_context",
        "dependency_context",
        "control",
    ]


def test_existing_start_marker_blocks_reexecution_before_credentials(tmp_path, monkeypatch):
    plan, bindings, _ = prepared()
    normalized = json.loads(json.dumps(plan))
    (tmp_path / "plan.json").write_text(json.dumps(normalized), encoding="utf-8")
    (tmp_path / "started.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paired, "comparison_plan", lambda root: (plan, bindings))
    monkeypatch.setattr(paired.subprocess, "check_output", lambda *a, **k: "")
    monkeypatch.setattr("sys.argv", ["paired", "--output", str(tmp_path), "--execute"])

    def forbidden():
        raise AssertionError("Must not load credentials on replay")

    monkeypatch.setattr(paired, "load_settings", forbidden)
    with pytest.raises(FileExistsError):
        asyncio.run(paired.main())
