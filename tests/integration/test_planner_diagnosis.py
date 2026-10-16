"""Independent synthetic consumer probes, with socket protection and forbidden services."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from test_offline_workflow import catalog, part, source

from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import PlannerReply, WorkflowRequest

sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts import diagnose_planner_failures as diagnostic
from scripts.diagnose_planner_failures import consumer_probe, trace_output


def setup(query, chunks, **changes):
    request = WorkflowRequest(query=query)
    evidence = catalog(*chunks)
    bindings = SourceBindings(evidence, include_block_types=True)
    numeric = PlannerReply(language="en", parts=(part(query, **changes),))
    fields = numeric.parts[0].model_dump(exclude={"start", "end"}, mode="json")
    proposal = AnchoredPlannerReply.model_validate_json(
        json.dumps(
            {
                "language": "en",
                "parts": [{**fields, "original_text": query, "constraint_quotes": []}],
            }
        )
    )
    return request, proposal, bindings, evidence


def probe(values, candidates):
    return asyncio.run(consumer_probe(*values, candidates))


@pytest.mark.parametrize(
    "query", ["Report the published fee notice.", "انقل توضيح الرسوم المنشور."]
)
@pytest.mark.parametrize(
    "use,expected",
    [
        ("consultation_eligibility", "unknown"),
        ("general_excerpt", "candidate"),
        ("service_description", "candidate"),
    ],
)
def test_fee_policy_effect_is_independent_of_request_wording(query, use, expected):
    fee = source(1).model_copy(
        update={"source_issue_codes": ("consultation_fee_offer_reconciliation_unverified",)}
    )
    values = setup(query, [fee], intended_use=use)
    original = values[1].model_dump_json()
    result = probe(values, [[fee.chunk_id]])
    assert result["result"]["parts"][0]["status"] == expected
    assert result["semantic_support_assessed"] is False
    assert result["fixture_draft_only"] and result["model_and_retrieval_calls"] == 0
    assert values[1].model_dump_json() == original


def test_valid_language_enum_with_impossible_source_scope_passes_then_filters_everything():
    item = source(1).model_copy(update={"language": "en"})
    values = setup("Read the exact English source.", [item], source_language="ar")
    trace = trace_output(*values[:2], values[2], values[3], "synthetic")
    assert trace["literal_valid"] and trace["parts"][0]["scope_members"] == []
    result = probe(values, [[item.chunk_id]])
    assert result["after_assembly_route"] == "safe"
    assert result["assembly_receipts"][0]["candidate_status"] == "scope_filtered"
    assert result["result"]["parts"][0]["reason_code"] == "not_found"


def test_authored_irrelevant_quote_can_pass_structural_draft_validation_without_semantic_proof():
    fee = source(1, "Synthetic fee notice, not offer applicability.").model_copy(
        update={"source_issue_codes": ("consultation_fee_offer_reconciliation_unverified",)}
    )
    unrelated = source(2, "Synthetic tree specimen grows in shade.")
    values = setup(
        "Report the synthetic fee notice.",
        [fee, unrelated],
        intended_use="consultation_eligibility",
    )
    result = probe(values, [[fee.chunk_id, unrelated.chunk_id]])
    assert result["allowed_quote_chunk_ids"] == [[unrelated.chunk_id]]
    assert result["result"]["outcome"] == "draft_ready"
    assert result["result"]["parts"][0]["quotes"][0]["quote"] == unrelated.retrieval_text
    assert not result["semantic_support_assessed"]
    # This fixture is deliberately irrelevant; the test asserts the validator's
    # documented limit, not a semantic pass or that a real model would choose it.


@pytest.mark.parametrize(
    "use,expected", [("doctor_role", "unknown"), ("general_excerpt", "candidate")]
)
def test_literal_derivative_reporting_and_role_assertion_have_different_policy_effects(
    use, expected
):
    doctor = source(1, "Synthetic Person A: published role wording.").model_copy(
        update={
            "block_type": "doctor",
            "doctor_id": "synthetic-owner-a",
            "doctor_name": "Person A",
            "source_issue_codes": ("department_titles_non_authoritative_use_explicit_roles",),
        }
    )
    values = setup("Report only the wording of this synthetic page.", [doctor], intended_use=use)
    result = probe(values, [[doctor.chunk_id]])
    assert result["result"]["parts"][0]["status"] == expected


def test_outside_constraint_blocks_consumer_and_joint_target_remains_representable():
    values = setup("Compare A and B; use only the source.", [source(1)])
    request, proposal, bindings, evidence = values
    original = proposal.model_dump(mode="json")
    first = {
        **original["parts"][0],
        "original_text": "Compare A",
        "retrieval_query": request.query,
        "constraint_quotes": ["use only the source."],
    }
    second = {
        **original["parts"][0],
        "original_text": " and B; use only the source.",
        "retrieval_query": " and B; use only the source.",
    }
    broken = AnchoredPlannerReply.model_validate_json(
        json.dumps({"language": "en", "parts": [first, second]})
    )
    blocked = probe(
        (request, broken, bindings, evidence), [["synthetic-chunk-1"], ["synthetic-chunk-1"]]
    )
    assert (
        blocked["error"] == "constraint_outside_original_part" and not blocked["consumer_entered"]
    )
    repaired_fixture = probe(values, [["synthetic-chunk-1"]])
    assert repaired_fixture["literal_valid"]


def test_joint_doctor_fixture_preserves_both_distinct_owners_in_validated_quotes():
    doctors = [
        source(i).model_copy(
            update={
                "block_type": "doctor",
                "doctor_id": f"owner-{i}",
                "doctor_name": f"Synthetic Person {i}",
            }
        )
        for i in (1, 2)
    ]
    values = setup(
        "Compare both synthetic people; keep owners separate.", doctors, intended_use="doctor_role"
    )
    result = probe(values, [[d.chunk_id for d in doctors]])
    quotes = result["result"]["parts"][0]["quotes"]
    assert {q["literal_owner_id"] for q in quotes} == {"owner-1", "owner-2"}


def test_nonpublic_candidate_injection_is_rejected_before_assembly():
    values = setup(
        "Book a synthetic visit.",
        [source(1)],
        state="excluded",
        retrieval_query=None,
        reason="Synthetic excluded action",
    )
    with pytest.raises(ValueError, match="candidate_membership"):
        probe(values, [["synthetic-chunk-1"]])


def test_candidate_part_inventory_is_exact():
    values = setup("Read a synthetic statement.", [source(1)])
    with pytest.raises(ValueError, match="part_inventory"):
        probe(values, [])


def test_relative_scenario_path_serializes_and_repeat_output_is_refused(tmp_path, monkeypatch):
    request, proposal, bindings, evidence = setup("Read a synthetic statement.", [source(1)])
    capture = tmp_path / "capture/control/synthetic"
    capture.mkdir(parents=True)
    (capture / "synthetic.json").write_text(
        json.dumps(
            {
                "proposal": proposal.model_dump(mode="json"),
                "literal_bindings_valid": True,
                "error_code": None,
            }
        ),
        encoding="utf-8",
    )
    original = {
        "prepared_digest": evidence.prepared_digest,
        "code_sha256": {},
        "packets": [
            {
                "case_id": "synthetic",
                "arm": "control",
                "request": request.model_dump(mode="json"),
                "payload_sha256": "synthetic-payload-hash",
            }
        ],
    }
    spec = {
        "scenarios": [
            {
                "id": "synthetic-probe",
                "case_id": "synthetic",
                "arm": "control",
                "purpose": "Synthetic CLI receipt check",
                "candidates_by_part": [["synthetic-chunk-1"]],
            }
        ]
    }
    (tmp_path / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    monkeypatch.setattr(diagnostic, "CAPTURE", Path("capture"))
    monkeypatch.setattr(
        diagnostic, "authenticate", lambda root: (original, evidence, {"control": bindings}, {})
    )
    monkeypatch.chdir(tmp_path)
    asyncio.run(diagnostic.diagnose(tmp_path, tmp_path / "output", Path("spec.json")))
    saved = json.loads((tmp_path / "output/inputs.json").read_bytes())
    assert saved["scenarios_path"] == "spec.json" and saved["model_requests"] == 0
    with pytest.raises(FileExistsError):
        asyncio.run(diagnostic.diagnose(tmp_path, tmp_path / "output", Path("spec.json")))
