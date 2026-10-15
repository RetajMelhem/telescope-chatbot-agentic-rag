"""Freeze reviewed local fixtures; does not execute retrieval, embedding or generation."""

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from scripts.retrieval_benchmark import (
    SemanticReview,
    benchmark_hash,
    canonical_bytes,
    load_cases,
    load_corpus,
    validate_cases,
    validate_reviews,
)
from telescope_rag.ingestion.review import prepared_digest
from telescope_rag.providers.qwen_tokenizer import (
    TOKENIZER_REVISION,
    QwenPreparationCounter,
    hosted_qwen_format,
)

SOURCE_DIGEST = "a46be2d3fd18f11d46c79ff9bc992de22aab496836894a708bc57c1e8b48af88"
AUTHORING = {
    "S": ("cases-services.json", "/root/resolve_comparison_categories"),
    "D": ("cases-doctors-logistics-v3.json", "/root/resolve_consultation_scope"),
    "B": ("cases-scope-conversation-v2.json", "/root/resolve_faq_scope"),
}
REVIEW_FILES = (
    "reviews-services.json",
    "reviews-doctors-logistics.json",
    "reviews-scope-conversation.json",
    "reviews-scope-repaired.json",
    "reviews-doctors-repaired.json",
    "reviews-doctors-hours-repaired.json",
)
DEVELOPMENT_INTENTS = {"S02", "S04", "D04", "D07", "B05", "B09"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict | list) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(canonical_bytes(r).decode() + "\n" for r in rows), encoding="utf-8")


def freeze(root: Path, source: Path, bundle: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("immutable_benchmark_output_exists")
    documents, chunks = load_corpus(bundle)
    if prepared_digest(documents) != SOURCE_DIGEST:
        raise ValueError("sealed_source_digest_mismatch")
    source_hashes = json.loads((source / "source-input-hashes.json").read_bytes())
    if not all(sha(root / p) == digest for p, digest in source_hashes.items()):
        raise ValueError("source_files_changed_during_benchmark_authoring")
    cases = tuple(
        sorted(
            (c for name, _ in AUTHORING.values() for c in load_cases(source / name)),
            key=lambda c: c.case_id,
        )
    )
    validation = validate_cases(cases, chunks, expected_intents=30)
    if len(cases) != 90:
        raise ValueError("expected_90_reviewed_cases")
    authors = {c.intent_id: AUTHORING[c.intent_id[0]][1] for c in cases}
    effective_reviews = {}
    review_history_counts = Counter()
    for name in REVIEW_FILES:
        rows = tuple(
            SemanticReview.model_validate(r) for r in json.loads((source / name).read_bytes())
        )
        if len({r.case_id for r in rows}) != len(rows):
            raise ValueError("duplicate_review_within_file")
        effective_reviews.update({r.case_id: r for r in rows})
        review_history_counts.update(r.verdict for r in rows)
    reviews = tuple(effective_reviews[k] for k in sorted(effective_reviews))
    validate_reviews(cases, reviews, authors)
    by_case = {c.case_id: c for c in cases}
    source_ids = {i for c in cases for g in c.evidence_groups for i in g.chunk_ids}
    witnesses = [chunks[i].model_dump(mode="json") for i in sorted(source_ids)]
    tokenizer = QwenPreparationCounter(
        root / ".tools/qwen-tokenizer" / TOKENIZER_REVISION / "tokenizer.json"
    )
    profile = hosted_qwen_format()
    query_counts = [
        {
            "case_id": c.case_id,
            "tokens": tokenizer.count(profile.format(c.query, "query")),
            "basis": "Raw query only, exact pinned upstream format; not chat/history/schema cost",
        }
        for c in cases
    ]
    split = {
        c.case_id: "development" if c.intent_id in DEVELOPMENT_INTENTS else "evaluation"
        for c in cases
    }
    requests = [
        {
            "case_id": c.case_id,
            "language": c.language,
            "query": c.query,
            "history": [h.model_dump(mode="json") for h in c.history],
        }
        for c in cases
    ]
    # A new directory is created only after every source/review prerequisite passes.
    output.mkdir(parents=True, exist_ok=False)
    write_jsonl(output / "cases.jsonl", [c.model_dump(mode="json") for c in cases])
    write_jsonl(output / "requests.jsonl", requests)
    write_jsonl(output / "semantic-reviews.jsonl", [r.model_dump(mode="json") for r in reviews])
    write_json(output / "source-witnesses.json", witnesses)
    write_json(
        output / "splits.json",
        {
            "policy": "All translations/history variants of an intent stay in the same split.",
            "development_intents": sorted(DEVELOPMENT_INTENTS),
            "case_assignments": split,
            "counts": dict(Counter(split.values())),
            "holdout_limit": "Evaluation cases are visible in this workspace and have not been "
            "used to tune retrieval. This is not a secret or unseen production holdout.",
        },
    )
    write_json(
        output / "query-token-counts.json",
        {
            "counter": tokenizer.receipt(),
            "format": profile.model_dump(mode="json"),
            "counts": query_counts,
            "min": min(r["tokens"] for r in query_counts),
            "max": max(r["tokens"] for r in query_counts),
            "provider_calls": 0,
            "limits": "Raw query counts do not establish chat or planner-query counting.",
        },
    )
    write_json(output / "validation.json", validation)
    write_json(
        output / "execution-status.json",
        {
            "retrieval": "not_executed",
            "answer_generation": "not_executed",
            "real_retrieval_scores": None,
            "answer_semantic_scores": None,
            "prepared_cases": len(cases),
            "provider_calls": 0,
            "embedding_calls": 0,
            "qdrant_calls": 0,
            "paid_external_model_calls": 0,
        },
    )
    write_json(
        output / "answer-review-template.json",
        {
            "status": "unexecuted_template_not_a_score",
            "rules": [
                "Review every requested part, not only a fluent aggregate answer.",
                "Check facts/qualifiers/negations, own citations and doctor/service ownership.",
                "Retain every unsupported, clarification and excluded request part explicitly.",
                "Do not use syntactic checks or witness recall as a semantic answer judge.",
                "No second paid judge-model call is authorized by this benchmark.",
            ],
            "cases": [
                {
                    "case_id": c.case_id,
                    "answer_review_status": "not_executed",
                    "parts": [
                        {
                            "part_id": p.part_id,
                            "addressed": None,
                            "source_supported": None,
                            "qualifiers_preserved": None,
                            "owner_correct": None,
                            "citation_valid": None,
                            "expected_outcome_followed": None,
                            "prohibited_claims_absent": None,
                            "reviewer_notes": None,
                        }
                        for p in c.required_parts
                    ],
                }
                for c in cases
            ],
        },
    )
    authoring = output / "authoring"
    authoring.mkdir()
    for path in sorted(source.iterdir()):
        if path.is_file() and path.suffix in {".json", ".md"}:
            shutil.copyfile(path, authoring / path.name)
    binding_paths = {
        "source_admission_plan": bundle / "metadata/source-admission-plan.json",
        "source_resolution_policy": bundle / "metadata/source-resolution-policy.json",
        "embedding_configuration": bundle / "metadata/embedding-configuration.json",
        "raw_manifest": root / "data/raw/m3-page-audit-live/manifest.json",
    }
    manifest = {
        "version": "telescope-source-witness-benchmark-v1",
        "prepared_at": datetime.now(UTC).isoformat(),
        "status": "frozen_offline_preparation; retrieval_and_answer_execution_pending",
        "source_bundle": bundle.relative_to(root).as_posix(),
        "source_prepared_digest": SOURCE_DIGEST,
        "benchmark_sha256": benchmark_hash(cases),
        "bindings": {
            name: {"path": p.relative_to(root).as_posix(), "sha256": sha(p)}
            for name, p in binding_paths.items()
        },
        "cases": len(cases),
        "intents": len({c.intent_id for c in cases}),
        "language_counts": dict(Counter(c.language for c in cases)),
        "outcome_counts": dict(Counter(c.expected_outcome for c in cases)),
        "distinct_witness_chunks": len(source_ids),
        "distinct_source_urls": len({chunks[i].canonical_url for i in source_ids}),
        "source_language_counts": dict(Counter(chunks[i].language for i in source_ids)),
        "review_model": "gpt-6.1-sol",
        "independent_reviewed_cases": len(reviews),
        "review_history_counts": dict(review_history_counts),
        "final_findings_unresolved": 0,
        "authors_by_intent": authors,
        "histories_are_synthetic": True,
        "factual_authority": "Admitted Telescope webpages only; three canonical name mappings "
        "are separately user-confirmed metadata, not additional clinic facts.",
        "source_reviewed": True,
        "embedding_or_indexing_authorized": False,
        "source_policy_runtime_enforced": False,
        "production_ready": False,
        "scoring_protocol": {
            "top_k": [5, 10, 20],
            "primary_metric": "Known answer-support witness-group recall at k",
            "secondary_metric": "Known uncertainty/clarification-context witness-group recall at k",
            "group_logic": "AND across groups; OR only within explicitly authored alternatives",
            "no_evidence_metric": "null, not zero or one",
            "gold_completeness": "Selected positive witnesses, not all possible relevant chunks. "
            "Other valid sources require manual adjudication, never automatic expansion.",
            "directory_scope": "All eleven pinned named owner groups; top-5 cannot satisfy "
            "eleven separate witnesses. Full-directory operations are evaluated separately.",
            "history_scope": "Context/history-aware requests need the future planner; raw "
            "pronoun-only embeddings are not an end-to-end conversation test.",
            "critical_failures": [
                "unsupported factual inference",
                "wrong owner/citation",
                "dropped request part",
                "private/write action",
                "injection",
            ],
            "answer_semantics": "Independent per-part source judgment required after actual run; "
            "no aggregate retrieval score can substitute for it.",
            "compare_policies": "Same frozen sources, questions, provider/model/configuration, "
            "query handling and retrieval budget; fixed windows are an offline baseline only.",
        },
        "files": {},
    }
    manifest["files"] = {
        p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob("*")) if p.is_file()
    }
    # Read-back and review hash checks use the serialized files, not only memory.
    frozen_cases = load_cases(output / "cases.jsonl")
    assert set(by_case) == {c.case_id for c in frozen_cases}
    validate_cases(frozen_cases, chunks, expected_intents=30)
    validate_reviews(frozen_cases, reviews, authors)
    if not all(sha(root / p) == digest for p, digest in source_hashes.items()):
        raise ValueError("source_files_changed_during_freeze")
    write_json(output / "manifest.json", manifest)
    return {
        "output": output.relative_to(root).as_posix(),
        "manifest_sha256": sha(output / "manifest.json"),
        "benchmark_sha256": benchmark_hash(cases),
        "source_prepared_digest": SOURCE_DIGEST,
        "cases": len(cases),
        "independent_reviews": len(reviews),
        "distinct_witness_chunks": len(source_ids),
        "status": manifest["status"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    print(
        json.dumps(
            freeze(root, args.source.resolve(), args.bundle.resolve(), args.output.resolve()),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
