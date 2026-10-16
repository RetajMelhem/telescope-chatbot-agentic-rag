"""Synthetic paired-dispatch safety tests; no semantic scoring or real provider I/O."""

import asyncio
import copy
import json

import httpx2 as httpx
import pytest
from test_luna_planner_screen import preparation, reply

from scripts import run_metadata_comparison as paired
from scripts.run_luna_planner_screen import payload_hash, planner_payload, screen_settings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.graph.planning import planner_messages
from telescope_rag.providers.openrouter import OpenRouterProviders


def prepared():
    control, original = preparation("policy_targets")
    treatment, _ = preparation("policy_targets")
    # Explicit synthetic metadata injection; not a reviewed production authority.
    body = json.loads(treatment.manifest_json)
    body["synthetic_metadata"] = "synthetic provenance only, never clinic evidence"
    treatment.manifest_json = json.dumps(body)
    bindings = dict(zip(paired.ARMS, (control, treatment), strict=True))
    config = screen_settings(profile=paired.PROFILE, output_cap=4096)
    packets = []
    for i, packet in enumerate(original):
        for arm in paired.ARMS if i % 2 == 0 else paired.ARMS[::-1]:
            request = WorkflowRequest.model_validate_json(json.dumps(packet["request"]))
            payload = planner_payload(
                planner_messages(request, bindings[arm], max_parts=4, profile=paired.PROFILE),
                config,
                profile=paired.PROFILE,
                output_cap=4096,
            )
            packets.append(
                {
                    "case_id": packet["case_id"],
                    "arm": arm,
                    "request": packet["request"],
                    "payload": payload,
                    "payload_sha256": payload_hash(payload),
                }
            )
    return {"case_ids": [p["case_id"] for p in original], "packets": packets}, bindings, config


def test_paired_adapter_exact_wire_unique_results_and_no_semantic_acceptance(tmp_path):
    plan, bindings, config = prepared()
    seen = []

    def handler(request):
        assert json.loads(request.read()) == plan["packets"][len(seen)]["payload"]
        seen.append(request)
        return reply(request)

    async def run():
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            return await paired.run_comparison(plan, bindings, config, p.chat, tmp_path)

    summary = asyncio.run(run())
    assert len(seen) == summary["physical_attempts"] == summary["attempted"] == 12
    assert summary["schema_valid"] == summary["literal_valid"] == 12
    assert not summary["semantic_review_completed"] and not summary["production_ready"]
    assert not summary["stopped_fatal"]
    assert len(list(tmp_path.glob("*/*/PL*.json"))) == 12
    assert all(
        summary[k] == 0
        for k in (
            "embedding_calls",
            "qdrant_calls",
            "answer_generation_calls",
            "reserved_evaluation_requests",
        )
    )


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
def test_fatal_failure_stops_both_arms_with_no_retry(tmp_path, status):
    plan, bindings, config = prepared()
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={"error": "synthetic"})

    async def run():
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            return await paired.run_comparison(plan, bindings, config, p.chat, tmp_path)

    summary = asyncio.run(run())
    assert summary["stopped_fatal"] and len(seen) == summary["attempted"] == 1


def test_ambiguous_timeout_has_no_retry_and_remains_unassessed(tmp_path):
    plan, bindings, config = prepared()
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            raise httpx.ReadTimeout("synthetic unknown upstream completion")
        return reply(request)

    async def run():
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            return await paired.run_comparison(plan, bindings, config, p.chat, tmp_path)

    summary = asyncio.run(run())
    first = json.loads((tmp_path / "control/PL01-ar/PL01-ar.json").read_bytes())
    assert len(seen) == 12 and summary["schema_valid"] == 11
    assert first["proposal"] is None and first["error_code"] == "provider_timeout"
    assert first["reported_input_tokens"] is None
    assert first["semantic_review"] == "pending"


@pytest.mark.parametrize(
    "tamper", ["order", "request", "schema", "system", "hash", "extra", "late"]
)
def test_any_changed_pair_rejects_before_first_dispatch(tmp_path, tamper):
    plan, bindings, config = prepared()
    packets = plan["packets"]
    item = packets[-1]
    if tamper == "order":
        packets.reverse()
    elif tamper == "request":
        item["request"] = {**item["request"], "query": "changed"}
    elif tamper == "hash":
        item["payload_sha256"] = "changed"
    elif tamper == "extra":
        item["gold"] = "forbidden"
    else:
        if tamper == "schema":
            item["payload"]["response_format"] = {}
        elif tamper == "system":
            item["payload"]["messages"][0]["content"] += " changed"
        else:
            # Self-consistent metadata tampering passes the difference check but
            # must fail the complete-list production-builder authentication.
            data = json.loads(item["payload"]["messages"][-1]["content"])
            data["source_manifest"]["invented"] = "changed"
            item["payload"]["messages"][-1]["content"] = json.dumps(data)
        item["payload_sha256"] = payload_hash(item["payload"])

    class Forbidden:
        async def complete(self, *args, **kwargs):
            raise AssertionError("Must reject before first dispatch")

    with pytest.raises(ValueError, match="paired_|comparison_builder"):
        asyncio.run(paired.run_comparison(plan, bindings, config, Forbidden(), tmp_path))
    assert not list(tmp_path.iterdir())


def test_complete_96_packet_order_has_exactly_one_of_each_arm():
    plan, _, _ = prepared()
    template = plan["packets"][:2]
    ids = tuple(f"synthetic-{i:02}" for i in range(48))
    packets = []
    for i, identity in enumerate(ids):
        for base in template if i % 2 == 0 else template[::-1]:
            item = copy.deepcopy(base)
            item["case_id"] = identity
            packets.append(item)
    paired.verify_pairs(packets, ids)
    assert len(packets) == len({(p["case_id"], p["arm"]) for p in packets}) == 96
    with pytest.raises(ValueError, match="inventory"):
        paired.verify_pairs(packets[:-1], ids)


def test_exclusive_marker_refuses_reexecution_before_credentials(tmp_path, monkeypatch):
    plan, bindings, _ = prepared()
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (tmp_path / "started.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paired, "comparison_plan", lambda root: (plan, bindings))
    monkeypatch.setattr(paired.subprocess, "check_output", lambda *a, **k: "")
    monkeypatch.setattr("sys.argv", ["paired", "--output", str(tmp_path), "--execute"])

    def forbidden():
        raise AssertionError("No credential access on replay")

    monkeypatch.setattr(paired, "load_settings", forbidden)
    with pytest.raises(FileExistsError):
        asyncio.run(paired.main())
