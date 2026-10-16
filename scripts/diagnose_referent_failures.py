"""Offline consumer replay of sealed v8/v9 outputs and explicit authored alternatives.

No provider client, credential loading, embedding, vector ranking or index access.
Synthetic candidate/draft dependencies probe mechanics; they never grade meaning.
"""

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scripts.diagnose_planner_failures import (
    FixturePackingCounter,
    diagnostic_settings,
    trace_output,
)
from scripts.retrieval_benchmark import load_corpus
from scripts.run_luna_planner_screen import file_hash, payload_hash, write_new
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import (
    AnswerDraft,
    PartDraft,
    QuoteDraft,
    RetrievalBatch,
    RetrievalQuery,
    RetrievedPart,
    WorkflowRequest,
)
from telescope_rag.graph.workflow import OfflineRagWorkflow
from telescope_rag.ingestion.admission import AdmissionPlan
from telescope_rag.knowledge.source_authority import (
    DirectoryAuthority,
    reviewed_directory_authority,
)
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import StructuredResult
from telescope_rag.retrieval.assembly import EvidenceCatalog

CAPTURE = Path("artifacts/m5-referent-comparison-v1")
SEAL_SHA256 = "8bd6f830b946c82da2618e04b70501f6ec25570033a7d4abca0c9042f37adb91"
SOURCE = Path("data/processed/m3-llm-semantic-token-validated-v6")
PROFILES = {"control": "purpose_contract", "referent_context": "referent_context"}
Profile = Literal["purpose_contract", "referent_context"]
EDIT_FIELDS = frozenset(
    {
        "original_text",
        "retrieval_query",
        "reference_text",
        "document_handles",
        "state",
        "block_types",
        "source_language",
        "reason",
    }
)


class PartEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    part_index: int = Field(ge=0, le=3)
    fields: dict[str, Any]

    @model_validator(mode="after")
    def known_fields(self):
        if not self.fields or not set(self.fields) <= EDIT_FIELDS:
            raise ValueError("unsupported_diagnostic_edit")
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: str = Field(min_length=1, max_length=100)
    case_id: str = Field(min_length=1, max_length=100)
    arm: Literal["control", "referent_context"]
    purpose: str = Field(min_length=20, max_length=2000)
    edits: tuple[PartEdit, ...] = ()
    candidates_by_part: tuple[tuple[str, ...], ...] = Field(min_length=1, max_length=4)


class Scenarios(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    scenarios: tuple[Scenario, ...] = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({s.id for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("duplicate_diagnostic_scenario")
        return self


def variant_of(actual: AnchoredPlannerReply, edits: tuple[PartEdit, ...]) -> AnchoredPlannerReply:
    """Explicit offline author edits only; never called by a serving workflow."""
    data = actual.model_dump(mode="json")
    for edit in edits:
        if edit.part_index >= len(data["parts"]):
            raise ValueError("diagnostic_edit_part_missing")
        data["parts"][edit.part_index].update(edit.fields)
    return AnchoredPlannerReply.model_validate_json(json.dumps(data))


class FixtureRetriever:
    def __init__(self, candidates: tuple[tuple[str, ...], ...], part_ids: tuple[str, ...]):
        self.by_id = dict(zip(part_ids, candidates, strict=True))
        self.calls: list[dict] = []

    async def retrieve(
        self,
        queries: Sequence[RetrievalQuery],
        *,
        snapshot_id: str,
        prepared_digest: str,
        budget: ExecutionBudget,
    ) -> RetrievalBatch:
        budget.remaining_seconds()
        self.calls.append({"queries": [q.model_dump(mode="json") for q in queries]})
        return RetrievalBatch(
            snapshot_id=snapshot_id,
            prepared_digest=prepared_digest,
            parts=tuple(
                RetrievedPart(part_id=q.part_id, chunk_ids=self.by_id[q.part_id]) for q in queries
            ),
        )


class FixtureDraft:
    def __init__(self):
        self.draft: AnswerDraft | None = None
        self.messages: list[dict] = []

    async def complete(self, messages, output_model, *, max_output_tokens, budget):
        budget.remaining_seconds()
        if output_model is not AnswerDraft or self.draft is None or self.messages:
            raise AssertionError("diagnostic_unexpected_chat_stage")
        self.messages = [m.model_dump(mode="json") for m in messages]
        return StructuredResult(self.draft, ())


def validate_candidates(
    proposal: AnchoredPlannerReply,
    catalog: EvidenceCatalog,
    candidates: tuple[tuple[str, ...], ...],
) -> None:
    if len(candidates) != len(proposal.parts):
        raise ValueError("diagnostic_candidate_part_inventory")
    if any(
        (part.state != "public" and ids)
        or len(set(ids)) != len(ids)
        or len(ids) > 8
        or any(i not in catalog.chunks for i in ids)
        for part, ids in zip(proposal.parts, candidates, strict=True)
    ):
        raise ValueError("diagnostic_candidate_membership")


async def consumer_probe(
    request: WorkflowRequest,
    proposal: AnchoredPlannerReply,
    catalog: EvidenceCatalog,
    authority: DirectoryAuthority,
    candidates: tuple[tuple[str, ...], ...],
    *,
    profile: Profile,
    identity: str,
    forced_quotes: tuple[tuple[str, ...], ...] | None = None,
) -> dict:
    """Run unchanged validation/retrieval-intake/assembly/draft nodes with local fixtures.

    Full source quotes are intentionally emitted by the fixture, even when an author
    identifies them as irrelevant. A mechanical pass is never semantic acceptance.
    """
    validate_candidates(proposal, catalog, candidates)
    if forced_quotes is not None and len(forced_quotes) != len(candidates):
        raise ValueError("diagnostic_candidate_part_inventory")
    config = diagnostic_settings()
    chat = FixtureDraft()
    retriever = FixtureRetriever(
        candidates, tuple(f"{identity}-p{i + 1}" for i in range(len(candidates)))
    )
    flow = OfflineRagWorkflow(
        settings=config,
        chat=chat,
        retriever=retriever,
        catalog=catalog,
        counter=FixturePackingCounter(),
        token_basis="synthetic_test",
        planner_profile=profile,
        directory_authority=authority,
    )
    context = SimpleNamespace(
        request_id=identity,
        budget=ExecutionBudget(config),
        stages=[],
        plan=None,
        evidence=None,
        request_anchors=(),
        answer_targets=(),
    )
    runtime = Runtime(context=context)
    state = {"request": request, "proposal": proposal}
    base = {
        "fixture_only": True,
        "profile": profile,
        "model_inference_requests": 0,
        "ranked_retrieval_executions": 0,
        "embedding_requests": 0,
        "qdrant_requests": 0,
        "synthetic_candidates_by_part": candidates,
        "packing_basis": "synthetic_test; one fixture packing unit, never Luna/Qwen token counting",
    }
    try:
        state.update(await flow._validate_plan(state, runtime))
    except ValueError as error:
        return {
            **base,
            "literal_valid": False,
            "error": str(error),
            "consumer_entered": False,
            "stages": context.stages,
            "fixture_retrieval_calls": [],
            "draft_messages": [],
        }
    plan = state["plan"]
    state.update(await flow._retrieve_evidence(state, runtime))
    state.update(await flow._assemble_evidence(state, runtime))
    evidence = state["evidence"]
    allowed = [flow._allowed(plan, evidence, i) for i in range(len(candidates))]
    route = flow._after_assembly(state)
    if route == "draft":
        parts = []
        for i, part in enumerate(plan.assembly_request.parts):
            safe = flow._safe_part(plan, evidence, i)
            ids = forced_quotes[i] if forced_quotes is not None else tuple(allowed[i])
            parts.append(
                PartDraft(
                    part_id=part.part_id,
                    status="candidate" if ids else safe.status,
                    quotes=tuple(
                        QuoteDraft(chunk_id=k, quote=catalog.chunks[k].retrieval_text) for k in ids
                    ),
                    reason_code=None if ids else safe.reason_code,
                )
            )
        chat.draft = AnswerDraft(parts=tuple(parts))
        state.update(await flow._generate_draft(state, runtime))
        try:
            final = await flow._validate_draft(state, runtime)
            result, error = final["result"].model_dump(mode="json"), None
        except ValueError as failure:
            result, error = None, str(failure)
    else:
        final = await flow._finalize_safe(state, runtime)
        result, error = final["result"].model_dump(mode="json"), None
    return {
        **base,
        "literal_valid": True,
        "consumer_entered": True,
        "error": error,
        "stages": context.stages,
        "fixture_retrieval_calls": retriever.calls,
        "request_anchors": [asdict(a) for a in context.request_anchors],
        "answer_targets": [asdict(a) for a in context.answer_targets],
        "allowed_quote_chunk_ids": [list(a) for a in allowed],
        "assembly_receipts": [asdict(p) for p in evidence.parts],
        "rendered_candidates": evidence.rendered_text,
        "draft_messages": chat.messages,
        "fixture_draft": chat.draft.model_dump(mode="json") if chat.draft else None,
        "after_assembly_route": route,
        "result": result,
        "semantic_support_assessed": evidence.semantic_support_assessed,
        "semantic_grade": None,
    }


def authenticate(root: Path) -> tuple[dict, EvidenceCatalog, DirectoryAuthority, dict]:
    root = root.resolve()
    seal = root / CAPTURE / "evidence-seal.json"
    if file_hash(seal) != SEAL_SHA256:
        raise ValueError("referent_diagnosis_seal_changed")
    files = json.loads(seal.read_bytes())["files"]
    for name, expected in files.items():
        target = (root / name).resolve()
        if not target.is_relative_to(root) or file_hash(target) != expected:
            raise ValueError("referent_diagnosis_sealed_file_changed")
    plan = json.loads((root / CAPTURE / "plan.json").read_bytes())
    for name, expected in plan["code_sha256"].items():
        if file_hash(root / name) != expected:
            raise ValueError("referent_diagnosis_executed_code_changed")
    source_hashes = json.loads(
        (
            root / "artifacts/m3-retrieval-benchmark-v1/authoring/source-input-hashes.json"
        ).read_bytes()
    )
    if len(source_hashes) != 122 or any(file_hash(root / p) != h for p, h in source_hashes.items()):
        raise ValueError("referent_diagnosis_source_changed")
    documents, _ = load_corpus(root / SOURCE)
    catalog = EvidenceCatalog(documents, expected_digest=plan["prepared_digest"])
    authority = reviewed_directory_authority(
        AdmissionPlan.model_validate_json(
            (root / SOURCE / "metadata/source-admission-plan.json").read_bytes()
        ),
        json.loads((root / SOURCE / "metadata/primary-directory.json").read_bytes()),
        prepared_digest=catalog.prepared_digest,
    )
    return plan, catalog, authority, files


async def diagnose(root: Path, output: Path, scenario_path: Path) -> None:
    root = await asyncio.to_thread(root.resolve)
    plan, catalog, authority, inventory = await asyncio.to_thread(authenticate, root)
    scenario_path = await asyncio.to_thread((root / scenario_path).resolve)
    if not scenario_path.is_relative_to(root):
        raise ValueError("referent_diagnosis_scenario_outside_workspace")
    specs = Scenarios.model_validate_json(scenario_path.read_bytes())
    if len(plan["packets"]) != 96:
        raise ValueError("referent_diagnosis_capture_inventory")
    bindings = SourceBindings(
        catalog, include_block_types=True, directory_authority=authority, purpose_contract=True
    )
    prior = {
        (t["case_id"], t["arm"]): t
        for t in json.loads((root / CAPTURE / "mechanical-source-policy-traces.json").read_bytes())[
            "traces"
        ]
    }
    captures, traces = {}, []
    for packet in plan["packets"]:
        key = packet["case_id"], packet["arm"]
        if (
            key in captures
            or packet["arm"] not in PROFILES
            or payload_hash(packet["payload"]) != packet["payload_sha256"]
        ):
            raise ValueError("referent_diagnosis_packet_binding")
        actual = json.loads((root / CAPTURE / key[1] / key[0] / f"{key[0]}.json").read_bytes())
        request = WorkflowRequest.model_validate_json(json.dumps(packet["request"]))
        proposal = AnchoredPlannerReply.model_validate_json(json.dumps(actual["proposal"]))
        captures[key] = request, proposal
        trace = {
            "case_id": key[0],
            "arm": key[1],
            **trace_output(request, proposal, bindings, catalog, key[0]),
        }
        # Dataclass tuples are serialized as JSON arrays in the sealed receipt.
        # Normalize containers only, preserving every literal string and value.
        trace = json.loads(json.dumps(trace, ensure_ascii=False, allow_nan=False))
        if trace != prior[key]:
            raise ValueError("referent_diagnosis_replay_changed")
        traces.append(trace)
    prepared = []
    # Authenticate every author-supplied alternative before any fixture node executes.
    for spec in specs.scenarios:
        if (spec.case_id, spec.arm) not in captures:
            raise ValueError("referent_diagnosis_unknown_capture")
        request, actual = captures[spec.case_id, spec.arm]
        variant = variant_of(actual, spec.edits)
        validate_candidates(variant, catalog, spec.candidates_by_part)
        prepared.append((spec, request, actual, variant))
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False)
    write_new(
        output / "inputs.json",
        {
            "capture_seal_sha256": SEAL_SHA256,
            "sealed_capture_files": len(inventory),
            "scenarios_path": scenario_path.relative_to(root).as_posix(),
            "scenarios_sha256": file_hash(scenario_path),
            "code_sha256": {
                p.relative_to(root).as_posix(): file_hash(p)
                for folder in ("src", "scripts")
                for p in sorted((root / folder).rglob("*.py"))
            },
            "model_requests": 0,
            "credentials_loaded": False,
        },
    )
    probes = []
    for spec, request, actual, variant in prepared:
        before = actual.model_dump_json()
        result = await consumer_probe(
            request,
            variant,
            catalog,
            authority,
            spec.candidates_by_part,
            profile=PROFILES[spec.arm],
            identity=spec.id,
        )
        if actual.model_dump_json() != before:
            raise ValueError("referent_diagnosis_original_mutated")
        probes.append(
            {
                "id": spec.id,
                "case_id": spec.case_id,
                "arm": spec.arm,
                "author_supplied_purpose": spec.purpose,
                "counterfactual": variant != actual,
                "explicit_edits": [e.model_dump(mode="json") for e in spec.edits],
                "exact_diagnostic_proposal": variant.model_dump(mode="json"),
                **result,
            }
        )
    write_new(
        output / "mechanical-replay.json",
        {"actual_captures": len(traces), "traces": traces, "semantic_judgments_by_script": 0},
    )
    write_new(
        output / "consumer-probes.json",
        {"probes": probes, "model_requests": 0, "semantic_judgments_by_script": 0},
    )
    print(
        json.dumps(
            {
                "captures_replayed": len(traces),
                "fixture_probes": len(probes),
                "new_model_requests": 0,
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenarios", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(diagnose(Path.cwd(), args.output, args.scenarios))


if __name__ == "__main__":
    main()
