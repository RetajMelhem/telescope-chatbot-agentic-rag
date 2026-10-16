"""Paid-dispatch isolation/immutability tests; no model semantic grading or real HTTP."""

import asyncio
import json
from datetime import UTC, datetime

import httpx2 as httpx
import pytest
from test_anchored_workflow import wire
from test_hours_graph import fixtures, hours_part, inputs

from scripts import run_hours_planner_screen as screen
from scripts.run_luna_planner_screen import payload_hash, screen_settings
from telescope_rag.graph.hours_inputs import HoursPlannerReply
from telescope_rag.graph.hours_workflow import HoursRagWorkflow
from telescope_rag.knowledge.hours import hours_plan_digest
from telescope_rag.providers.openrouter import OpenRouterProviders

NOW = datetime(2026, 10, 16, 20, tzinfo=UTC)


def compose(config, chat, clock=NOW, hours_profile="v12"):
    catalog, authority, plan, _ = fixtures()
    return HoursRagWorkflow(
        settings=config,
        chat=chat,
        retriever=screen._NoDownstream(),
        catalog=catalog,
        counter=screen._NoDownstream(),
        directory_authority=authority,
        hours_plan=plan,
        expected_hours_plan_digest=hours_plan_digest(plan),
        planner_output_tokens=screen.OUTPUT_CAP,
        clock=lambda: clock,
        hours_profile=hours_profile,
    )


def frozen(tmp_path, monkeypatch, *, text="When does the center open?", language="en"):
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "H01-" + language,
                        "request": {"query": text, "language": "auto", "history": []},
                        "expected_decisions": ["GOLD-ONLY-DO-NOT-SEND"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        screen,
        "build_workflow",
        lambda root, config, chat, clock, hours_profile="v12": compose(
            config, chat, clock, hours_profile
        ),
    )
    monkeypatch.setattr(screen, "source_bindings", lambda root: {"synthetic-source": "hash"})
    monkeypatch.setattr(screen, "code_bindings", lambda root: {"synthetic-code": "hash"})
    return cases, asyncio.run(screen.freeze_plan(tmp_path, cases, NOW))


def test_opt_in_profile_is_pinned_and_default_frozen_wire_is_unchanged(tmp_path, monkeypatch):
    cases, default = frozen(tmp_path, monkeypatch)
    candidate = asyncio.run(
        screen.freeze_plan(tmp_path, cases, NOW, hours_profile="identity_links_v13")
    )
    assert "hours_profile" not in default
    assert candidate["hours_profile"] == "identity_links_v13"
    old = json.loads(default["packets"][0]["payload"]["messages"][-1]["content"])
    new = json.loads(candidate["packets"][0]["payload"]["messages"][-1]["content"])
    assert old["hours_manifest"]["subjects"] == new["hours_manifest"]["subjects"]
    assert old["prompt_version"] != new["prompt_version"]
    assert new["hours_manifest"]["identity_metadata"]["groups"] == []
    assert candidate["packets"][0]["payload_sha256"] != default["packets"][0]["payload_sha256"]


@pytest.mark.parametrize(
    "language,text,subject",
    [
        ("en", "When does the center open?", "the center"),
        ("ar", "متى يفتح المركز؟", "المركز"),
        ("ar-JO", "إيمتى المركز بيفتح؟", "المركز"),
    ],
)
def test_freezing_captures_actual_graph_wire_without_gold_or_dispatch(
    tmp_path, monkeypatch, language, text, subject
):
    cases, plan = frozen(tmp_path, monkeypatch, text=text, language=language)
    packet = plan["packets"][0]
    config = screen_settings(profile="local_constraints", output_cap=screen.OUTPUT_CAP)
    assert "GOLD-ONLY" not in json.dumps(packet["payload"])
    assert packet["expected_decisions"] == ["GOLD-ONLY-DO-NOT-SEND"]
    assert packet["payload_sha256"] == payload_hash(packet["payload"])
    assert packet["payload"]["response_format"]["json_schema"]["name"] == "HoursPlannerReply"
    assert packet["payload"]["max_completion_tokens"] == 4096
    assert "reasoning" not in packet["payload"] and plan["automatic_retries"] == 0

    async def scenario():
        seen = []

        def handler(request):
            seen.append(json.loads(request.read()))
            return wire(
                HoursPlannerReply(
                    language=language,
                    parts=(hours_part(text, inputs(workflow, subject_text=subject)),),
                )
            )

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            workflow = compose(config, screen._ExactChat(providers.chat, packet, config))
            result = await screen.run_packet(packet, workflow, config)
        assert (
            result["schema_valid"]
            and result["literal_bindings_valid"]
            and result["error_code"] is None
        )
        assert result["physical_attempts"] == result["logical_chat_calls"] == len(seen) == 1
        assert seen[0] == packet["payload"]
        assert result["stages"] == ["validate_request", "plan_query", "validate_plan"]
        assert result["computed_hours"][0]["input"]["intent"] == "schedule"
        assert result["semantic_review"] == "pending"

    asyncio.run(scenario())


@pytest.mark.parametrize("tamper", ["payload", "digest", "schema"])
def test_changed_payload_cannot_reach_the_provider(tmp_path, monkeypatch, tamper):
    _, plan = frozen(tmp_path, monkeypatch)
    packet = plan["packets"][0]
    if tamper == "payload":
        packet["payload"]["messages"][-1]["content"] += "altered"
    elif tamper == "digest":
        packet["payload_sha256"] = "wrong"
    else:
        packet["payload"]["response_format"]["json_schema"]["name"] = "wrong"
    config = screen_settings(profile="local_constraints", output_cap=4096)

    async def scenario():
        seen = []
        async with OpenRouterProviders(
            config, transport=httpx.MockTransport(lambda req: seen.append(req))
        ) as providers:
            workflow = compose(config, screen._ExactChat(providers.chat, packet, config))
            result = await screen.run_packet(packet, workflow, config)
        assert not seen and result["physical_attempts"] == 0 and result["fatal"]

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["literal", "truncation", "credit", "transport"])
def test_failed_attempts_are_recorded_once_without_downstream_or_repair(
    tmp_path, monkeypatch, mode
):
    _, plan = frozen(tmp_path, monkeypatch)
    packet = plan["packets"][0]
    config = screen_settings(profile="local_constraints", output_cap=4096)

    async def scenario():
        attempts = []

        def handler(request):
            attempts.append(1)
            if mode == "credit":
                return httpx.Response(402, json={"error": {"message": "SYNTHETIC-SECRET"}})
            if mode == "transport":
                raise httpx.ConnectError("SYNTHETIC-SECRET")
            reply = HoursPlannerReply(
                language="en",
                parts=(
                    hours_part(
                        "When does the center open?",
                        inputs(
                            workflow,
                            subject_text="not present" if mode == "literal" else "the center",
                        ),
                    ),
                ),
            )
            response = wire(reply)
            if mode == "truncation":
                body = response.json()
                body["choices"][0]["finish_reason"] = "length"
                return httpx.Response(200, json=body)
            return response

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            workflow = compose(config, screen._ExactChat(providers.chat, packet, config))
            result = await screen.run_packet(packet, workflow, config)
        assert len(attempts) == result["physical_attempts"] == 1 and result["error_code"]
        assert not result["literal_bindings_valid"] and "SYNTHETIC-SECRET" not in json.dumps(result)
        assert (
            result["schema_valid"] == (mode == "literal") and result["semantic_review"] == "pending"
        )
        assert result["fatal"] == (mode == "credit")

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["dirty", "changed", "started"])
def test_execute_rejects_checkout_drift_or_repeat_before_loading_credentials(
    tmp_path, monkeypatch, mode
):
    cases, plan = frozen(tmp_path, monkeypatch)
    output = tmp_path / "run"
    output.mkdir()
    (output / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(
        screen.subprocess, "check_output", lambda *a, **kw: b"dirty" if mode == "dirty" else b""
    )
    monkeypatch.setattr(
        screen,
        "load_settings",
        lambda *a: (_ for _ in ()).throw(AssertionError("must not load secrets")),
    )
    if mode == "changed":
        plan["packets"][0]["payload_sha256"] = "altered"
        (output / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    if mode == "started":
        (output / "started.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError if mode == "started" else ValueError):
        asyncio.run(screen.execute(tmp_path, output, cases))
    assert not (output / "finished.json").exists()


def test_case_inventory_refuses_duplicates_before_any_dispatch(tmp_path, monkeypatch):
    cases, _ = frozen(tmp_path, monkeypatch)
    value = json.loads(cases.read_bytes())
    value["cases"] *= 2
    cases.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="hours_screen_duplicate_case"):
        asyncio.run(screen.freeze_plan(tmp_path, cases, NOW))
