"""Read-only offline checks of a frozen benchmark and its pinned source bundle."""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from scripts.retrieval_benchmark import (
    SemanticReview,
    benchmark_hash,
    load_cases,
    load_corpus,
    validate_cases,
    validate_reviews,
)
from telescope_rag.ingestion.review import prepared_digest


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inventory(directory: Path, expected_manifest_hash: str) -> dict:
    manifest_file = directory / "manifest.json"
    if file_hash(manifest_file) != expected_manifest_hash:
        raise ValueError("benchmark_manifest_hash_mismatch")
    manifest = json.loads(manifest_file.read_bytes())
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("frozen_file_inventory_changed")
    for relative, digest in manifest["files"].items():
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("frozen_file_path_escape")
        if file_hash(path) != digest:
            raise ValueError("frozen_file_hash_mismatch")
    return manifest


def verify(root: Path, directory: Path, expected_manifest_hash: str) -> dict:
    manifest = verify_inventory(directory, expected_manifest_hash)
    for binding in manifest["bindings"].values():
        path = (root / binding["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or file_hash(path) != binding["sha256"]:
            raise ValueError("frozen_source_binding_mismatch")
    bundle = (root / manifest["source_bundle"]).resolve()
    if not bundle.is_relative_to(root.resolve()):
        raise ValueError("frozen_source_path_escape")
    documents, chunks = load_corpus(bundle)
    digest = prepared_digest(documents)
    if digest != manifest["source_prepared_digest"]:
        raise ValueError("frozen_prepared_digest_mismatch")
    cases = load_cases(directory / "cases.jsonl")
    validation = validate_cases(cases, chunks, expected_intents=30)
    if benchmark_hash(cases) != manifest["benchmark_sha256"]:
        raise ValueError("frozen_benchmark_hash_mismatch")
    reviews = tuple(
        SemanticReview.model_validate_json(line)
        for line in (directory / "semantic-reviews.jsonl").read_text(encoding="utf-8").splitlines()
    )
    validate_reviews(cases, reviews, manifest["authors_by_intent"])
    requests = [
        json.loads(line)
        for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    expected_requests = [
        {
            "case_id": c.case_id,
            "language": c.language,
            "query": c.query,
            "history": [h.model_dump(mode="json") for h in c.history],
        }
        for c in cases
    ]
    if requests != expected_requests:
        raise ValueError("request_export_changed_or_gold_leaked")
    ids = {i for c in cases for g in c.evidence_groups for i in g.chunk_ids}
    witnesses = json.loads((directory / "source-witnesses.json").read_bytes())
    if witnesses != [chunks[i].model_dump(mode="json") for i in sorted(ids)]:
        raise ValueError("source_witness_payload_changed")
    assignments = json.loads((directory / "splits.json").read_bytes())["case_assignments"]
    if set(assignments) != {c.case_id for c in cases}:
        raise ValueError("split_coverage_mismatch")
    intent_splits = defaultdict(set)
    for case in cases:
        intent_splits[case.intent_id].add(assignments[case.case_id])
    if any(len(values) != 1 for values in intent_splits.values()):
        raise ValueError("language_variants_cross_splits")
    if not all(assignment in {"development", "evaluation"} for assignment in assignments.values()):
        raise ValueError("unknown_split")
    status = json.loads((directory / "execution-status.json").read_bytes())
    if status["retrieval"] != "not_executed" or status["answer_generation"] != "not_executed":
        raise ValueError("preparation_artifact_cannot_claim_execution")
    if status["real_retrieval_scores"] is not None or status["answer_semantic_scores"] is not None:
        raise ValueError("unexecuted_benchmark_cannot_claim_scores")
    return {
        **validation,
        "prepared_digest": digest,
        "manifest_sha256": expected_manifest_hash,
        "independent_reviews": len(reviews),
        "all_frozen_file_hashes_match": True,
        "requests_contain_no_gold_answers_or_sources": True,
        "source_witnesses_and_split_integrity_passed": True,
        "retrieval_executed": False,
        "answer_generation_executed": False,
        "provider_calls": 0,
        "embedding_calls": 0,
        "qdrant_calls": 0,
        "limits": "Integrity checks bind actual authored reviews; they do not replace semantic "
        "judgment or establish real retrieval/answer performance.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(verify(root, args.benchmark.resolve(), args.manifest_sha256), indent=2))


if __name__ == "__main__":
    main()
