"""Authored boundary/owner contrasts through real adapters; no live semantic grading."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest
from pydantic import ValidationError
from test_anchored_workflow import part
from test_hours_graph import fixtures, quote
from test_offline_workflow import SyntheticCounter, catalog

from scripts import run_hours_planner_screen as screen
from scripts.run_luna_planner_screen import screen_settings
from telescope_rag.api.hours_presentation import project_hours_response
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.graph.hours_contract import (
    ContractHoursInput,
    ContractHoursPlannerPart,
    ContractHoursPlannerReply,
    contract_hours_manifest,
    hours_reply_model,
)
from telescope_rag.graph.hours_workflow import HoursRagWorkflow
from telescope_rag.knowledge.hours import hours_plan_digest
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.providers.validation import output_schema

NOW = datetime(2026, 10, 16, 20, tzinfo=UTC)
IDENTITY = UUID(int=1400)


def supplied(**changes):
    return (
        dict(
            intent="local",
            subject_handle="h1",
            subject_quote=quote("the center").model_dump(),
            date_value="2026-10-16",
            date_quote=quote("2026-10-16").model_dump(),
            hour=12,
            minute=0,
            clock_basis="am",
            time_quote=quote("12:00 AM").model_dump(),
        )
        | changes
    )


def compose(chat, *, profile="contracts_v14"):
    original, authority, plan, _ = fixtures()
    chunks = []
    for chunk in original.chunks.values():
        changes = {}
        if chunk.doctor_id:
            changes = dict(
                document_id="directory" if chunk.doctor_id == "a" else "profile",
                canonical_url="https://telescopecenter.com/synthetic-"
                + ("directory/" if chunk.doctor_id == "a" else "profile/"),
                canonical_doctor_id="confirmed-person",
                canonical_doctor_name="Synthetic approved person",
            )
        chunks.append(chunk.model_copy(update=changes))
    evidence = catalog(*chunks)
    plan = plan.model_copy(update={"prepared_digest": evidence.prepared_digest})
    authority = authority.model_copy(
        update={
            "prepared_digest": evidence.prepared_digest,
            "primary_directory_document_ids": ("directory",),
        }
    )
    return HoursRagWorkflow(
        settings=screen_settings(profile="local_constraints", output_cap=4096),
        chat=chat,
        retriever=screen._NoDownstream(),
        counter=SyntheticCounter(),
        token_basis="synthetic_test",
        catalog=evidence,
        directory_authority=authority,
        hours_plan=plan,
        expected_hours_plan_digest=hours_plan_digest(plan),
        planner_output_tokens=4096,
        clock=lambda: NOW,
        hours_profile=profile,
    )


def response(proposal):
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
            "usage": {"prompt_tokens": 20, "completion_tokens": 12},
        },
    )


async def execute(text, propose):
    seen = []

    def handler(request):
        seen.append(json.loads(request.read()))
        return response(propose(workflow))

    config = screen_settings(profile="local_constraints", output_cap=4096)
    async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
        workflow = compose(providers.chat)
        request = WorkflowRequest(query=text)
        run = await workflow.run(request, request_id=IDENTITY)
    return workflow, run, seen


@pytest.mark.parametrize(
    "basis,hour",
    [
        ("24h", 0),
        ("24h", 23),
        ("am", 1),
        ("am", 12),
        ("pm", 12),
        ("pm", 11),
        ("unspecified", 1),
        ("unspecified", 12),
    ],
)
def test_consistent_clock_pairs_remain_literal(basis, hour):
    model = ContractHoursInput.model_validate_json(
        json.dumps(supplied(clock_basis=basis, hour=hour))
    )
    assert (model.hour, model.clock_basis) == (hour, basis)


@pytest.mark.parametrize(
    "basis,hour",
    [
        ("am", 0),
        ("pm", 0),
        ("unspecified", 0),
        ("am", 13),
        ("pm", 23),
        ("unspecified", 13),
        ("24h", 24),
        ("24h", -1),
    ],
)
def test_inconsistent_clock_pairs_fail_without_normalization(basis, hour):
    with pytest.raises(ValidationError):
        ContractHoursInput.model_validate_json(json.dumps(supplied(clock_basis=basis, hour=hour)))


@pytest.mark.parametrize(
    "mode", ["missing_hour", "missing_basis", "schedule_has_clock", "now_has_clock"]
)
def test_inherited_input_shape_remains_enforced(mode):
    changes = (
        {"hour": None}
        if mode == "missing_hour"
        else {"clock_basis": None}
        if mode == "missing_basis"
        else {"intent": "schedule" if mode == "schedule_has_clock" else "now"}
    )
    with pytest.raises(ValidationError):
        ContractHoursInput.model_validate_json(json.dumps(supplied(**changes)))


@pytest.mark.parametrize(
    "mode",
    [
        "query",
        "search_hours",
        "read_hours",
        "excluded_hours",
        "clarification_hours",
        "missing_hours",
        "wrong_use",
    ],
)
def test_hours_and_search_contract_is_exclusive(mode):
    base = part(
        "When does the center open?", operation="time_comparison", retrieval_query=None
    ).model_dump()
    base["hours"] = supplied(
        intent="schedule",
        date_value=None,
        date_quote=None,
        hour=None,
        minute=None,
        clock_basis=None,
        time_quote=None,
    )
    if mode == "query":
        base["retrieval_query"] = "Do not search."
    if mode == "search_hours":
        base["operation"] = "search"
    if mode == "read_hours":
        base["operation"] = "read_source"
    if mode == "excluded_hours":
        base["state"] = "excluded"
    if mode == "clarification_hours":
        base["state"] = "clarification_required"
    if mode == "missing_hours":
        base["hours"] = None
    if mode == "wrong_use":
        base["intended_use"] = "profile_detail"
    with pytest.raises(ValidationError):
        ContractHoursPlannerPart.model_validate_json(json.dumps(base))


@pytest.mark.parametrize(
    "state,operation",
    [
        ("public", "search"),
        ("public", "read_source"),
        ("excluded", "search"),
        ("clarification_required", "time_comparison"),
    ],
)
def test_nonhours_parts_keep_nullable_hours(state, operation):
    value = part("Synthetic question", state=state, operation=operation).model_dump() | {
        "hours": None
    }
    assert ContractHoursPlannerPart.model_validate_json(json.dumps(value)).hours is None


def test_manifest_keeps_exact_membership_tuples_and_old_handles():
    workflow = compose(screen._CaptureChat(ContractHoursPlannerReply))
    manifest = json.loads(workflow._hours_manifest_json)
    old = json.loads(workflow.hours_bindings.manifest_json)
    assert [
        {k: v for k, v in entry.items() if k != "source_membership"}
        for entry in manifest["subjects"]
    ] == old["subjects"]
    docs = {identity: handle for handle, identity in workflow._bindings.documents.items()}
    for entry in manifest["subjects"]:
        subject = workflow.hours_bindings.subjects[entry["handle"]]
        if subject.kind != "doctor":
            assert "source_membership" not in entry
            continue
        expected = {
            (docs[c.document_id], c.block_type, c.language)
            for c in workflow._catalog.chunks.values()
            if (c.doctor_id if subject.owner_kind == "literal" else c.canonical_doctor_id)
            == subject.id
        }
        assert {
            (m["document_handle"], m["block_type"], m["source_language"])
            for m in entry["source_membership"]
        } == expected


def schedule(workflow, text, *, identity=None, kind="clinic", **changes):
    handle = next(
        h
        for h, s in workflow.hours_bindings.subjects.items()
        if (s.kind == kind and (identity is None or (s.owner_kind, s.id) == identity))
    )
    fields = supplied(
        intent="schedule",
        subject_handle=handle,
        subject_quote=quote(text).model_dump(),
        date_value=None,
        date_quote=None,
        hour=None,
        minute=None,
        clock_basis=None,
        time_quote=None,
    )
    proposal = (
        part(text, operation="time_comparison", retrieval_query=None).model_dump()
        | {"hours": fields}
        | changes
    )
    return {"language": "ar" if text == "الطبيب" else "en", "parts": [proposal]}


@pytest.mark.parametrize(
    "identity,scope,accepted",
    [
        (("literal", "b"), "directory", False),
        (("canonical", "confirmed-person"), "directory", True),
        (("literal", "a"), "directory", True),
        (("literal", "b"), "profile", True),
        (("literal", "a"), "profile", False),
        (("canonical", "confirmed-person"), "profile", True),
    ],
)
@pytest.mark.parametrize("text", ["Synthetic doctor", "الطبيب"])
def test_doctor_subject_and_declared_source_are_jointly_checked(identity, scope, accepted, text):
    def proposal(w):
        doc = next(h for h, d in w._bindings.documents.items() if d == scope)
        return schedule(w, text, kind="doctor", identity=identity, document_handles=[doc])

    workflow, run, seen = asyncio.run(execute(text, proposal))
    assert len(seen) == 1
    if not accepted:
        assert run.result.outcome == "failed" and run.result.error_code == "invalid_hours_input"
        assert run.evidence is None
    else:
        assert run.result.outcome != "failed"
        summary = project_hours_response(
            run, catalog=workflow._catalog, request_id=IDENTITY, bindings=workflow.hours_bindings
        )
        assert summary.questions[0].hours.reason == "missing_hours"
        assert not summary.citations


@pytest.mark.parametrize("restriction", ["owner", "language", "block"])
def test_doctor_scope_does_not_switch_owner_language_or_block_to_find_evidence(restriction):
    def proposal(w):
        changes = (
            {"source_language": "ar"}
            if restriction == "language"
            else {"block_types": ["faq"]}
            if restriction == "block"
            else {
                "owner_handle": next(
                    h for h, v in w._bindings.owners.items() if v == ("literal", "b")
                )
            }
        )
        return schedule(w, "Synthetic doctor", kind="doctor", identity=("literal", "a"), **changes)

    _, run, seen = asyncio.run(execute("Synthetic doctor", proposal))
    assert len(seen) == 1 and run.result.error_code == "invalid_hours_input"


def test_facility_restricted_to_contact_stays_unknown_without_source_fallback():
    def proposal(w):
        doc = next(h for h, d in w._bindings.documents.items() if d == "contact")
        return schedule(w, "the center", document_handles=[doc])

    workflow, run, seen = asyncio.run(execute("the center", proposal))
    assert len(seen) == 1 and run.result.outcome != "failed"
    reply = project_hours_response(
        run, catalog=workflow._catalog, request_id=IDENTITY, bindings=workflow.hours_bindings
    )
    assert reply.questions[0].hours.reason == "missing_hours" and not reply.citations


@pytest.mark.parametrize("basis,hour", [("am", 12), ("24h", 0), ("pm", 12), ("24h", 12)])
def test_midnight_and_noon_are_distinct_and_source_bound(basis, hour):
    text = f"the center 2026-10-16 at {hour} ({basis})"

    def proposal(w):
        value = schedule(w, text)
        value["parts"][0]["hours"] = supplied(
            subject_handle=value["parts"][0]["hours"]["subject_handle"],
            subject_quote=quote("the center").model_dump(),
            hour=hour,
            clock_basis=basis,
            time_quote=quote(f"{hour} ({basis})").model_dump(),
        )
        return value

    workflow, run, seen = asyncio.run(execute(text, proposal))
    assert len(seen) == 1 and run.result.outcome != "failed"
    reply = project_hours_response(
        run, catalog=workflow._catalog, request_id=IDENTITY, bindings=workflow.hours_bindings
    )
    assert reply.questions[0].hours.local_candidates[0].hour == (
        0 if basis == "am" or hour == 0 else 12
    )
    assert reply.questions[0].hours.status == "outside_posted_hours"  # Friday opens at 14:00.
    assert len(reply.citations) == 2


@pytest.mark.parametrize("bad", ["clock", "query"])
def test_actual_adapter_rejects_bad_pairs_and_queries_once_before_downstream(bad):
    text = "the center 2026-10-16 12:00 AM"

    def proposal(w):
        value = schedule(w, text)
        if bad == "clock":
            value["parts"][0]["hours"] = supplied(
                subject_handle=value["parts"][0]["hours"]["subject_handle"],
                subject_quote=quote("the center").model_dump(),
                hour=0,
            )
        else:
            value["parts"][0]["retrieval_query"] = text
        return value

    _, run, seen = asyncio.run(execute(text, proposal))
    assert len(seen) == 1 and run.result.error_code == "provider_failed"
    assert run.usage.receipts[0].outcome == "structured_output_invalid"
    assert run.evidence is None and run.computed_hours == ()


def test_presenter_rechecks_subject_source_relationship_after_receipt_tampering():
    def proposal(w):
        doc = next(h for h, d in w._bindings.documents.items() if d == "directory")
        return schedule(
            w,
            "Synthetic doctor",
            kind="doctor",
            identity=("canonical", "confirmed-person"),
            document_handles=[doc],
        )

    workflow, run, _ = asyncio.run(execute("Synthetic doctor", proposal))
    receipt = run.computed_hours[0]
    other = next(h for h, s in workflow.hours_bindings.subjects.items() if s.id == "b")
    changed = replace(
        receipt, supplied=receipt.supplied.model_copy(update={"subject_handle": other})
    )
    tampered = replace(run, computed_hours=(changed,))
    with pytest.raises(ValueError, match="offline_hours_response_invalid"):
        project_hours_response(
            tampered,
            catalog=workflow._catalog,
            request_id=IDENTITY,
            bindings=workflow.hours_bindings,
        )


def test_material_unknown_identity_still_requests_clarification_without_source_inference():
    def proposal(w):
        value = schedule(w, "Which doctor?")
        value["parts"][0]["hours"]["subject_handle"] = None
        return value

    workflow, run, _ = asyncio.run(execute("Which doctor?", proposal))
    reply = project_hours_response(
        run, catalog=workflow._catalog, request_id=IDENTITY, bindings=workflow.hours_bindings
    )
    assert reply.questions[0].hours.reason == "ambiguous_subject"
    assert reply.questions[0].status == "clarification_required" and not reply.citations


def test_typed_unspecified_clock_keeps_both_candidates_and_no_guess():
    text = "the center 2026-10-16 at 7; do not guess AM or PM"

    def proposal(w):
        value = schedule(w, text)
        value["parts"][0]["constraint_quotes"] = ["do not guess AM or PM"]
        value["parts"][0]["hours"] = supplied(
            subject_handle=value["parts"][0]["hours"]["subject_handle"],
            subject_quote=quote("the center").model_dump(),
            hour=7,
            clock_basis="unspecified",
            time_quote=quote("7").model_dump(),
        )
        return value

    workflow, run, seen = asyncio.run(execute(text, proposal))
    reply = project_hours_response(
        run, catalog=workflow._catalog, request_id=IDENTITY, bindings=workflow.hours_bindings
    )
    summary = reply.questions[0].hours
    assert len(seen) == 1 and summary.reason == "ambiguous_time"
    assert summary.clock_ambiguous and [d.hour for d in summary.local_candidates] == [7, 19]
    assert run.request_anchors[0].constraints[0].quote == "do not guess AM or PM"


def test_new_schema_prompt_and_runner_are_explicitly_pinned(tmp_path, monkeypatch):
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "H31-en",
                        "request": {"query": "When does the center open?"},
                        "expected_decisions": ["GOLD-ONLY"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        screen,
        "build_workflow",
        lambda root, config, chat, clock, hours_profile="v12": compose(chat, profile=hours_profile),
    )
    monkeypatch.setattr(screen, "source_bindings", lambda root: {})
    monkeypatch.setattr(screen, "code_bindings", lambda root: {})
    frozen = asyncio.run(screen.freeze_plan(tmp_path, path, NOW, "contracts_v14"))
    packet = frozen["packets"][0]
    assert frozen["hours_profile"] == "contracts_v14"
    schema = packet["payload"]["response_format"]["json_schema"]
    assert schema == output_schema(ContractHoursPlannerReply)
    assert "0..23" in json.dumps(schema) and "Hours/time_comparison always uses null" in json.dumps(
        schema
    )
    assert "GOLD-ONLY" not in json.dumps(packet["payload"])
    assert (
        "Return only the closed HoursPlannerReply schema"
        not in packet["payload"]["messages"][0]["content"]
    )
    assert hours_reply_model("contracts_v14") is ContractHoursPlannerReply

    async def run():
        seen = []

        def handler(request):
            seen.append(json.loads(request.read()))
            return response(schedule(workflow, "When does the center open?"))

        config = screen_settings(profile="local_constraints", output_cap=4096)
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            workflow = compose(
                screen._ExactChat(providers.chat, packet, config, ContractHoursPlannerReply)
            )
            row = await screen.run_packet(packet, workflow, config)
        assert row["schema_valid"] and row["literal_bindings_valid"] and len(seen) == 1
        assert seen[0] == packet["payload"]

    asyncio.run(run())


def test_contract_manifest_bound_includes_source_membership(monkeypatch):
    workflow = compose(screen._CaptureChat(ContractHoursPlannerReply))
    import telescope_rag.graph.hours_contract as module

    monkeypatch.setattr(
        module,
        "identity_hours_manifest",
        lambda *a: json.dumps({"subjects": [], "padding": "x" * 96000}),
    )
    with pytest.raises(ValueError, match="hours_manifest_exceeds_bound"):
        contract_hours_manifest(workflow.hours_bindings, workflow._bindings)
