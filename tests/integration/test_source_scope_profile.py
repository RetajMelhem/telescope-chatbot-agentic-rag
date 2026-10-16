"""Reviewed metadata/ownership contracts, not semantic scoring or real requests."""

import asyncio
import json
import sys
from pathlib import Path

import httpx2 as httpx
import pytest
from test_anchored_workflow import part, wire
from test_offline_workflow import FakeRetriever, SyntheticCounter, catalog
from test_offline_workflow import source as base_source

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts import run_source_scope_screen as screen
from scripts.run_luna_planner_screen import development_packets, planner_payload, screen_settings
from telescope_rag.core.settings import Settings
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft, WorkflowRequest
from telescope_rag.graph.planning import planner_messages
from telescope_rag.graph.workflow import OfflineRagWorkflow, WorkflowError
from telescope_rag.ingestion.admission import AdmissionPlan, admission_hash
from telescope_rag.ingestion.models import PreparedChunk
from telescope_rag.knowledge.source_authority import (
    DirectoryAuthority,
    reviewed_directory_authority,
)
from telescope_rag.providers.openrouter import OpenRouterProviders


def source(number, text, *, block_type, **changes):
    return PreparedChunk.model_validate(
        base_source(number, text, **changes).model_dump() | {"block_type": block_type}
    )


def fixtures():
    items = (
        source(
            1,
            "Synthetic primary role.",
            document="main",
            block_type="doctor",
            doctor_id="a",
            doctor_name="Synthetic Person A",
        ),
        source(
            2,
            "Synthetic derivative wording.",
            document="derivative",
            block_type="doctor",
            doctor_id="b",
            doctor_name="Synthetic Person B",
            source_issue_codes=("department_titles_non_authoritative_use_explicit_roles",),
        ),
        source(
            3,
            "Synthetic separate fee; details before proceeding.",
            document="faq",
            block_type="faq",
        ),
    )
    evidence = catalog(*items)
    authority = DirectoryAuthority(
        prepared_digest=evidence.prepared_digest,
        admission_policy_hash="synthetic-policy",
        primary_directory_document_ids=("main",),
    )
    return items, evidence, authority


def admission():
    return AdmissionPlan(
        snapshot_id="synthetic",
        collection_digest="synthetic",
        input_prepared_digest="synthetic",
        decision_authority="synthetic-review",
        decision_notes=(),
        primary_directory_document_ids=("main",),
        units=(),
    )


@pytest.mark.parametrize("tamper", [None, "digest", "policy", "membership", "duplicate", "type"])
def test_projected_authority_requires_exact_reviewed_metadata(tamper):
    plan = admission()
    metadata = {
        "prepared_digest": "synthetic-digest",
        "policy_hash": admission_hash(plan),
        "pages": [{"document_id": "main"}],
    }
    if tamper == "digest":
        metadata["prepared_digest"] = "wrong"
    elif tamper == "policy":
        metadata["policy_hash"] = "wrong"
    elif tamper == "membership":
        metadata["pages"] = [{"document_id": "derivative"}]
    elif tamper == "duplicate":
        metadata["pages"] *= 2
    elif tamper == "type":
        metadata["pages"] = ["main"]
    if tamper:
        with pytest.raises(ValueError, match="directory_authority_.*mismatch"):
            reviewed_directory_authority(plan, metadata, prepared_digest="synthetic-digest")
    else:
        result = reviewed_directory_authority(plan, metadata, prepared_digest="synthetic-digest")
        assert result.primary_directory_document_ids == ("main",)
        assert result.admission_policy_hash == admission_hash(plan)


@pytest.mark.parametrize(
    "tamper", ["digest", "policy", "unknown", "duplicate", "nondoctor", "derivative"]
)
def test_authority_cannot_relabel_unknown_or_conflicting_catalog_membership(tamper):
    _, evidence, authority = fixtures()
    changes = {
        "digest": {"prepared_digest": "wrong"},
        "policy": {"admission_policy_hash": "wrong"},
        "unknown": {"primary_directory_document_ids": ("unknown",)},
        "duplicate": {"primary_directory_document_ids": ("main", "main")},
        "nondoctor": {"primary_directory_document_ids": ("faq",)},
        "derivative": {"primary_directory_document_ids": ("derivative",)},
    }
    with pytest.raises(ValueError, match="^directory_authority_catalog_mismatch$"):
        SourceBindings(evidence, directory_authority=authority.model_copy(update=changes[tamper]))


def test_roles_are_explicit_metadata_and_old_manifests_are_unchanged():
    _, evidence, authority = fixtures()
    plain = SourceBindings(evidence, include_block_types=True)
    scoped = SourceBindings(evidence, include_block_types=True, directory_authority=authority)
    old, new = (json.loads(b.manifest_json) for b in (plain, scoped))
    assert old["owners"] == new["owners"] and plain.documents == scoped.documents
    roles = {scoped.documents[d["handle"]]: d.pop("source_role") for d in new["documents"]}
    assert roles == {
        "main": "approved_primary_doctor_directory",
        "derivative": "derivative_directory_titles_non_authoritative",
        "faq": "unclassified",
    }
    assert new.pop("source_role_basis")["role_is_not_question_relevance_or_factual_support"] is True
    assert old == new
    with pytest.raises(ValueError, match="^source_scoped_requires_directory_authority$"):
        planner_messages(
            WorkflowRequest(query="Synthetic query."), plain, max_parts=4, profile="source_scoped"
        )


@pytest.mark.parametrize(
    "language,query",
    [
        ("en", "Report this named source only."),
        ("ar", "انقل هذه الصفحة المحددة فقط."),
        ("ar-JO", "بدي هالصفحة المحددة بس."),
    ],
)
@pytest.mark.parametrize("use", ["general_excerpt", "doctor_role"])
def test_explicit_derivative_reporting_does_not_replace_source_or_override_policy(
    language, query, use
):
    async def run():
        items, evidence, authority = fixtures()
        bindings = SourceBindings(evidence, include_block_types=True, directory_authority=authority)
        derivative_handle = next(h for h, i in bindings.documents.items() if i == "derivative")
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        retriever = FakeRetriever(lambda i, q: (items[0].chunk_id, items[1].chunk_id))
        seen = []

        def handler(request):
            payload = json.loads(request.read())
            body = json.loads(payload["messages"][-1]["content"])
            seen.append(payload)
            if payload["response_format"]["json_schema"]["name"] == "AnchoredPlannerReply":
                assert body["prompt_version"] == "offline-rag-planner-source-scope-v7"
                value = AnchoredPlannerReply(
                    language=language,
                    parts=(
                        part(
                            query,
                            intended_use=use,
                            document_handles=(derivative_handle,),
                            reason="Synthetic explicitly requested source.",
                        ),
                    ),
                )
            else:
                assert use == "general_excerpt"
                assert body["parts"][0]["eligible_quote_chunk_ids"] == [items[1].chunk_id]
                assert body["parts"][0]["answer_target"] == query
                value = AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=body["parts"][0]["part_id"],
                            status="candidate",
                            quotes=(
                                QuoteDraft(
                                    chunk_id=items[1].chunk_id, quote=items[1].retrieval_text
                                ),
                            ),
                            reason_code=None,
                        ),
                    )
                )
            return wire(value)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            result = await OfflineRagWorkflow(
                settings=config,
                chat=p.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="source_scoped",
                directory_authority=authority,
            ).run(WorkflowRequest(query=query, language="ar" if language == "ar-JO" else language))
        assert result.plan.assembly_request.parts[0].scope.document_ids == ("derivative",)
        assert len(result.answer_targets) == 1
        if use == "doctor_role":
            assert result.result.parts[0].status == "unknown" and len(seen) == 1
            assert result.result.parts[0].quotes == ()
        else:
            assert result.result.parts[0].quotes[0].literal_owner_id == "b" and len(seen) == 2
        assert not result.result.semantic_grounding_verified

    asyncio.run(run())


def test_candidate_wire_changes_only_messages_not_model_schema_reasoning_or_allowance():
    _, evidence, authority = fixtures()
    request = WorkflowRequest(query="Synthetic public request.")
    a = planner_payload(
        planner_messages(
            request,
            SourceBindings(evidence, include_block_types=True),
            max_parts=4,
            profile="policy_targets",
        ),
        screen_settings(profile="policy_targets", output_cap=4096),
        profile="policy_targets",
        output_cap=4096,
    )
    b = planner_payload(
        planner_messages(
            request,
            SourceBindings(evidence, include_block_types=True, directory_authority=authority),
            max_parts=4,
            profile="source_scoped",
        ),
        screen_settings(profile="source_scoped", output_cap=4096),
        profile="source_scoped",
        output_cap=4096,
    )
    assert {k: v for k, v in a.items() if k != "messages"} == {
        k: v for k, v in b.items() if k != "messages"
    }
    assert "reasoning" not in b


def fresh_fixture(root):
    d = root / screen.CASES
    d.mkdir(parents=True)
    rows = [
        {
            "case_id": f"S{i:02}-{lang}",
            "request": {"query": f"Synthetic {i} {lang}.", "history": [], "language": "en"},
            "review_criteria": "gold never sent",
            "witness": "gold-witness-never-sent",
        }
        for i in range(1, 5)
        for lang in ("ar", "ar-JO", "en")
    ]
    (d / "cases.json").write_text(json.dumps({"cases": rows}), encoding="utf-8")
    (d / "manifest.json").write_text(
        json.dumps({"files": {"cases.json": screen.file_hash(d / "cases.json")}}), encoding="utf-8"
    )
    return d, screen.file_hash(d / "manifest.json")


def test_fresh_contrasts_export_only_requests(tmp_path, monkeypatch):
    _, digest = fresh_fixture(tmp_path)
    monkeypatch.setattr(screen, "MANIFEST_SHA256", digest)
    cases = screen.frozen_cases(tmp_path)
    _, evidence, authority = fixtures()
    bindings = SourceBindings(evidence, include_block_types=True, directory_authority=authority)
    ids = tuple(c.case_id for c in cases)
    packets = development_packets(
        cases, bindings, profile="source_scoped", output_cap=4096, case_ids=ids, inventory=ids
    )
    for packet in packets:
        body = json.dumps(packet["payload"])
        assert "gold never sent" not in body and "gold-witness" not in body
        assert packet["case_id"] not in body


@pytest.mark.parametrize("tamper", ["manifest", "cases", "inventory", "escape"])
def test_fresh_tampering_stops_before_credentials(tmp_path, monkeypatch, tamper):
    d, digest = fresh_fixture(tmp_path)
    if tamper in {"manifest", "cases"}:
        (d / f"{tamper}.json").write_text("{}", encoding="utf-8")
    else:
        files = {"../outside.json": "wrong"}
        if tamper == "inventory":
            value = json.loads((d / "cases.json").read_bytes())
            value["cases"][0]["case_id"] = "PL02-en"
            (d / "cases.json").write_text(json.dumps(value), encoding="utf-8")
            files = {"cases.json": screen.file_hash(d / "cases.json")}
        (d / "manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
        digest = screen.file_hash(d / "manifest.json")
    monkeypatch.setattr(screen, "MANIFEST_SHA256", digest)
    with pytest.raises(ValueError, match="source_scope_.*changed"):
        screen.frozen_cases(tmp_path)


@pytest.mark.parametrize(
    "profile,authority_present", [("source_scoped", False), ("baseline", True)]
)
def test_offline_profile_requires_explicit_matching_authority_dependency(
    profile, authority_present
):
    _, evidence, authority = fixtures()
    config = Settings(_env_file=None, app_env="test")
    with pytest.raises(WorkflowError, match="offline_workflow_configuration_invalid"):
        OfflineRagWorkflow(
            settings=config,
            chat=None,
            retriever=None,
            catalog=evidence,
            counter=SyntheticCounter(),
            token_basis="synthetic_test",
            planner_profile=profile,
            directory_authority=authority if authority_present else None,
        )
