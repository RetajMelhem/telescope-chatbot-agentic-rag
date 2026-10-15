"""Offline proposal only: exact embedding inputs/batches without approving or dispatching."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.check_frozen_benchmark import verify
from scripts.retrieval_benchmark import load_cases, load_corpus
from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.deduplication import embedding_input_key
from telescope_rag.ingestion.indexing import (
    EmbeddingConfiguration,
    configuration_hash,
    validate_chunks,
)
from telescope_rag.ingestion.models import stable_id
from telescope_rag.ingestion.review import (
    PreparationAudit,
    ReviewApproval,
    prepared_digest,
    validate_approval,
)
from telescope_rag.providers.qwen_tokenizer import (
    TOKENIZER_REVISION,
    QwenPreparationCounter,
    hosted_qwen_format,
)

SOURCE_DIGEST = "a46be2d3fd18f11d46c79ff9bc992de22aab496836894a708bc57c1e8b48af88"
BENCHMARK_MANIFEST = "ee9ace13c784f6c8182ec9f9db4cf76fdc39dc24dc82ba9ad62c8c1b18dbd499"


def batch_plan(
    rows: list[dict], *, batch_size: int, max_batch_tokens: int, max_input_tokens: int
) -> list[dict]:
    """Mirror fixed input-count windows then token subbatches; never dispatch."""
    if (
        type(batch_size) is not int
        or not 1 <= batch_size <= 32
        or type(max_batch_tokens) is not int
        or max_batch_tokens < 1
        or type(max_input_tokens) is not int
        or max_input_tokens < 1
        or not rows
    ):
        raise ValueError("proposal_batch_limits_invalid")
    if len({r["input_key"] for r in rows}) != len(rows):
        raise ValueError("proposal_duplicate_input_key")
    if any(type(r["tokens"]) is not int or not 0 < r["tokens"] <= max_batch_tokens for r in rows):
        raise ValueError("proposal_input_token_count_invalid")
    if sum(r["tokens"] for r in rows) > max_input_tokens:
        raise ValueError("proposal_input_budget_exceeded")
    batches = []
    for start in range(0, len(rows), batch_size):
        current: list[dict] = []
        for row in rows[start : start + batch_size]:
            if sum(r["tokens"] for r in current) + row["tokens"] > max_batch_tokens:
                batches.append(
                    {"inputs": current, "input_tokens": sum(r["tokens"] for r in current)}
                )
                current = []
            current.append(row)
        if current:
            batches.append({"inputs": current, "input_tokens": sum(r["tokens"] for r in current)})
    return [{"batch": i, "input_count": len(b["inputs"]), **b} for i, b in enumerate(batches, 1)]


def build(root: Path, bundle: Path, benchmark: Path) -> dict:
    verify(root, benchmark, BENCHMARK_MANIFEST)
    source_hashes = json.loads((benchmark / "authoring/source-input-hashes.json").read_bytes())
    for relative, expected in source_hashes.items():
        path = (root / relative).resolve()
        if (
            not path.is_relative_to(root.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("proposal_sealed_source_metadata_changed")
    documents, chunks_by_id = load_corpus(bundle)
    digest = prepared_digest(documents)
    if digest != SOURCE_DIGEST:
        raise ValueError("proposal_source_digest_mismatch")
    audit = PreparationAudit.model_validate_json((bundle / "audit.json").read_bytes())
    review = ReviewApproval.model_validate_json(
        (bundle / "metadata/review-approved.json").read_bytes()
    )
    if audit.prepared_digest != digest or review.prepared_digest != digest:
        raise ValueError("proposal_review_digest_mismatch")
    if not review.source_reviewed or review.approved:
        raise ValueError("proposal_requires_reviewed_but_unapproved_baseline")
    try:
        validate_approval(documents, audit, review)
    except ValueError as error:
        if str(error) != "source_review_required":
            raise
        dispatch_gate = "CLOSED: source_review_required; persisted approved=false"
    else:
        raise ValueError("proposal_must_not_grant_execution_approval")
    configuration = EmbeddingConfiguration.model_validate_json(
        (bundle / "metadata/embedding-configuration.json").read_bytes()
    )
    settings = Settings(
        _env_file=None,
        openrouter_api_key="",
        qdrant_api_key="",
        openrouter_embedding_model="qwen/qwen3-embedding-8b",
        embedding_dimensions=4096,
        provider_max_retries=0,
        max_embedding_batch_size=16,
        max_embedding_input_tokens=16000,
        chunk_max_tokens=1200,
        qdrant_url="http://127.0.0.1:6333",
    )
    chunks = tuple(c for d in documents for c in d.chunks)
    validate_chunks(chunks, settings, configuration)
    counter = QwenPreparationCounter(
        root / ".tools/qwen-tokenizer" / TOKENIZER_REVISION / "tokenizer.json"
    )
    format = hosted_qwen_format()
    config_hash = configuration_hash(configuration)
    if configuration.format_hash != stable_id("embedding-format-v1", format.model_dump_json()):
        raise ValueError("proposal_format_mismatch")
    groups = {}
    for chunk in chunks:
        tokens = counter.count(format.format(chunk.retrieval_text, "document"))
        if tokens != chunk.token_count:
            raise ValueError("proposal_token_count_mismatch")
        key = embedding_input_key(chunk, config_hash)
        if key not in groups:
            groups[key] = {
                "input_key": key,
                "tokens": tokens,
                "language": chunk.language,
                "doctor_id": chunk.doctor_id,
                "representative_chunk_id": chunk.chunk_id,
                "occurrence_chunk_ids": [],
            }
        groups[key]["occurrence_chunk_ids"].append(chunk.chunk_id)
    corpus_rows = list(groups.values())
    corpus_tokens = sum(r["tokens"] for r in corpus_rows)
    corpus_batches = batch_plan(
        corpus_rows, batch_size=16, max_batch_tokens=16000, max_input_tokens=corpus_tokens
    )
    cases = load_cases(benchmark / "cases.jsonl")
    # Query proposal deliberately preserves all 90 requests, no semantic/fuzzy reuse.
    query_rows = [
        {
            "input_key": c.case_id,
            "tokens": counter.count(format.format(c.query, "query")),
            "language": c.language,
            "query_sha256": hashlib.sha256(c.query.encode("utf-8")).hexdigest(),
        }
        for c in cases
    ]
    query_tokens = sum(r["tokens"] for r in query_rows)
    query_batches = batch_plan(
        query_rows, batch_size=32, max_batch_tokens=16000, max_input_tokens=query_tokens
    )
    candidate = "telescope_public_" + stable_id(audit.snapshot_id, digest, config_hash)[:24]
    return {
        "status": "PROPOSED_ONLY; execution_not_authorized",
        "prepared_digest": digest,
        "collection_digest": audit.collection_digest,
        "benchmark_manifest_sha256": BENCHMARK_MANIFEST,
        "configuration_hash": config_hash,
        "candidate": candidate,
        "model": configuration.model,
        "dimensions": configuration.dimensions,
        "provider_only": [format.provider_slug],
        "allow_fallbacks": False,
        "retries": 0,
        "source_reviewed": True,
        "persisted_execution_approved": False,
        "dispatch_gate": dispatch_gate,
        "approval_changed": False,
        "active_alias_changed": False,
        "source_policy_runtime_enforced": False,
        "tokenizer_receipt": counter.receipt(),
        "embedding_format": format.model_dump(mode="json"),
        "corpus_stage": {
            "points": len(chunks_by_id),
            "unique_inputs": len(corpus_rows),
            "exact_reuse_occurrences": len(chunks) - len(corpus_rows),
            "input_tokens": corpus_tokens,
            "max_physical_provider_requests": len(corpus_batches),
            "max_reserved_input_tokens": corpus_tokens,
            "max_batch_inputs": 16,
            "max_batch_input_tokens": 16000,
            "deadline_seconds": 600,
            "batches": corpus_batches,
            "cache_assumption": "Cold cache upper bound. New ignored cache; no cache instantiated. "
            "Existing compatible cache records must all validate before dispatch; a corrupt record "
            "stops the run. Fixed subbatch boundaries can leave multiple partial requests.",
            "raw_float32_vector_bytes_unique": len(corpus_rows) * configuration.dimensions * 4,
            "raw_float32_vector_bytes_points": len(chunks) * configuration.dimensions * 4,
            "storage_limits": "Arithmetic payload estimate only; excludes JSON/cache, metadata, "
            "indexes, process overhead, replicas and actual storage implementation.",
        },
        "query_stage_separate_future_authorization": {
            "status": "NOT_IMPLEMENTED_OR_EXECUTED",
            "inputs": len(query_rows),
            "input_tokens": query_tokens,
            "max_physical_provider_requests": len(query_batches),
            "max_reserved_input_tokens": query_tokens,
            "max_batch_inputs": 32,
            "batches": query_batches,
            "limits": "Raw queries only. No planner/history rewrite, chat counting, Luna call or "
            "query-format change is covered by this proposal. Search runner remains unimplemented.",
        },
        "combined_embedding_proposal": {
            "max_requests": len(corpus_batches) + len(query_batches),
            "max_input_tokens": corpus_tokens + query_tokens,
            "limits": "Stages have separate approval and implementations. This sum is not an "
            "executable end-to-end budget or permission to run either stage.",
        },
        "money": {
            "quoted_usd": None,
            "verified_current_route_price": None,
            "formula": "input_tokens / 1000000 * verified_route_USD_per_million_input_tokens",
            "gate": "No price quote or spend is approved. Reconfirm actual route pricing and "
            "explicit monetary cap before paid execution; do not infer price from token counts.",
        },
        "payload_contract": {
            "all_occurrences": True,
            "literal_owners_and_canonical_aliases": True,
            "source_spans_context_and_timestamps": True,
            "source_issue_codes": True,
            "admission_policy_hash": True,
            "full_payload_equality_audit_required": True,
        },
        "next_stage_limits": {
            "read_only_search_requests": 90,
            "max_results_per_request": 20,
            "derive_top_k_offline": [5, 10, 20],
            "hypothetical_result_slots_max": 1800,
            "directory_and_history": "Separate capability gates; top-k witnesses do not prove "
            "full-directory listing or history-aware conversation behavior.",
            "answer_generation": "Not covered: no Luna call/counting/answer readiness claimed.",
        },
        "source_issue_code_occurrences": dict(
            Counter(code for c in chunks for code in c.source_issue_codes)
        ),
        "planned_new_paths_not_created": {
            "execution_copy": "data/processed/m3-execution-approved-v6-v1",
            "cache": "data/processed/m3-qwen-cache-v6-v1",
            "execution_receipts": "artifacts/m3-candidate-execution-v6-v1",
        },
        "approval_handoff": "Preserve original v6 approved=false. Only after explicit user "
        "execution authorization, create a new exclusive execution copy with identical prepared "
        "document digest and a separately recorded exact-digest, stage-bounded approval. All "
        "historical false approval/policy receipts remain in the original immutable bundle. "
        "No approval receipt or execution copy is created by this planner.",
        "provider_calls": 0,
        "embedding_calls": 0,
        "qdrant_calls": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("immutable_plan_output_exists")
    root = Path(__file__).resolve().parents[1]
    result = build(root, args.bundle.resolve(), args.benchmark.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    summary = {k: result[k] for k in ("status", "candidate", "prepared_digest", "dispatch_gate")}
    summary["corpus"] = {
        k: result["corpus_stage"][k]
        for k in ("points", "unique_inputs", "input_tokens", "max_physical_provider_requests")
    }
    summary["query"] = {
        k: result["query_stage_separate_future_authorization"][k]
        for k in ("inputs", "input_tokens", "max_physical_provider_requests")
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
