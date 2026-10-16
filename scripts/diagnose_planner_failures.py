"""Offline consumer-path diagnosis of sealed planner captures, never a semantic judge.

Saved outputs and explicitly authored counterfactuals are injected into existing
validation/assembly/draft-validation functions. No model, retriever, credentials,
provider adapter or index is invoked. Fixture drafts do not measure Luna behavior.
"""

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from scripts.retrieval_benchmark import load_corpus
from telescope_rag.core.settings import Settings
from telescope_rag.graph.anchoring import AnchoredPlannerReply, resolve_anchored_plan
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft, WorkflowRequest
from telescope_rag.graph.target_context import bind_answer_targets
from telescope_rag.graph.workflow import OfflineRagWorkflow
from telescope_rag.ingestion.admission import AdmissionPlan
from telescope_rag.knowledge.source_authority import reviewed_directory_authority
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.retrieval.assembly import EvidenceCatalog, limited_to_context

CAPTURE = Path("artifacts/m5-source-metadata-comparison-v1")
SEAL_SHA256 = "1bd85ba74eb663223ad9791d2bc46a0bc11d5d2bfe080b1d891184248a36b807"
SOURCE = Path("data/processed/m3-llm-semantic-token-validated-v6")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def diagnostic_settings() -> Settings:
    values = {n: f.get_default(call_default_factory=True) for n, f in Settings.model_fields.items()}
    values.update(app_env="test", openrouter_api_key="synthetic-unused-offline-diagnosis")
    return Settings(_env_file=None, **values)


class FixturePackingCounter:
    """One synthetic packing unit; never a model token estimate or production counter."""

    verified = True
    version = "synthetic-diagnosis-no-packing-pressure-not-model-tokens"

    def count(self, text: str) -> int:
        return 1


class ForbiddenService:
    async def complete(self, *args, **kwargs):
        raise AssertionError("Offline diagnosis must not invoke a model")

    async def retrieve(self, *args, **kwargs):
        raise AssertionError("Offline diagnosis must not invoke retrieval")


def validate_output(request, proposal, bindings, identity):
    derived, anchors = resolve_anchored_plan(proposal, request, identity)
    targets = bind_answer_targets(proposal, anchors)
    plan = bindings.validate(derived, request, identity, max_parts=4)
    return plan, anchors, targets


def trace_output(request, proposal, bindings, catalog, identity):
    """Literal/scope/policy effects only. Never judges a target's meaning."""
    try:
        plan, anchors, targets = validate_output(request, proposal, bindings, identity)
    except ValueError as error:
        return {"literal_valid": False, "error": str(error), "parts": []}
    parts = []
    for i, part in enumerate(plan.assembly_request.parts):
        members = catalog.scope_members(part.scope) if part.state == "public" else ()
        contextual = [
            k for k in members if limited_to_context(catalog.chunks[k], part.intended_use)
        ]
        parts.append(
            {
                "part_number": i + 1,
                "state": part.state,
                "intended_use": part.intended_use,
                "original_text": request.query[part.start : part.end],
                "retrieval_query": proposal.parts[i].retrieval_query,
                "scope": part.scope.model_dump(mode="json"),
                "scope_members": list(members),
                "context_only_scope_members": contextual,
                "potential_support_scope_members": [k for k in members if k not in contextual],
                "caution": "Membership/eligibility is not relevance or entailment; "
                "nonpublic parts never retrieve.",
            }
        )
    return {
        "literal_valid": True,
        "error": None,
        "parts": parts,
        "anchors": [asdict(a) for a in anchors],
        "answer_targets": [asdict(t) for t in targets],
    }


async def consumer_probe(request, proposal, bindings, catalog, candidates, *, identity="diagnosis"):
    """Probe existing post-plan functions with authored candidate/draft fixtures.

    No plan is repaired, no retrieval ranking is simulated, and no fixture result
    is a measured model response. The v6 consumer has identical handle validation
    with or without reviewed input roles, authenticated separately by the caller.
    """
    try:
        plan, anchors, targets = validate_output(request, proposal, bindings, identity)
    except ValueError as error:
        return {"literal_valid": False, "error": str(error), "consumer_entered": False}
    if len(candidates) != len(plan.assembly_request.parts):
        raise ValueError("diagnostic_candidate_part_inventory_mismatch")
    for part, ids in zip(plan.assembly_request.parts, candidates, strict=True):
        if (part.state != "public" and ids) or any(k not in catalog.chunks for k in ids):
            raise ValueError("diagnostic_candidate_membership_invalid")
    config = diagnostic_settings()
    flow = OfflineRagWorkflow(
        settings=config,
        chat=ForbiddenService(),
        retriever=ForbiddenService(),
        catalog=catalog,
        counter=FixturePackingCounter(),
        token_basis="synthetic_test",
        planner_profile="policy_targets",
    )
    context = SimpleNamespace(
        request_id=identity,
        budget=ExecutionBudget(config),
        stages=[],
        plan=plan,
        evidence=None,
        request_anchors=anchors,
        answer_targets=targets,
    )
    runtime = SimpleNamespace(context=context)
    supplied = {
        p.part_id: tuple(ids)
        for p, ids in zip(plan.assembly_request.parts, candidates, strict=True)
    }
    state = {"request": request, "plan": plan, "candidates": supplied}
    state.update(await flow._assemble_evidence(state, runtime))
    evidence = state["evidence"]
    allowed = [flow._allowed(plan, evidence, i) for i in range(len(plan.assembly_request.parts))]
    route = flow._after_assembly(state)
    if route == "draft":
        entries = []
        for i, part in enumerate(plan.assembly_request.parts):
            safe = flow._safe_part(plan, evidence, i)
            entries.append(
                PartDraft(
                    part_id=part.part_id,
                    status="candidate" if allowed[i] else safe.status,
                    quotes=tuple(
                        QuoteDraft(chunk_id=k, quote=catalog.chunks[k].retrieval_text)
                        for k in allowed[i]
                    ),
                    reason_code=None if allowed[i] else safe.reason_code,
                )
            )
        state["draft"] = AnswerDraft(parts=tuple(entries))
        final = await flow._validate_draft(state, runtime)
    else:
        final = await flow._finalize_safe(state, runtime)
    return {
        "literal_valid": True,
        "error": None,
        "consumer_entered": True,
        "after_assembly_route": route,
        "allowed_quote_chunk_ids": [list(a) for a in allowed],
        "assembly_receipts": [asdict(p) for p in evidence.parts],
        "result": final["result"].model_dump(mode="json"),
        "stages_actually_exercised": context.stages,
        "semantic_support_assessed": evidence.semantic_support_assessed,
        "fixture_draft_only": True,
        "model_and_retrieval_calls": 0,
        "packing": "synthetic_test, one fixture unit; no model token estimate or budget conclusion",
    }


def authenticate(root: Path):
    seal = root / CAPTURE / "evidence-seal.json"
    if digest(seal) != SEAL_SHA256:
        raise ValueError("diagnostic_capture_seal_changed")
    inventory = json.loads(seal.read_bytes())["files"]
    for name, expected in inventory.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or digest(path) != expected:
            raise ValueError("diagnostic_sealed_file_changed")
    original = json.loads((root / CAPTURE / "plan.json").read_bytes())
    for name, expected in original["code_sha256"].items():
        if digest(root / name) != expected:
            raise ValueError("diagnostic_executed_code_changed")
    documents, _ = load_corpus(root / SOURCE)
    catalog = EvidenceCatalog(documents, expected_digest=original["prepared_digest"])
    authority = reviewed_directory_authority(
        AdmissionPlan.model_validate_json(
            (root / SOURCE / "metadata/source-admission-plan.json").read_bytes()
        ),
        json.loads((root / SOURCE / "metadata/primary-directory.json").read_bytes()),
        prepared_digest=catalog.prepared_digest,
    )
    plain = SourceBindings(catalog, include_block_types=True)
    roles = SourceBindings(catalog, include_block_types=True, directory_authority=authority)
    return original, catalog, {"control": plain, "source_metadata_only": roles}, inventory


async def diagnose(root: Path, output: Path, scenario_path: Path):
    root = await asyncio.to_thread(root.resolve)
    scenario_path = await asyncio.to_thread((root / scenario_path).resolve)
    if not scenario_path.is_relative_to(root):
        raise ValueError("diagnostic_scenario_outside_workspace")
    original, catalog, bindings, inventory = await asyncio.to_thread(authenticate, root)
    specifications = json.loads(await asyncio.to_thread(scenario_path.read_bytes))["scenarios"]
    if (
        not specifications
        or len(specifications) > 100
        or len({s["id"] for s in specifications}) != len(specifications)
    ):
        raise ValueError("diagnostic_scenario_inventory_invalid")
    packets = {(p["case_id"], p["arm"]): p for p in original["packets"]}
    traces = []
    captures = {}
    for key, packet in packets.items():
        path = root / CAPTURE / key[1] / key[0] / f"{key[0]}.json"
        actual = json.loads(path.read_bytes())
        request = WorkflowRequest.model_validate_json(json.dumps(packet["request"]))
        proposal = AnchoredPlannerReply.model_validate_json(json.dumps(actual["proposal"]))
        captures[key] = request, proposal
        trace = trace_output(request, proposal, bindings[key[1]], catalog, key[0])
        if (
            trace["literal_valid"] != actual["literal_bindings_valid"]
            or trace["error"] != actual["error_code"]
        ):
            raise ValueError("diagnostic_replay_disagrees_with_capture")
        # Input roles do not change the implemented post-plan consumer projection.
        if trace != trace_output(request, proposal, bindings["control"], catalog, key[0]):
            raise ValueError("diagnostic_post_plan_binding_effect_changed")
        traces.append(
            {
                "case_id": key[0],
                "arm": key[1],
                "result_sha256": digest(path),
                "payload_sha256": packet["payload_sha256"],
                **trace,
            }
        )
    probes = []
    for spec in specifications:
        key = spec["case_id"], spec["arm"]
        if key not in captures:
            raise ValueError("diagnostic_unknown_capture")
        request, actual = captures[key]
        original_before = actual.model_dump_json()
        data = actual.model_dump(mode="json")
        if spec.get("whole_query_joint_target"):
            part = data["parts"][spec.get("part_index", 0)]
            part.update(
                original_text=request.query,
                retrieval_query=request.query,
                constraint_quotes=[],
                reference_text=None,
                history_indices=[],
            )
            data["parts"] = [part]
        for edit in spec.get("edits", []):
            index = edit["part_index"]
            fields = edit["fields"]
            if not set(fields) <= {
                "intended_use",
                "document_handles",
                "source_language",
                "block_types",
            }:
                raise ValueError("diagnostic_unsupported_counterfactual_field")
            data["parts"][index].update(fields)
        variant = AnchoredPlannerReply.model_validate_json(json.dumps(data))
        result = await consumer_probe(
            request,
            variant,
            bindings[key[1]],
            catalog,
            spec["candidates_by_part"],
            identity=spec["id"],
        )
        probes.append(
            {
                "id": spec["id"],
                "case_id": key[0],
                "arm": key[1],
                "author_supplied_purpose": spec["purpose"],
                "counterfactual": variant != actual,
                "exact_diagnostic_proposal": variant.model_dump(mode="json"),
                **result,
            }
        )
        if actual.model_dump_json() != original_before:
            raise ValueError("diagnostic_original_proposal_mutated")
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False)
    write_new(
        output / "mechanical-traces.json",
        {
            "requests": len(traces),
            "traces": traces,
            "new_semantic_judgments_by_script": 0,
            "scope": "All 96 saved outputs mechanically replayed; "
            "no model rerun or new semantic certification.",
        },
    )
    write_new(
        output / "consumer-probes.json",
        {
            "probes": probes,
            "fixture_only": True,
            "interpretation": "Conditional consequences for authored candidate/draft fixtures. "
            "Not actual ranking, model drafting, answer quality or proposed runtime repair.",
        },
    )
    write_new(
        output / "inputs.json",
        {
            "capture_seal_sha256": SEAL_SHA256,
            "sealed_files": len(inventory),
            "source_prepared_digest": catalog.prepared_digest,
            "catalog_chunks": len(catalog.chunks),
            "scenarios_sha256": digest(scenario_path),
            "scenarios_path": scenario_path.relative_to(root).as_posix(),
            "diagnosis_script_sha256": digest(Path(__file__)),
            "prior_executed_code_files": len(original["code_sha256"]),
            "model_requests": 0,
            "embedding_requests": 0,
            "qdrant_requests": 0,
            "source_fetches": 0,
            "post_plan_binding_projections_equal": len(traces),
            "runtime_src_changed": False,
        },
    )
    print(
        json.dumps(
            {
                "mechanical_captures": len(traces),
                "consumer_probes": len(probes),
                "provider_requests": 0,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenarios", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(diagnose(Path.cwd(), args.output, args.scenarios))


if __name__ == "__main__":
    main()
