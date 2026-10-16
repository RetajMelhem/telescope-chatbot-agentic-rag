"""Exact identity projection and graph isolation; authored plans, no semantic grading."""

import asyncio
import json
from datetime import UTC, datetime

import httpx2 as httpx
import pytest
from test_anchored_workflow import wire
from test_hours_graph import fixtures, hours_part, inputs
from test_offline_workflow import catalog

from scripts import run_hours_planner_screen as screen
from scripts.run_luna_planner_screen import screen_settings
from telescope_rag.graph.hours_identity import identity_hours_manifest
from telescope_rag.graph.hours_inputs import HoursPlannerReply
from telescope_rag.graph.hours_workflow import HoursRagWorkflow
from telescope_rag.knowledge.hours import hours_plan_digest
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.retrieval.assembly import SourceScope

NOW = datetime(2026, 10, 16, 20, tzinfo=UTC)


def compose(chat, *, updates=None, profile="identity_links_v13", same_labels=False):
    original, authority, plan, _ = fixtures()
    changes = (
        updates
        if updates is not None
        else {
            "synthetic-chunk-1": {
                "canonical_doctor_id": "confirmed-one",
                "canonical_doctor_name": "Synthetic approved display",
            },
            "synthetic-chunk-2": {
                "canonical_doctor_id": "confirmed-one",
                "canonical_doctor_name": "Synthetic approved display",
            },
        }
    )
    evidence = catalog(
        *(
            c.model_copy(
                update=changes.get(c.chunk_id, {})
                | ({"doctor_name": "Same literal label"} if same_labels and c.doctor_id else {})
            )
            for c in original.chunks.values()
        )
    )
    plan = plan.model_copy(update={"prepared_digest": evidence.prepared_digest})
    authority = authority.model_copy(update={"prepared_digest": evidence.prepared_digest})
    return HoursRagWorkflow(
        settings=screen_settings(profile="local_constraints", output_cap=screen.OUTPUT_CAP),
        chat=chat,
        retriever=screen._NoDownstream(),
        counter=screen._NoDownstream(),
        catalog=evidence,
        directory_authority=authority,
        hours_plan=plan,
        expected_hours_plan_digest=hours_plan_digest(plan),
        clock=lambda: NOW,
        planner_output_tokens=screen.OUTPUT_CAP,
        hours_profile=profile,
    )


def test_explicit_relationships_retain_all_subjects_literal_labels_scopes_and_witnesses():
    workflow = compose(screen._CaptureChat())
    old = json.loads(workflow.hours_bindings.manifest_json)
    candidate = json.loads(workflow._hours_manifest_json)
    assert candidate["subjects"] == old["subjects"]
    group = candidate["identity_metadata"]["groups"][0]
    subjects = workflow.hours_bindings.subjects
    assert subjects[group["canonical_subject_handle"]].id == "confirmed-one"
    assert group["approved_display_name"] == "Synthetic approved display"
    assert len(group["literal_members"]) == 2
    for member in group["literal_members"]:
        subject = subjects[member["subject_handle"]]
        assert subject.owner_kind == "literal"
        assert workflow._bindings.owners[member["owner_handle"]] == ("literal", subject.id)
        for witness in member["metadata_witnesses"]:
            chunk = workflow._catalog.chunks[witness["chunk_id"]]
            assert workflow._bindings.documents[witness["document_handle"]] == chunk.document_id
            assert chunk.doctor_id == subject.id
            assert chunk.canonical_doctor_id == "confirmed-one"
            assert member["literal_labels"] == [chunk.doctor_name]
        assert workflow._catalog.scope_members(
            SourceScope(owner_id=subject.id, owner_kind="literal")
        ) == tuple(w["chunk_id"] for w in member["metadata_witnesses"])
        assert not workflow.hours_bindings.engine.records_for(subject)
    assert not workflow.hours_bindings.engine.records_for(
        subjects[group["canonical_subject_handle"]]
    )


@pytest.mark.parametrize("same_labels", [False, True])
def test_unconfirmed_owners_remain_separate_despite_identical_labels_or_specialty(same_labels):
    workflow = compose(screen._CaptureChat(), updates={}, same_labels=same_labels)
    manifest = json.loads(workflow._hours_manifest_json)
    assert manifest["identity_metadata"]["groups"] == []
    doctors = [s for s in workflow.hours_bindings.subjects.values() if s.kind == "doctor"]
    assert {(s.id, s.owner_kind) for s in doctors} == {("a", "literal"), ("b", "literal")}


def test_distinct_confirmed_people_are_never_merged_by_display_name():
    workflow = compose(
        screen._CaptureChat(),
        updates={
            "synthetic-chunk-1": {
                "canonical_doctor_id": "one",
                "canonical_doctor_name": "Same approved display",
            },
            "synthetic-chunk-2": {
                "canonical_doctor_id": "two",
                "canonical_doctor_name": "Same approved display",
            },
        },
        same_labels=True,
    )
    groups = json.loads(workflow._hours_manifest_json)["identity_metadata"]["groups"]
    assert len(groups) == 2
    assert len({g["canonical_subject_handle"] for g in groups}) == 2
    assert all(len(g["literal_members"]) == 1 for g in groups)


@pytest.mark.parametrize(
    "changes",
    [
        {"canonical_doctor_id": "one"},
        {"canonical_doctor_name": "One"},
        {"canonical_doctor_id": "one", "canonical_doctor_name": ""},
        {"canonical_doctor_id": "one", "canonical_doctor_name": "One", "doctor_name": None},
    ],
)
def test_partial_identity_metadata_is_refused(changes):
    with pytest.raises(ValueError):
        compose(screen._CaptureChat(), updates={"synthetic-chunk-1": changes})


@pytest.mark.parametrize("conflict", ["canonical_name", "literal_target"])
def test_conflicting_identity_metadata_is_refused_without_majority_vote(conflict):
    first = {"canonical_doctor_id": "one", "canonical_doctor_name": "One"}
    second = (
        {"canonical_doctor_id": "one", "canonical_doctor_name": "Different"}
        if conflict == "canonical_name"
        else {"doctor_id": "a", "canonical_doctor_id": "two", "canonical_doctor_name": "Two"}
    )
    with pytest.raises(ValueError, match="hours_identity_metadata_inconsistent"):
        compose(
            screen._CaptureChat(),
            updates={"synthetic-chunk-1": first, "synthetic-chunk-2": second},
        )


def test_manifest_bound_remains_enforced_after_metadata_projection():
    workflow = compose(screen._CaptureChat())
    workflow.hours_bindings.manifest_json = json.dumps({"subjects": [], "padding": "x" * 96000})
    with pytest.raises(ValueError, match="hours_manifest_exceeds_bound"):
        identity_hours_manifest(workflow.hours_bindings, workflow._bindings)


@pytest.mark.parametrize(
    "language,text", [("en", "When does the doctor work?"), ("ar", "متى يعمل الطبيب؟")]
)
def test_candidate_wire_diff_is_only_version_and_hours_metadata(language, text):
    async def capture(profile):
        chat = screen._CaptureChat()
        workflow = compose(chat, profile=profile)
        packet = {
            "case_id": "H11-" + language,
            "payload_sha256": "synthetic-not-dispatched",
            "request": {"query": text, "language": language, "history": []},
        }
        # Capture the real planning node through the same bounded runner.
        await screen.run_packet(packet, workflow, workflow._settings)
        return screen.wire_payload(chat.messages, workflow._settings)

    before = asyncio.run(capture("v12"))
    after = asyncio.run(capture("identity_links_v13"))
    assert before["messages"][0] == after["messages"][0]
    old = json.loads(before["messages"][1]["content"])
    new = json.loads(after["messages"][1]["content"])
    assert old.pop("prompt_version") != new.pop("prompt_version")
    old_hours, new_hours = old.pop("hours_manifest"), new.pop("hours_manifest")
    assert old == new and old_hours["subjects"] == new_hours["subjects"]
    before.pop("messages")
    after.pop("messages")
    assert before == after


@pytest.mark.parametrize("owner_kind", ["canonical", "literal", "wrong_literal_scope"])
def test_actual_adapter_validation_keeps_missing_hours_unknown_and_refuses_cross_owner(owner_kind):
    config = screen_settings(profile="local_constraints", output_cap=screen.OUTPUT_CAP)
    text = "When does Synthetic A work?"

    async def run():
        def handler(request):
            group = json.loads(workflow._hours_manifest_json)["identity_metadata"]["groups"][0]
            member = group["literal_members"][0]
            handle = (
                group["canonical_subject_handle"]
                if owner_kind != "literal"
                else member["subject_handle"]
            )
            owner = (
                group["canonical_owner_handle"]
                if owner_kind == "canonical"
                else member["owner_handle"]
            )
            supplied = inputs(
                workflow, kind="doctor", subject_text="Synthetic A", subject_handle=handle
            )
            return wire(
                HoursPlannerReply(
                    language="en", parts=(hours_part(text, supplied, owner_handle=owner),)
                )
            )

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            workflow = compose(providers.chat)
            row = await screen.run_packet(
                {
                    "case_id": "H11-en",
                    "payload_sha256": "synthetic-not-dispatched",
                    "request": {"query": text, "language": "auto", "history": []},
                },
                workflow,
                config,
            )
        assert row["physical_attempts"] == 1
        if owner_kind == "wrong_literal_scope":
            assert row["error_code"] == "invalid_hours_input"
        else:
            assert row["literal_bindings_valid"]
            assert row["computed_hours"][0]["assessment"]["status"] == "unknown"
            assert row["computed_hours"][0]["assessment"]["reason"] == "missing_hours"

    asyncio.run(run())


def test_unknown_profile_refused():
    with pytest.raises(ValueError, match="hours_profile_invalid"):
        compose(screen._CaptureChat(), profile="unreviewed")
