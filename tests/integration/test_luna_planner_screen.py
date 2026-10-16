"""Development-only screen contracts with synthetic inputs and forbidden live I/O."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx2 as httpx
import pytest
from test_offline_workflow import catalog, single_plan, source

from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.providers.openrouter import OpenRouterProviders

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts import run_luna_planner_screen as screen


def preparation(profile="baseline"):
    bindings = SourceBindings(catalog(source(1)), include_block_types=profile != "baseline")
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
    return bindings, screen.development_packets(cases, bindings, profile=profile)


def reply(request, *, usage=True, invalid_binding=False):
    payload = json.loads(request.read())
    body = json.loads(payload["messages"][-1]["content"])
    proposal = single_plan()(body).model_dump(mode="json")
    if payload["response_format"]["json_schema"]["name"] == "AnchoredPlannerReply":
        for part in proposal["parts"]:
            start, end = part.pop("start"), part.pop("end")
            part["original_text"] = body["original_query"][start:end]
            part["constraint_quotes"] = []
        AnchoredPlannerReply.model_validate_json(json.dumps(proposal))
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
@pytest.mark.parametrize(
    "profile",
    [
        "baseline",
        "source_types_no_reasoning",
        "literal_anchors",
        "answer_targets",
        "policy_targets",
    ],
)
def test_exact_six_development_inputs_match_actual_adapter_and_have_no_gold(
    tmp_path, usage, profile
):
    bindings, packets = preparation(profile)
    assert tuple(p["case_id"] for p in packets) == screen.DEVELOPMENT_IDS
    assert all(set(p) == {"case_id", "request", "payload", "payload_sha256"} for p in packets)
    config = screen.screen_settings(profile=profile)
    seen = []

    def handler(request):
        actual = json.loads(request.read())
        assert actual == packets[len(seen)]["payload"]
        assert actual["response_format"]["json_schema"]["name"] == (
            "AnchoredPlannerReply"
            if profile in {"literal_anchors", "answer_targets", "policy_targets"}
            else "PlannerReply"
        )
        assert actual["max_completion_tokens"] == 1000
        if profile == "source_types_no_reasoning":
            assert actual["reasoning"] == {"effort": "none"}
        else:
            assert "reasoning" not in actual
        if profile != "baseline":
            manifest = json.loads(actual["messages"][-1]["content"])["source_manifest"]
            assert all(d["available_block_types"] == ["section"] for d in manifest["documents"])
        seen.append(actual)
        return reply(request, usage=usage)

    async def run():
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            return await screen.run_packets(
                packets, bindings, config, p.chat, tmp_path, profile=profile
            )

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
        if profile in {"literal_anchors", "answer_targets", "policy_targets"}:
            assert saved["derived_proposal"]["parts"][0]["start"] == 0
            assert saved["request_anchors"][0]["original"]["quote"] == packet["request"]["query"]
            if profile in {"answer_targets", "policy_targets"}:
                assert saved["answer_targets"][0]["target"]["quote"] == packet["request"]["query"]


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
    monkeypatch.setattr(screen, "build_plan", lambda root, **kwargs: (plan, bindings))
    monkeypatch.setattr(screen.subprocess, "check_output", lambda *a, **k: "")
    monkeypatch.setattr("sys.argv", ["screen", "--output", str(tmp_path), "--execute"])

    def forbidden():
        raise AssertionError("Must reject repeat before loading keys")

    monkeypatch.setattr(screen, "load_settings", forbidden)
    with pytest.raises(FileExistsError):
        asyncio.run(screen.main())


def test_manifest_types_come_from_literal_source_structure_without_inventing_contact_type():
    item = source(1).model_copy(update={"page_title": "Contact details", "block_type": "section"})
    original = item.model_dump_json()
    evidence = catalog(item)
    baseline = json.loads(SourceBindings(evidence).manifest_json)
    candidate = json.loads(SourceBindings(evidence, include_block_types=True).manifest_json)
    assert candidate["documents"][0]["available_block_types"] == ["section"]
    candidate["documents"][0].pop("available_block_types")
    assert candidate == baseline and item.model_dump_json() == original


@pytest.mark.parametrize("identities", [(), ("PL02-en",), ("PL05-en", "PL05-en")])
def test_declared_subset_refuses_empty_reserved_or_repeated_cases(identities):
    with pytest.raises(ValueError, match="development_inventory_mismatch"):
        screen.selected_case_ids(identities)


def test_three_case_capacity_screen_does_not_repeat_successful_cases_or_disable_reasoning(tmp_path):
    bindings, packets = preparation("literal_anchors")
    identities = tuple(i for i in screen.DEVELOPMENT_IDS if i.startswith("PL05-"))
    cases = [
        SimpleNamespace(
            case_id=p["case_id"],
            split="development",
            request=screen.WorkflowRequest.model_validate_json(json.dumps(p["request"])),
        )
        for p in packets
    ]
    selected = screen.development_packets(
        cases, bindings, profile="literal_anchors", case_ids=identities, output_cap=4096
    )
    config = screen.screen_settings(profile="literal_anchors", output_cap=4096)
    assert config.provider_timeout_seconds == config.request_timeout_seconds == 30
    assert config.max_total_output_tokens == 4096 and config.max_llm_calls == 1
    seen = []

    def handler(request):
        payload = json.loads(request.read())
        assert payload == selected[len(seen)]["payload"]
        assert payload["max_completion_tokens"] == 4096 and "reasoning" not in payload
        seen.append(payload)
        data = reply(request).json()
        data["usage"]["completion_tokens"] = 1500
        return httpx.Response(200, json=data)

    async def run():
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            return await screen.run_packets(
                selected,
                bindings,
                config,
                p.chat,
                tmp_path,
                profile="literal_anchors",
                case_ids=identities,
                output_cap=4096,
            )

    summary = asyncio.run(run())
    assert summary["cases_planned"] == summary["cases_attempted"] == len(seen) == 3
    assert summary["schema_valid"] == summary["literal_bindings_valid"] == 3
    assert {r["case_id"] for r in summary["case_results"]} == set(identities)
    for identity in identities:
        saved = json.loads((tmp_path / f"{identity}.json").read_bytes())
        assert saved["charged_output_tokens"] == 1500
        assert saved["receipts"][0]["output_reserved"] == 4096
        assert saved["receipts"][0]["input_reserved"] is None


def test_prepared_subset_survives_source_binding_inventory_iteration(tmp_path, monkeypatch):
    import hashlib

    bindings, packets = preparation("literal_anchors")
    code = tmp_path / "src/telescope_rag/synthetic.py"
    code.parent.mkdir(parents=True)
    code.write_text("# Synthetic binding only.\n", encoding="utf-8")
    digest = hashlib.sha256(code.read_bytes()).hexdigest()
    sources = {}
    for i in range(122):
        path = tmp_path / f"data/synthetic-{i}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        sources[path.relative_to(tmp_path).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    inventory = tmp_path / screen.SOURCE_HASHES
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps(sources), encoding="utf-8")
    fixtures = tmp_path / screen.FIXTURES
    fixtures.mkdir(parents=True)
    (fixtures / "independent-reviews.json").write_text("[]", encoding="utf-8")
    cases = [
        SimpleNamespace(
            case_id=p["case_id"],
            split="development",
            request=screen.WorkflowRequest.model_validate_json(json.dumps(p["request"])),
        )
        for p in packets
    ]
    evidence = catalog(source(1))
    manifest = {
        "bindings": {"src/telescope_rag/synthetic.py": digest},
        "source_bundle": "data/synthetic",
        "prepared_digest": evidence.prepared_digest,
    }
    monkeypatch.setattr(screen, "verify_inventory", lambda *a: manifest)
    monkeypatch.setattr(screen, "load_corpus", lambda *a: ((), {}))
    monkeypatch.setattr(screen, "EvidenceCatalog", lambda *a, **k: evidence)
    monkeypatch.setattr(screen, "load_fixtures", lambda *a: cases)
    monkeypatch.setattr(screen, "validate_cohort", lambda *a, **k: None)
    monkeypatch.setattr(screen, "validate_reviews", lambda *a, **k: None)
    monkeypatch.setattr(screen, "validate_source_evidence", lambda *a, **k: {})
    identities = tuple(i for i in screen.DEVELOPMENT_IDS if i.startswith("PL05-"))
    plan, _ = screen.build_plan(
        tmp_path, profile="literal_anchors", case_ids=identities, output_cap=4096
    )
    assert tuple(plan["case_ids"]) == identities and plan["requests_max"] == 3
    assert plan["per_request_output_cap"] == 4096 and plan["per_request_timeout_seconds"] == 30
    assert {p["case_id"] for p in plan["packets"]} == set(identities)
