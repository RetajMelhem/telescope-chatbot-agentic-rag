"""Offline capture of actual Luna adapter payloads; inference remains blocked.

The only continuation is an explicitly labelled authored planner oracle. No
token estimate, provider response, generated answer or compatibility is invented.
"""

import argparse
import asyncio
import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import httpx2 as httpx

from scripts.planner_review import PlannerFixture, fixture_hash, load_fixtures, validate_case
from scripts.retrieval_benchmark import load_corpus
from telescope_rag.core.settings import Settings
from telescope_rag.graph.contracts import PlannerReply, RetrievalBatch, RetrievedPart
from telescope_rag.graph.workflow import OfflineRagWorkflow
from telescope_rag.providers.contracts import StructuredResult
from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.providers.qwen_tokenizer import QwenPreparationCounter
from telescope_rag.retrieval.assembly import AssemblyCounter, EvidenceCatalog


class CaptureError(ValueError):
    """Application-authored event code only; no credentials or user input."""


def payload_bytes(payload: Mapping[str, Any]) -> bytes:
    """Exactly the current provider adapter's pre-dispatch JSON serialization."""
    return json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")


class RecordingRejectCounter:
    """Observe complete actual wire input, then fail before budget/HTTP dispatch."""

    def __init__(self):
        self.stage = "unassigned"
        self.captures: list[dict] = []

    def count(self, kind, payload):
        self.captures.append({"stage": self.stage, "kind": kind, "payload": copy.deepcopy(payload)})
        raise ProviderError("token_count_unavailable")


class ForbiddenTransport:
    """A second, independent no-network boundary even if counting regresses."""

    def __init__(self):
        self.attempts = 0
        self.transport = httpx.MockTransport(self.reject)

    def reject(self, request):
        self.attempts += 1
        raise CaptureError("offline_transport_gate_reached")


class CaptureChat:
    """Use the real adapter; only an authored planning oracle can continue."""

    def __init__(self, adapter, counter, case):
        self.adapter, self.counter, self.case = adapter, counter, case
        self.oracle_continuations = 0
        self.budgets = []

    async def complete(self, messages, output_model, *, max_output_tokens, budget):
        self.counter.stage = "planning" if output_model is PlannerReply else "draft"
        previous = len(self.counter.captures)
        self.budgets.append(budget)
        try:
            await self.adapter.complete(
                messages,
                output_model,
                max_output_tokens=max_output_tokens,
                budget=budget,
            )
        except ProviderError as error:
            if (
                error.code == "token_count_unavailable"
                and output_model is PlannerReply
                and len(self.counter.captures) == previous + 1
            ):
                self.oracle_continuations += 1
                return StructuredResult(self.case.expected_plan, ())
            raise
        raise CaptureError("reject_counter_did_not_block")


class OracleRetriever:
    """Authored witnesses only, explicitly not a search or embedding result."""

    def __init__(self, case, *, top_k):
        self.case, self.top_k = case, top_k
        self.search_indices = tuple(
            i
            for i, p in enumerate(case.expected_plan.parts)
            if p.state == "public" and p.operation == "search"
        )
        self.calls = 0
        self.budgets = []

    async def retrieve(self, queries, *, snapshot_id, prepared_digest, budget):
        if len(queries) != len(self.search_indices):
            raise CaptureError("oracle_search_part_mismatch")
        self.calls += 1
        self.budgets.append(budget)
        parts = []
        for query, index in zip(queries, self.search_indices, strict=True):
            if query.text != self.case.expected_plan.parts[index].retrieval_query:
                raise CaptureError("oracle_query_changed")
            identities = self.case.part_reviews[index].witness_chunk_ids
            if len(identities) > self.top_k:
                raise CaptureError("oracle_witness_limit_exceeded")
            parts.append(RetrievedPart(part_id=query.part_id, chunk_ids=identities))
        return RetrievalBatch(
            snapshot_id=snapshot_id, prepared_digest=prepared_digest, parts=tuple(parts)
        )


def capture_settings() -> Settings:
    # Explicit init values have priority over ambient process settings. Supplying
    # every declared default also prevents an inherited endpoint/budget override.
    # _env_file=None prevents loading the project's credentials or dotenv file.
    values = {
        name: field.get_default(call_default_factory=True)
        for name, field in Settings.model_fields.items()
    }
    values.update(
        app_env="test",
        openrouter_api_key="synthetic-capture-only",
        provider_max_retries=0,
        chat_input_accounting="strict",
    )
    return Settings(_env_file=None, **values)


async def capture_case(
    case: PlannerFixture,
    catalog: EvidenceCatalog,
    assembly_counter: AssemblyCounter,
    *,
    token_basis: Literal["qwen_retrieval_only", "synthetic_test"] = "qwen_retrieval_only",
) -> dict:
    validate_case(case, catalog)
    settings = capture_settings()
    counter, forbidden = RecordingRejectCounter(), ForbiddenTransport()
    retriever = OracleRetriever(case, top_k=settings.retrieval_top_k_per_question)
    async with OpenRouterProviders(
        settings, token_counter=counter, transport=forbidden.transport
    ) as providers:
        chat = CaptureChat(providers.chat, counter, case)
        flow = OfflineRagWorkflow(
            settings=settings,
            chat=chat,
            retriever=retriever,
            catalog=catalog,
            counter=assembly_counter,
            token_basis=token_basis,
        )
        run = await flow.run(case.request)
    if forbidden.attempts:
        raise CaptureError("offline_transport_gate_reached")
    if (
        chat.oracle_continuations != 1
        or not counter.captures
        or counter.captures[0]["stage"] != "planning"
    ):
        raise CaptureError("offline_planning_payload_not_captured")
    if (
        any(
            (
                run.usage.logical_chat_calls,
                run.usage.logical_embedding_calls,
                run.usage.physical_chat_attempts,
                run.usage.physical_embedding_attempts,
                run.usage.charged_chat_input,
                run.usage.charged_embedding_input,
                run.usage.charged_output,
            )
        )
        or run.usage.receipts
    ):
        raise CaptureError("offline_capture_budget_was_charged")
    all_budgets = chat.budgets + retriever.budgets
    if all_budgets and any(b is not all_budgets[0] for b in all_budgets):
        raise CaptureError("offline_capture_budget_not_shared")
    payloads = []
    for item in counter.captures:
        encoded = payload_bytes(item["payload"])
        payloads.append(
            {
                **item,
                "serialized_utf8": encoded.decode("utf-8"),
                "serialized_bytes": len(encoded),
                "serialized_sha256": hashlib.sha256(encoded).hexdigest(),
                "luna_input_tokens": None,
                "input_count_basis": "unavailable; rejected before reservation",
                "provider_dispatch": False,
            }
        )
    return {
        "version": "offline-luna-wire-preparation-v1",
        "case_id": case.case_id,
        "case_sha256": fixture_hash(case),
        "prepared_digest": catalog.prepared_digest,
        "requested_model": settings.openrouter_chat_model,
        "payloads": payloads,
        "payload_capture_count": len(payloads),
        "oracle_provenance": {
            "planner": "Authored expected_plan injected only after the real adapter "
            "rejected counting.",
            "retrieval": "Authored per-part witness IDs, not measured search or vector results.",
            "complete_reads": "Current EvidenceCatalog derives exact admitted scope membership.",
            "continuations": chat.oracle_continuations,
            "retrieval_batches": retriever.calls,
            "generation_budget_assumption": "Oracle planning charges zero; actual paid planning "
            "usage could alter the draft output cap. No actual Luna usage is known.",
        },
        "settings_caps": {
            "retrieval_top_k_per_question": settings.retrieval_top_k_per_question,
            "max_evidence_chunks": settings.max_evidence_chunks,
            "max_evidence_tokens": settings.max_evidence_tokens,
            "max_total_input_tokens": settings.max_total_input_tokens,
            "max_total_output_tokens": settings.max_total_output_tokens,
            "max_llm_calls": settings.max_llm_calls,
            "max_embedding_calls": settings.max_embedding_calls,
            "provider_max_retries": settings.provider_max_retries,
            "provider_max_request_bytes": settings.provider_max_request_bytes,
        },
        "workflow_stages": list(run.stages),
        "workflow_result": run.result.model_dump(mode="json"),
        "evidence": None
        if run.evidence is None
        else {
            "token_count": run.evidence.token_count,
            "token_profile": run.evidence.token_profile,
            "token_basis": run.evidence.token_basis,
            "luna_input_admitted": run.evidence.luna_input_admitted,
            "semantic_support_assessed": run.evidence.semantic_support_assessed,
            "parts": [
                {
                    "part_id": p.part_id,
                    "candidate_status": p.candidate_status,
                    "admitted_scope_complete": p.admitted_scope_complete,
                    "context_only": p.context_only,
                    "occurrence_ids": list(p.occurrence_ids),
                    "missing_scope_occurrence_ids": list(p.missing_scope_occurrence_ids),
                    "omission_reasons": [list(pair) for pair in p.omission_reasons],
                }
                for p in run.evidence.parts
            ],
        },
        "luna_input_tokens": None,
        "estimated_provider_cost_usd": None,
        "http_attempts": forbidden.attempts,
        "provider_calls": 0,
        "budget_operations": {"chat": 0, "embedding": 0},
        "budget_reservations": {"chat": 0, "embedding": 0},
        "index_calls": 0,
        "planner_model_executed": False,
        "draft_model_executed": False,
        "model_accuracy_assessed": False,
        "luna_compatibility_verified": False,
        "production_ready": False,
    }


def parser():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--cases", type=Path, nargs="+", required=True)
    args.add_argument("--bundle", type=Path, required=True)
    args.add_argument("--prepared-digest", required=True)
    args.add_argument("--tokenizer", type=Path, required=True)
    args.add_argument("--output", type=Path, required=True)
    return args


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


async def prepare(args):
    if args.output.exists():
        raise CaptureError("offline_capture_output_must_be_new")
    cases = load_fixtures(tuple(args.cases))
    if not cases or len({c.case_id for c in cases}) != len(cases):
        raise CaptureError("offline_capture_case_inventory_invalid")
    documents, _ = load_corpus(args.bundle)
    catalog = EvidenceCatalog(documents, expected_digest=args.prepared_digest)
    for case in cases:
        validate_case(case, catalog)
    counter = QwenPreparationCounter(args.tokenizer)
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for index, case in enumerate(cases, 1):
        result = await capture_case(case, catalog, counter)
        filename = f"capture-{index:04d}.json"
        write_new(args.output / filename, result)
        results.append(
            {
                "case_id": case.case_id,
                "file": filename,
                "sha256": hashlib.sha256((args.output / filename).read_bytes()).hexdigest(),
                "payloads": result["payload_capture_count"],
            }
        )
    summary = {
        "version": "offline-luna-wire-preparation-v1",
        "captures": results,
        "prepared_digest": catalog.prepared_digest,
        "case_input_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in args.cases
        },
        "luna_input_tokens": None,
        "provider_calls": 0,
        "http_attempts": 0,
        "index_calls": 0,
        "oracle_only": True,
        "model_accuracy_assessed": False,
        "luna_compatibility_verified": False,
        "production_ready": False,
    }
    write_new(args.output / "summary.json", summary)
    return summary


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        summary = asyncio.run(prepare(args))
    except (ValueError, OSError, ProviderError):
        raise SystemExit("offline_luna_preparation_failed") from None
    print(
        json.dumps(
            {"cases": len(summary["captures"]), "provider_calls": 0, "luna_input_tokens": None}
        )
    )


if __name__ == "__main__":
    main()
