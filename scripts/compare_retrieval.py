"""Explicit, frozen dense/local-BM25 comparison; no serving or candidate mutation.

Default invocation prepares an offline plan. --execute selects only the bounded
query-embedding and read-only search experiment; corpus embeddings are reused.
"""

import argparse
import asyncio
import hashlib
import json
import statistics
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import httpx2 as httpx
from pydantic import BaseModel, ConfigDict, Field

from scripts.check_frozen_benchmark import verify
from scripts.retrieval_benchmark import (
    HistoryMessage,
    RetrievalReceipt,
    canonical_bytes,
    load_cases,
    score_receipts,
)
from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.indexing import EmbeddingCache, configuration_hash
from telescope_rag.ingestion.review import all_chunks, prepared_digest
from telescope_rag.ingestion.runner import load_reviewed_bundle, read_secret
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.providers.qwen_tokenizer import QwenEmbeddingCounter, QwenPreparationCounter
from telescope_rag.providers.validation import load_json
from telescope_rag.retrieval.candidate import CandidateDenseReader
from telescope_rag.retrieval.lexical import BM25Index, reciprocal_rank_fusion
from telescope_rag.retrieval.query_vectors import QueryText, embed_queries, plan_queries

MANIFEST = "ee9ace13c784f6c8182ec9f9db4cf76fdc39dc24dc82ba9ad62c8c1b18dbd499"
BENCHMARK_HASH = "e753d931c558c29a74ccfd18c0921efc4dd943b04c8a972267643943458be84b"
CANDIDATE = "telescope_public_018817ac10ec05ecad92adb9"
TOKENIZER = ".tools/qwen-tokenizer/1d8ad4ca9b3dd8059ad90a75d4983776a23d44af/tokenizer.json"
BUNDLE = "data/processed/m3-execution-approved-v6-v2"
BENCHMARK = "artifacts/m3-retrieval-benchmark-v1"
QUERY_CACHE = "data/processed/m4-query-cache-v1"
MODES = ("dense", "bm25", "hybrid")


class BenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str = Field(min_length=1, max_length=128)
    language: Literal["en", "ar", "ar-JO"]
    query: str = Field(min_length=1, max_length=4000)
    history: tuple[HistoryMessage, ...] = Field(max_length=6)


def write(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)


def load_requests(path: Path) -> tuple[BenchmarkRequest, ...]:
    rows = tuple(
        BenchmarkRequest.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if not rows or len(rows) > 1000 or len({r.case_id for r in rows}) != len(rows):
        raise ValueError("comparison_request_inventory_invalid")
    return rows


def prepare(root: Path) -> tuple[dict, tuple[BenchmarkRequest, ...], object]:
    frozen = verify(root, root / BENCHMARK, MANIFEST)
    bundle = load_reviewed_bundle(root / BUNDLE)
    corpus_plan = json.loads(
        (root / "artifacts/m3-candidate-execution-v6-v1/plan.json").read_bytes()
    )
    if (
        prepared_digest(bundle.documents) != frozen["prepared_digest"]
        or bundle.audit.prepared_digest != frozen["prepared_digest"]
        or bundle.audit.collection_digest != corpus_plan["collection_digest"]
        or configuration_hash(bundle.configuration) != corpus_plan["configuration_hash"]
        or corpus_plan["candidate"] != CANDIDATE
        or frozen["benchmark_sha256"] != BENCHMARK_HASH
    ):
        raise ValueError("comparison_execution_copy_binding_mismatch")
    requests = load_requests(root / BENCHMARK / "requests.jsonl")
    if len(requests) != 90:
        raise ValueError("frozen_comparison_requires_90_requests")
    query_plan = plan_queries(
        [QueryText(r.case_id, r.query) for r in requests],
        QwenPreparationCounter(root / TOKENIZER),
        corpus_plan["configuration_hash"],
    )
    if (query_plan["unique_inputs"], query_plan["total_input_tokens"]) != (90, 4758):
        raise ValueError("frozen_query_proposal_changed")
    plan = {
        "version": "dense-local-bm25-rrf-v1",
        "prepared_digest": frozen["prepared_digest"],
        "benchmark_manifest_sha256": MANIFEST,
        "benchmark_sha256": BENCHMARK_HASH,
        "requests_sha256": hashlib.sha256(
            (root / BENCHMARK / "requests.jsonl").read_bytes()
        ).hexdigest(),
        "candidate": CANDIDATE,
        "source_occurrences": 955,
        "query_plan": query_plan,
        "query_cache": QUERY_CACHE,
        "query_deadline_seconds": 180,
        "max_dense_searches": 90,
        "dense_exact": True,
        "dense_prefetch": 20,
        "lexical_prefetch": 20,
        "final_limit": 20,
        "bm25": {
            "implementation": "local_literal_unicode_v1",
            "k1": 1.2,
            "b": 0.75,
            "idf": "log(1+(N-df+0.5)/(df+0.5))",
            "query_term_frequency": "repeated_terms_contribute_repeated_scores",
            "analysis": "NFC,casefold,Unicode-L/N/M;no-stemming/Arabic-folding/translation",
            "zero_scores": "omitted",
        },
        "fusion": {"implementation": "application_original_rrf", "one_based": True, "k": 60},
        "tie_order": "score_desc,chunk_id_asc within fetched pool; cutoff ties unresolved",
        "history": "raw current query only; history cases not conversation acceptance",
        "primary_selection": "eligible single-turn non-exhaustive-directory: hybrid must "
        "strictly improve macro support recall@10 on development, with no per-language "
        "support/context regression; evaluation must confirm all conditions without retuning",
        "fallback_selection": "inconclusive; dense experimental baseline retained",
        "adoption_gate": "manual source review of gains/losses and unlisted alternatives; "
        "no universal best or end-to-end readiness claim",
        "corpus_embedding_calls": 0,
        "qdrant_write_requests": 0,
        "source_policy_runtime_enforced": False,
        "answer_generation": "not_executed",
    }
    return plan, requests, bundle


async def metadata(settings: Settings) -> dict:
    """Two free official GETs only; never return a key label or upstream error body."""
    rows = {}
    async with httpx.AsyncClient(
        timeout=10,
        trust_env=False,
        follow_redirects=False,
        transport=httpx.AsyncHTTPTransport(retries=0),
    ) as client:
        for name, path, auth in (
            ("route", "models/qwen/qwen3-embedding-8b/endpoints", False),
            ("key", "key", True),
        ):
            headers = {"Accept": "application/json"}
            if auth:
                headers["Authorization"] = (
                    "Bearer " + settings.openrouter_api_key.get_secret_value()
                )
            async with client.stream(
                "GET", "https://openrouter.ai/api/v1/" + path, headers=headers
            ) as response:
                raw = bytearray()
                async for part in response.aiter_bytes(chunk_size=65536):
                    if len(raw) + len(part) > 1_000_000:
                        raise ValueError("comparison_metadata_too_large")
                    raw.extend(part)
                if response.status_code != 200:
                    raise ValueError("comparison_metadata_request_failed")
                data = load_json(bytes(raw))["data"]
                if name == "route":
                    candidates = [r for r in data["endpoints"] if r["tag"] == "deepinfra/us"]
                    if len(candidates) != 1:
                        raise ValueError("comparison_pinned_route_missing")
                    rows[name] = {k: candidates[0][k] for k in ("tag", "pricing")}
                else:
                    rows[name] = {k: data.get(k) for k in ("limit", "limit_remaining", "usage")}
    price = Decimal(rows["route"]["pricing"]["prompt"])
    if price != Decimal("0.00000001") or Decimal(str(rows["key"]["limit_remaining"])) < Decimal(
        "0.001"
    ):
        raise ValueError("comparison_price_or_allowance_changed")
    return {
        "observed_at_utc": datetime.now(UTC).isoformat(),
        **rows,
        "query_quote_usd": str(4758 * price),
        "conservative_allowance_usd": "0.001",
        "usd_limit_basis": "fixed exact token/attempt caps at checked price; no new USD server cap",
        "embedding_calls": 0,
    }


def aggregate(scored: dict, splits: dict[str, str], eligible: set[str]) -> dict:
    output = {}
    for scope in ("all", "eligible"):
        for split in ("development", "evaluation"):
            for language in ("all", "en", "ar", "ar-JO"):
                selected = [
                    row
                    for row in scored["cases"]
                    if splits[row["case_id"]] == split
                    and (scope == "all" or row["case_id"] in eligible)
                    and (language == "all" or row["language"] == language)
                ]
                metrics = {}
                for role in ("answer_support", "uncertainty_or_clarification"):
                    values = [
                        row["metrics"][role]["witness_group_recall"]
                        for row in selected
                        if row["metrics"][role]["witness_group_recall"] is not None
                    ]
                    metrics[role] = {
                        "cases": len(values),
                        "macro_recall": statistics.mean(values) if values else None,
                    }
                output[f"{scope}/{split}/{language}"] = {
                    "cases": len(selected),
                    **metrics,
                }
    return output


def select_mode(dense: dict, hybrid: dict) -> dict:
    checks = {}
    for split in ("development", "evaluation"):
        prefix = f"eligible/{split}/"
        d = dense[prefix + "all"]["answer_support"]["macro_recall"]
        h = hybrid[prefix + "all"]["answer_support"]["macro_recall"]
        checks[split + "/strict_support_gain"] = d is not None and h is not None and h > d + 1e-12
        for language in ("en", "ar", "ar-JO"):
            for role in ("answer_support", "uncertainty_or_clarification"):
                d = dense[prefix + language][role]["macro_recall"]
                h = hybrid[prefix + language][role]["macro_recall"]
                checks[f"{split}/{language}/{role}_nondecreasing"] = (
                    d is not None and h is not None and h + 1e-12 >= d
                )
    return {
        "result": "preliminary_hybrid_candidate"
        if all(checks.values())
        else "inconclusive_dense_baseline_retained",
        "checks": checks,
        "requires_manual_source_review_before_adoption": True,
        "production_ready": False,
    }


def already_started(output: Path) -> bool:
    return any(
        path.name in {"result.json", "failure.json", "provider-metadata-before.json"}
        or path.name.startswith("query-batch-")
        for path in output.iterdir()
    )


async def rank_requests(requests, vectors, reader, lexical, record, progress=lambda _: None):
    """One dense call per raw request; share its exact pool across comparison arms."""
    ranked = {mode: [] for mode in MODES}
    timings, payload_ids = [], set()
    for index, request in enumerate(requests, 1):
        tick = time.perf_counter()
        dense = sorted(
            await reader.search(vectors[request.case_id], limit=20),
            key=lambda hit: (-hit.score, hit.chunk.chunk_id),
        )
        dense_ms = (time.perf_counter() - tick) * 1000
        tick = time.perf_counter()
        sparse = lexical.search(request.query, limit=20)
        lexical_ms = (time.perf_counter() - tick) * 1000
        tick = time.perf_counter()
        hybrid = reciprocal_rank_fusion(
            [[h.chunk.chunk_id for h in dense], [h.chunk_id for h in sparse]],
            limit=20,
            rank_constant=60,
        )
        fusion_ms = (time.perf_counter() - tick) * 1000
        case = {}
        for mode, hits in {
            "dense": [(h.chunk.chunk_id, h.score) for h in dense],
            "bm25": [(h.chunk_id, h.score) for h in sparse],
            "hybrid": [(h.chunk_id, h.score) for h in hybrid],
        }.items():
            payload_ids.update(chunk_id for chunk_id, _ in hits)
            row = {
                "case_id": request.case_id,
                "ranked_chunk_ids": [chunk_id for chunk_id, _ in hits],
                "scores": [score for _, score in hits],
            }
            ranked[mode].append(row)
            case[mode] = row
        timing = {
            "case_id": request.case_id,
            "dense_ms": dense_ms,
            "lexical_ms": lexical_ms,
            "fusion_ms": fusion_ms,
        }
        timings.append(timing)
        # Preserve completed case evidence even if a later request fails.
        record(index, {"case_id": request.case_id, "rankings": case, "timings": timing})
        progress(index)
    return ranked, timings, payload_ids


async def execute(root: Path, output: Path, plan: dict, requests: tuple, bundle) -> dict:
    if await asyncio.to_thread(already_started, output):
        raise ValueError("comparison_run_already_started_use_new_evidence_directory")
    chunks = all_chunks(bundle.documents)
    by_id = {c.chunk_id: c for c in chunks}
    if len(by_id) != 955:
        raise ValueError("comparison_corpus_inventory_changed")
    settings = Settings(
        _env_file=root / ".env",
        provider_max_retries=0,
        max_embedding_batch_size=16,
        max_embedding_input_tokens=16000,
        embedding_dimensions=4096,
        qdrant_url="http://127.0.0.1:6333",
        qdrant_api_key="",
    )
    account = await metadata(settings)
    write(output / "provider-metadata-before.json", account)
    # Bind authorization and implementation to the sealed pre-scoring plan.
    write(
        output / "execution-authorization.json",
        {
            "user_instruction": "begin the next step and compare dense/hybrid; resume the task",
            "scope": "90 raw query embeddings and paired bounded retrieval comparison only",
            "plan_sha256": hashlib.sha256(canonical_bytes(plan)).hexdigest(),
            "max_embedding_attempts": 6,
            "max_input_tokens": 4758,
            "max_searches": 90,
            "corpus_embedding_calls": 0,
            "qdrant_write_requests": 0,
            "quoted_query_usd": account["query_quote_usd"],
            "conservative_allowance_usd": "0.001",
            "usd_server_cap_changed": False,
            "implementation_sha256": {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in (
                    "scripts/compare_retrieval.py",
                    "src/telescope_rag/retrieval/candidate.py",
                    "src/telescope_rag/retrieval/lexical.py",
                    "src/telescope_rag/retrieval/query_vectors.py",
                )
            },
        },
    )
    reader = CandidateDenseReader(
        settings,
        read_secret(root / ".tools/qdrant-m3/read.key"),
        collection=CANDIDATE,
        chunks={c.point_id: c for c in chunks},
    )
    started = time.monotonic()
    try:
        async with asyncio.timeout(180):
            before, aliases = await reader.info(), await reader.aliases()
            if (
                before["points_count"] != 955
                or before["config"]["params"]["vectors"] != {"size": 4096, "distance": "Cosine"}
                or aliases
            ):
                raise ValueError("comparison_candidate_preflight_failed")
            write(output / "candidate-before.json", before)
            lexical = BM25Index({c.chunk_id: c.retrieval_text for c in chunks})
            cache = EmbeddingCache(root / QUERY_CACHE)
            embedding_started = time.monotonic()
            async with OpenRouterProviders(
                settings, token_counter=QwenEmbeddingCounter(root / TOKENIZER)
            ) as providers:
                vectors, query_result = await embed_queries(
                    [QueryText(r.case_id, r.query) for r in requests],
                    provider=providers.embeddings,
                    settings=settings,
                    counter=QwenPreparationCounter(root / TOKENIZER),
                    configuration_hash=plan["query_plan"]["configuration_hash"],
                    cache=cache,
                    receipt=lambda row: write(output / f"query-batch-{row['batch']:04}.json", row),
                )
            embedding_seconds = time.monotonic() - embedding_started
            ranked, timings, payload_ids = await rank_requests(
                requests,
                vectors,
                reader,
                lexical,
                record=lambda index, row: write(output / f"case-{index:04}.json", row),
                progress=lambda index: (
                    print(json.dumps({"retrieval_cases_completed": index, "total": 90}), flush=True)
                    if index % 15 == 0
                    else None
                ),
            )
            after = await reader.info()
            if (
                after["points_count"] != 955
                or after["config"] != before["config"]
                or await reader.aliases() != aliases
            ):
                raise ValueError("comparison_candidate_state_changed")
            write(output / "candidate-after.json", after)
    except BaseException as error:
        write(
            output / "failure.json",
            {
                "status": "stopped_preserve_cache_and_receipts",
                "error_type": type(error).__name__,
                "automatic_paid_retry": False,
                "qdrant_write_requests": 0,
            },
        )
        raise
    finally:
        await reader.aclose()
    # Seal actual rankings before passing any gold outcomes to scoring.
    for mode, rows in ranked.items():
        with (output / f"{mode}-rankings.jsonl").open("x", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (output / "retrieved-payloads.jsonl").open("x", encoding="utf-8") as stream:
        for chunk_id in sorted(payload_ids):
            stream.write(by_id[chunk_id].model_dump_json() + "\n")
    cases = load_cases(root / BENCHMARK / "cases.jsonl")
    splits = json.loads((root / BENCHMARK / "splits.json").read_bytes())["case_assignments"]
    eligible = {c.case_id for c in cases if not c.history and "exhaustive_directory" not in c.tags}
    summaries = {}
    for mode, rows in ranked.items():
        receipts = tuple(
            RetrievalReceipt(
                case_id=row["case_id"],
                prepared_digest=plan["prepared_digest"],
                benchmark_sha256=BENCHMARK_HASH,
                execution_kind="real_retrieval",
                ranked_chunk_ids=tuple(row["ranked_chunk_ids"]),
            )
            for row in rows
        )
        summaries[mode] = {}
        for k in (5, 10, 20):
            scored = score_receipts(
                cases, receipts, by_id, source_digest=plan["prepared_digest"], k=k
            )
            write(output / f"{mode}-scores-k{k}.json", scored)
            summaries[mode][str(k)] = aggregate(scored, splits, eligible)
    result = {
        "status": "retrieval_comparison_executed",
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "plan_sha256": hashlib.sha256(canonical_bytes(plan)).hexdigest(),
        "query_embedding_result": query_result,
        "query_embedding_seconds": embedding_seconds,
        "dense_search_requests": len(requests),
        "ranked_cases_per_mode": {m: len(r) for m, r in ranked.items()},
        "source_payloads_exported": len(payload_ids),
        "source_issue_codes_preserved": True,
        "source_policy_runtime_enforced": False,
        "candidate_config_points_and_aliases_unchanged": True,
        "summaries": summaries,
        "selection": select_mode(summaries["dense"]["10"], summaries["hybrid"]["10"]),
        "timings": timings,
        "elapsed_seconds": time.monotonic() - started,
        "answer_generation_calls": 0,
        "corpus_embedding_calls": 0,
        "qdrant_write_requests": 0,
        "limits": "Known selected witness recall; raw-query scope only. Local literal BM25 "
        "and original application RRF, not native Qdrant hybrid. Cutoff ties and unlisted valid "
        "alternatives need review. No answer, conversation, directory or production acceptance.",
    }
    write(output / "result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / "artifacts"):
        raise ValueError("comparison_output_must_be_local_artifact")
    output.mkdir(parents=True, exist_ok=True)
    plan, requests, bundle = prepare(root)
    path = output / "experiment-plan.json"
    if path.exists():
        if json.loads(path.read_bytes()) != plan:
            raise ValueError("frozen_comparison_plan_changed")
    else:
        write(path, plan)
    if args.execute:
        result = asyncio.run(execute(root, output, plan, requests, bundle))
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in (
                        "status",
                        "query_embedding_result",
                        "dense_search_requests",
                        "selection",
                    )
                },
                indent=2,
            )
        )
    else:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "queries": len(requests),
                    "modes": MODES,
                    "input_tokens": plan["query_plan"]["total_input_tokens"],
                    "max_query_embedding_requests": 6,
                    "corpus_embedding_calls": 0,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(
            f"Retrieval comparison stopped ({type(error).__name__}); preserve receipts."
        ) from None
