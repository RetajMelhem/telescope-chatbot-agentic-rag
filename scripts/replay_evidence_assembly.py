"""Freeze/replay cached retrieval locally. No credentials, model or index calls.

The raw queries remain opaque single retrieval probes, not semantic request
plans. Frozen gold is used solely by scoring after all rankings are persisted.
"""

import argparse
import hashlib
import json
import statistics
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from scripts.check_frozen_benchmark import verify
from scripts.retrieval_benchmark import canonical_bytes, load_cases, load_corpus
from telescope_rag.ingestion.deduplication import embedding_input_key
from telescope_rag.ingestion.indexing import EmbeddingCache
from telescope_rag.providers.qwen_tokenizer import QwenPreparationCounter
from telescope_rag.retrieval.assembly import (
    AssemblyRequest,
    EvidenceCatalog,
    RequestPart,
    evidence_group_key,
)
from telescope_rag.retrieval.cached_dense import CachedDenseRanker
from telescope_rag.retrieval.query_vectors import QueryText, plan_queries

BENCHMARK = Path("artifacts/m3-retrieval-benchmark-v1")
SOURCE = Path("data/processed/m3-llm-semantic-token-validated-v6")
DOC_CACHE = Path("data/processed/m3-qwen-cache-v6-v1")
QUERY_CACHE = Path("data/processed/m4-query-cache-v1")
TOKENIZER = Path(".tools/qwen-tokenizer/1d8ad4ca9b3dd8059ad90a75d4983776a23d44af/tokenizer.json")
MANIFEST = "ee9ace13c784f6c8182ec9f9db4cf76fdc39dc24dc82ba9ad62c8c1b18dbd499"
ARMS = ("cached_occurrence20", "cached_pool20_coalesced", "cached_distinct20")
# Exact historical receipt bytes, independently checked before this experiment.
# These are local integrity anchors, not signatures or new provider attestations.
CORPUS_PLAN = "artifacts/m3-candidate-execution-v6-v1/plan.json"
DOCUMENT_REVIEW = "artifacts/m3-candidate-authorization-v1/post-execution-independent-review.json"
QUERY_REVIEW = "artifacts/m4-retrieval-comparison-v1/post-execution-independent-review.json"
REFERENCE_SHA256 = {
    CORPUS_PLAN: "bdf0dda87e811cfcae8516dce679ea865be9b109276fe2f6cf629e4782298e42",
    DOCUMENT_REVIEW: "8af43954a815c6e7ec40a815023e58d633a46d21a4bbc3a87ddc0225014b17f7",
    QUERY_REVIEW: "148b42c4bfb7bff6fe5aaf4349f6367b002de4b61fa597a0aeebed0f17199c24",
}


def write(path: Path, value: dict):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def historical_bindings(root: Path, prepared_digest: str) -> tuple[dict, dict, dict]:
    for relative, expected in REFERENCE_SHA256.items():
        if file_hash(root / relative) != expected:
            raise ValueError("replay_historical_reference_changed")
    corpus_plan = json.loads((root / CORPUS_PLAN).read_bytes())
    if corpus_plan["prepared_digest"] != prepared_digest:
        raise ValueError("replay_original_configuration_source_mismatch")
    documents = json.loads((root / DOCUMENT_REVIEW).read_bytes())["validated_cache_entries"]
    queries = json.loads((root / QUERY_REVIEW).read_bytes())["cache_inventory"]
    document_hashes = {r["input_key"]: r["file_sha256"] for r in documents}
    query_hashes = {n.removesuffix(".json"): r["file_sha256"] for n, r in queries.items()}
    if (
        len(documents) != 834
        or len(document_hashes) != 834
        or len(queries) != 90
        or len(query_hashes) != 90
        or any(r["dimensions"] != 4096 for r in (*documents, *queries.values()))
        or any(n != f"{k}.json" for n, k in zip(queries, query_hashes, strict=True))
    ):
        raise ValueError("replay_historical_cache_inventory_invalid")
    return corpus_plan, document_hashes, query_hashes


def attested_vector(cache, key: str, configuration: str, expected_hash: str):
    """Refuse a self-consistent vector rewritten since the hosted run."""
    path = cache.directory / f"{key}.json"
    if not path.is_file() or file_hash(path) != expected_hash:
        raise ValueError("replay_cache_differs_from_original_hosted_run")
    vector = cache.get(key, configuration, 4096)
    if vector is None or file_hash(path) != expected_hash:
        raise ValueError("replay_cache_changed_during_read")
    return vector


def score_groups(case, occurrence_groups: list[list[str]], *, k: int) -> dict:
    """Selected witness membership after K presentation units, not semantic coverage."""
    if (
        type(k) is not int
        or k < 1
        or any(not g or len(g) != len(set(g)) for g in occurrence_groups)
    ):
        raise ValueError("invalid_scored_groups")
    if len({i for g in occurrence_groups for i in g}) != sum(map(len, occurrence_groups)):
        raise ValueError("scored_occurrence_in_multiple_groups")
    top = {i for group in occurrence_groups[:k] for i in group}
    output = {}
    for name, roles in (
        ("support", {"answer_support"}),
        ("context", {"uncertainty_context", "clarification_context"}),
    ):
        groups = [g for g in case.evidence_groups if g.role in roles]
        hits = [g.group_id for g in groups if top.intersection(g.chunk_ids)]
        output[name] = {
            "expected_groups": len(groups),
            "hit_groups": hits,
            "recall": len(hits) / len(groups) if groups else None,
        }
    return output


def prepare(root: Path) -> tuple[dict, tuple, EvidenceCatalog, QwenPreparationCounter]:
    verified = verify(root, root / BENCHMARK, MANIFEST)
    documents, chunks = load_corpus(root / SOURCE)
    if len(chunks) != 955:
        raise ValueError("replay_source_inventory_changed")
    requests = tuple(
        json.loads(line)
        for line in (root / BENCHMARK / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    )
    if len(requests) != 90 or any(
        set(r) != {"case_id", "language", "query", "history"} for r in requests
    ):
        raise ValueError("replay_raw_request_inventory_invalid")
    counter = QwenPreparationCounter(root / TOKENIZER)
    corpus_plan, _, _ = historical_bindings(root, verified["prepared_digest"])
    configuration = corpus_plan["configuration_hash"]
    query_plan = plan_queries(
        [QueryText(r["case_id"], r["query"]) for r in requests], counter, configuration
    )
    catalog = EvidenceCatalog(documents, expected_digest=verified["prepared_digest"])
    code = (
        "src/telescope_rag/retrieval/assembly.py",
        "src/telescope_rag/retrieval/cached_dense.py",
        "scripts/replay_evidence_assembly.py",
    )
    plan = {
        "version": "offline-exact-grouping-assembly-v1",
        "prepared_digest": verified["prepared_digest"],
        "benchmark_manifest_sha256": MANIFEST,
        "benchmark_sha256": verified["benchmark_sha256"],
        "requests_sha256": file_hash(root / BENCHMARK / "requests.jsonl"),
        "configuration_hash": configuration,
        "historical_reference_sha256": REFERENCE_SHA256,
        "cache_integrity": "all 834 document and 90 query files must match the original "
        "independently recorded hosted-run SHA-256 inventories before ranking",
        "query_plan": query_plan,
        "arms": ARMS,
        "candidate_limit": 20,
        "max_rendered_groups": 16,
        "max_rendered_qwen_tokens": 6000,
        "score_cutoffs": [5, 10, 20],
        "search": "exact normalized float64 cosine over all 955 cached occurrences; "
        "score-desc/chunk-id ties",
        "comparison": "same engine/query/vector/source/token budget; "
        "cached_pool20_coalesced isolates assembly, "
        "cached_distinct20 additionally groups before limiting",
        "query_handling": "opaque whole raw query; one public retrieval-only probe; "
        "no planner, subquestion interpretation, private action or source-scope inference",
        "membership_scoring": "each selected rendered unit retains all explicitly ranked "
        "member occurrences; strict frozen selected-witness membership only",
        "no_claims": [
            "Qdrant float32 ranking identity",
            "semantic answer support",
            "complete request decomposition",
            "source-evidence equivalence beyond exact group key",
            "new holdout acceptance",
            "nDCG",
            "Luna input admission",
        ],
        "provider_calls": 0,
        "index_calls": 0,
        "corpus_changes": 0,
        "implementation_sha256": {str(p): file_hash(root / p) for p in code},
    }
    return plan, requests, catalog, counter


def execute(root: Path, output: Path, plan: dict, requests: tuple, catalog, counter) -> dict:
    if any(
        p.name in {"cache-inventory.json", "result.json", "failure.json"}
        or p.name.startswith("case-")
        for p in output.iterdir()
    ):
        raise ValueError("replay_already_started_use_new_output")
    caches = (root / DOC_CACHE, root / QUERY_CACHE)
    if any(not p.is_dir() for p in caches):
        raise ValueError("replay_requires_existing_cache")
    document_cache, query_cache = (EmbeddingCache(p) for p in caches)
    config = plan["configuration_hash"]
    corpus_plan, document_hashes, query_hashes = historical_bindings(root, plan["prepared_digest"])
    if (
        corpus_plan["configuration_hash"] != config
        or set(document_hashes) != {embedding_input_key(c, config) for c in catalog.chunks.values()}
        or set(query_hashes) != {r["key"] for r in plan["query_plan"]["queries"]}
    ):
        raise ValueError("replay_original_cache_membership_or_configuration_mismatch")
    document_vectors, cache_hashes, unique_vectors = {}, {}, {}
    for c in catalog.chunks.values():
        key = embedding_input_key(c, config)
        if key not in unique_vectors:
            vector = attested_vector(document_cache, key, config, document_hashes[key])
            unique_vectors[key] = vector
            path = root / DOC_CACHE / f"{key}.json"
            cache_hashes[str(path.relative_to(root))] = file_hash(path)
        document_vectors[c.chunk_id] = unique_vectors[key]
    queries = {}
    for row in plan["query_plan"]["queries"]:
        vector = attested_vector(query_cache, row["key"], config, query_hashes[row["key"]])
        queries[row["query_id"]] = vector
        path = root / QUERY_CACHE / f"{row['key']}.json"
        cache_hashes[str(path.relative_to(root))] = file_hash(path)
    write(
        output / "cache-inventory.json",
        {
            "files": cache_hashes,
            "document_inputs": len(unique_vectors),
            "query_inputs": len(queries),
            "provider_calls": 0,
        },
    )
    ranker = CachedDenseRanker(catalog.chunks, document_vectors)
    timings, rows = [], []
    for index, request in enumerate(requests, 1):
        tick = time.perf_counter()
        plain = ranker.search(queries[request["case_id"]], limit=20)
        plain_seconds = time.perf_counter() - tick
        tick = time.perf_counter()
        distinct = ranker.search(
            queries[request["case_id"]], limit=20, group_key=evidence_group_key
        )
        distinct_seconds = time.perf_counter() - tick
        simple_ids = [h.chunk_id for h in plain]
        grouped_ids = [
            i
            for h in distinct
            for i in (h.chunk_id, *[i for i in h.occurrence_ids if i != h.chunk_id])
        ]
        probe = AssemblyRequest(
            original_query=request["query"],
            parts=(RequestPart(part_id="raw", start=0, end=len(request["query"])),),
        )
        row = {
            "case_id": request["case_id"],
            "language": request["language"],
            "raw_occurrence_ranking": simple_ids,
            "distinct_ranking": [asdict(h) for h in distinct],
            "arms": {},
        }
        for arm in ARMS:
            tick = time.perf_counter()
            assembled = catalog.assemble(
                probe,
                {"raw": grouped_ids if arm == ARMS[2] else simple_ids},
                counter=counter,
                max_tokens=6000,
                max_groups=16,
                coalesce_exact=arm != ARMS[0],
            )
            group_ids = [[c.chunk_id for c in g.occurrences] for g in assembled.groups]
            row["arms"][arm] = {
                "rendered_groups": group_ids,
                "rendered_text": assembled.rendered_text,
                "tokens": assembled.token_count,
                "part_receipts": [asdict(p) for p in assembled.parts],
                "semantic_support_assessed": assembled.semantic_support_assessed,
                "luna_input_admitted": assembled.luna_input_admitted,
            }
            timings.append(
                {
                    "case_id": request["case_id"],
                    "arm": arm,
                    "assembly_ms": (time.perf_counter() - tick) * 1000,
                }
            )
        row["search_seconds"] = {"plain": plain_seconds, "distinct": distinct_seconds}
        write(output / f"case-{index:04}.json", row)
        rows.append(row)
        if index % 10 == 0:
            print(
                json.dumps({"cached_replay_completed": index, "total": len(requests)}), flush=True
            )
    # All actual source selections are sealed before accessing gold for scoring.
    cases = {c.case_id: c for c in load_cases(root / BENCHMARK / "cases.jsonl")}
    split = json.loads((root / BENCHMARK / "splits.json").read_bytes())["case_assignments"]
    scores = []
    for row in rows:
        case = cases[row["case_id"]]
        for arm, data in row["arms"].items():
            for k in (5, 10, 20):
                scores.append(
                    {
                        "case_id": case.case_id,
                        "language": case.language,
                        "split": split[case.case_id],
                        "arm": arm,
                        "k": k,
                        "selection_eligible": not case.history
                        and "exhaustive_directory" not in case.tags,
                        "metrics": score_groups(case, data["rendered_groups"], k=k),
                    }
                )
    summaries = {}
    for arm in ARMS:
        summaries[arm] = {}
        for k in (5, 10, 20):
            for split_name in ("development", "evaluation"):
                for language in ("all", "en", "ar", "ar-JO"):
                    selected = [
                        r
                        for r in scores
                        if r["arm"] == arm
                        and r["k"] == k
                        and r["split"] == split_name
                        and r["selection_eligible"]
                        and (language == "all" or r["language"] == language)
                    ]
                    summaries[arm][f"{split_name}/{language}/k{k}"] = {
                        role: {
                            "cases": len(values),
                            "macro_recall": statistics.mean(values) if values else None,
                        }
                        for role in ("support", "context")
                        for values in [
                            [
                                r["metrics"][role]["recall"]
                                for r in selected
                                if r["metrics"][role]["recall"] is not None
                            ]
                        ]
                    }
    write(output / "scores.json", {"rows": scores, "limits": plan["membership_scoring"]})
    write(
        output / "timings.json",
        {
            "assembly": timings,
            "search": [{"case_id": r["case_id"], **r["search_seconds"]} for r in rows],
        },
    )
    result = {
        "status": "offline_cached_retrieval_assembly_executed",
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "queries": len(rows),
        "arms": ARMS,
        "summaries": summaries,
        "rendering": {
            arm: {
                "mean_groups": statistics.mean(
                    len(r["arms"][arm]["rendered_groups"]) for r in rows
                ),
                "mean_qwen_tokens": statistics.mean(r["arms"][arm]["tokens"] for r in rows),
                "max_qwen_tokens": max(r["arms"][arm]["tokens"] for r in rows),
            }
            for arm in ARMS
        },
        "provider_calls": 0,
        "index_calls": 0,
        "source_changes": 0,
        "new_semantic_review": "separate review records; scores are not semantic judgments",
        "new_holdout_acceptance": False,
        "ndcg_measured": False,
        "production_ready": False,
    }
    write(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--execute-offline", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / "artifacts"):
        raise ValueError("replay_output_must_be_local_artifact")
    output.mkdir(parents=True, exist_ok=True)
    plan, requests, catalog, counter = prepare(root)
    path = output / "experiment-plan.json"
    if path.exists():
        if json.loads(path.read_bytes()) != json.loads(canonical_bytes(plan)):
            raise ValueError("replay_frozen_plan_changed")
    else:
        write(path, plan)
    if args.execute_offline:
        result = execute(root, output, plan, requests, catalog, counter)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "queries": result["queries"],
                    "provider_calls": 0,
                    "index_calls": 0,
                }
            )
        )
    else:
        print(
            json.dumps(
                {
                    "status": "prepared_offline_only",
                    "queries": len(requests),
                    "provider_calls": 0,
                    "index_calls": 0,
                }
            )
        )


if __name__ == "__main__":
    main()
