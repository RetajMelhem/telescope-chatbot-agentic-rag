"""Synthetic contract checks; no real retrieval, answers, models or services."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from telescope_rag.ingestion.models import PreparedChunk

SPEC = importlib.util.spec_from_file_location(
    "offline_retrieval_benchmark", Path(__file__).parents[2] / "scripts/retrieval_benchmark.py"
)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def case_data(language: str = "en") -> dict:
    return {
        "case_id": f"T01-{language}",
        "intent_id": "T01",
        "language": language,
        "query": "Synthetic clinic fact?",
        "history": [],
        "tags": ["synthetic"],
        "expected_outcome": "supported",
        "required_parts": [
            {
                "part_id": "p1",
                "request": "Fact",
                "outcome": "supported",
                "required_claims": ["Synthetic fact."],
                "prohibited_claims": ["Other doctor"],
                "evidence_group_ids": ["g1"],
            }
        ],
        "evidence_groups": [
            {
                "group_id": "g1",
                "role": "answer_support",
                "chunk_ids": ["c1", "c2"],
                "source_reason": "Explicit synthetic alternatives with same supporting claim.",
                "quotes": [
                    {"chunk_id": "c1", "quote": "Synthetic fact."},
                    {"chunk_id": "c2", "quote": "Synthetic fact."},
                ],
            }
        ],
        "prohibited_actions": ["No service access"],
        "policy_references": ["Synthetic test policy"],
        "semantic_rationale": "Synthetic contract fixture, not a Telescope fact.",
    }


def cases() -> tuple:
    return tuple(
        benchmark.BenchmarkCase.model_validate(case_data(lang)) for lang in ("en", "ar", "ar-JO")
    )


def chunks() -> dict:
    # Only these fields are read by this validator/scorer. No synthetic record is
    # prepared, embedded, written to a corpus or marked production compatible.
    return {
        i: PreparedChunk.model_construct(
            chunk_id=i,
            retrieval_text="Synthetic fact.",
            canonical_url="https://telescopecenter.com/synthetic-test-only/",
        )
        for i in ("c1", "c2", "distractor")
    }


def receipts(case_rows: tuple, ranked: tuple[str, ...] = ("c1",)) -> tuple:
    return tuple(
        benchmark.RetrievalReceipt(
            case_id=c.case_id,
            prepared_digest="SYNTHETIC",
            benchmark_sha256=benchmark.benchmark_hash(case_rows),
            execution_kind="synthetic_contract_test",
            ranked_chunk_ids=ranked,
        )
        for c in case_rows
    )


def review(case) -> dict:
    return {
        "case_id": case.case_id,
        "case_sha256": benchmark.case_hash(case),
        "reviewer_agent": "independent",
        "model": "gpt-6.1-sol",
        "verdict": "pass",
        "rationale": "SYNTHETIC review receipt tests validation only, no semantic review claimed.",
        "reviewed_chunk_ids": ["c1", "c2"],
        "findings": [],
        "request_language_preserved": True,
    }


def test_complete_language_variants_and_explicit_alternatives_validate():
    result = benchmark.validate_cases(cases(), chunks(), expected_intents=1)
    assert result["cases"] == 3 and result["distinct_witness_chunks"] == 2
    assert result["semantic_acceptance_established_by_validator"] is False


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda d: d.update(case_id="wrong"), "identity_language"),
        (lambda d: d.update(unapproved_extra="x"), "Extra inputs"),
        (lambda d: d["required_parts"][0].update(outcome="unsupported"), "cannot_claim_answer"),
        (lambda d: d["required_parts"][0].update(evidence_group_ids=[]), "orphan_evidence"),
        (lambda d: d["evidence_groups"][0].update(role="uncertainty_context"), "requires_answer"),
        (lambda d: d["evidence_groups"][0].update(chunk_ids=["c1", "c1"]), "duplicate_evidence"),
        (lambda d: d["evidence_groups"][0].update(quotes=[]), "at least 1"),
        (lambda d: d.update(expected_outcome="partial"), "overstates_request"),
    ],
)
def test_invalid_gold_boundaries_are_rejected(change, match):
    data = case_data()
    change(data)
    with pytest.raises(ValidationError, match=match):
        benchmark.BenchmarkCase.model_validate(data)


@pytest.mark.parametrize("kind", ["unknown_id", "invented_quote", "external_source"])
def test_unbacked_source_witnesses_rejected(kind):
    data = case_data()
    source = chunks()
    if kind == "unknown_id":
        source.pop("c1")
    elif kind == "invented_quote":
        data["evidence_groups"][0]["quotes"][0]["quote"] = "Invented"
    else:
        source["c1"] = source["c1"].model_copy(
            update={"canonical_url": "https://unapproved.invalid/"}
        )
    row = benchmark.BenchmarkCase.model_validate(data)
    with pytest.raises(ValueError, match="unknown_source|quotation_not|non_official"):
        benchmark.validate_cases((row,), source)


def test_language_coverage_missing_variant_and_request_part_drift_rejected():
    with pytest.raises(ValueError, match="language_variant"):
        benchmark.validate_cases(cases()[:2], chunks())
    data = case_data("ar-JO")
    data["required_parts"][0]["part_id"] = "silently_different_part"
    changed = (*cases()[:2], benchmark.BenchmarkCase.model_validate(data))
    with pytest.raises(ValueError, match="request_structure_drift"):
        benchmark.validate_cases(changed, chunks())


@pytest.mark.parametrize("kind", ["missing", "duplicate", "stale", "self", "source", "finding"])
def test_incomplete_stale_or_self_review_cannot_seal(kind):
    rows = cases()
    reviews = [review(c) for c in rows]
    if kind == "missing":
        reviews.pop()
    elif kind == "duplicate":
        reviews.append(reviews[0])
    elif kind == "stale":
        reviews[0]["case_sha256"] = "old-draft"
    elif kind == "self":
        reviews[0]["reviewer_agent"] = "author"
    elif kind == "source":
        reviews[0]["reviewed_chunk_ids"] = ["c1"]
    else:
        reviews[0]["findings"] = ["Unfixed source-scope problem"]
    with pytest.raises(ValueError, match="review"):
        benchmark.validate_reviews(
            rows,
            tuple(benchmark.SemanticReview.model_validate(v) for v in reviews),
            {"T01": "author"},
        )


def test_valid_independent_review_receipts_bind_exact_cases():
    rows = cases()
    benchmark.validate_reviews(
        rows,
        tuple(benchmark.SemanticReview.model_validate(review(c)) for c in rows),
        {"T01": "author"},
    )


def test_or_alternatives_credit_only_explicit_anchors_and_obey_top_k():
    rows = cases()
    provided = receipts(rows, ("distractor", "c2"))
    short = benchmark.score_receipts(rows, provided, chunks(), source_digest="SYNTHETIC", k=1)
    longer = benchmark.score_receipts(rows, provided, chunks(), source_digest="SYNTHETIC", k=2)
    assert short["cases"][0]["metrics"]["answer_support"]["witness_group_recall"] == 0
    assert longer["cases"][0]["metrics"]["answer_support"]["witness_group_recall"] == 1
    assert longer["execution_kind"] == "synthetic_contract_test"
    assert not longer["cases"][0]["answer_semantics_assessed"]


def test_and_groups_cannot_be_satisfied_by_one_group():
    data = case_data()
    other = dict(
        data["evidence_groups"][0],
        group_id="g2",
        chunk_ids=["distractor"],
        quotes=[{"chunk_id": "distractor", "quote": "Synthetic fact."}],
    )
    data["evidence_groups"].append(other)
    data["required_parts"][0]["evidence_group_ids"].append("g2")
    rows = (benchmark.BenchmarkCase.model_validate(data),)
    result = benchmark.score_receipts(
        rows, receipts(rows), chunks(), source_digest="SYNTHETIC", k=5
    )
    metric = result["cases"][0]["metrics"]["answer_support"]
    assert metric["witness_group_recall"] == 0.5 and not metric["all_witness_groups_found"]


def test_uncertainty_context_does_not_count_as_answer_support():
    data = case_data()
    data["evidence_groups"][0]["role"] = "uncertainty_context"
    data["required_parts"][0]["outcome"] = data["expected_outcome"] = "unsupported"
    rows = (benchmark.BenchmarkCase.model_validate(data),)
    result = benchmark.score_receipts(
        rows, receipts(rows), chunks(), source_digest="SYNTHETIC", k=5
    )
    metrics = result["cases"][0]["metrics"]
    assert metrics["answer_support"]["witness_group_recall"] is None
    assert metrics["uncertainty_or_clarification"]["witness_group_recall"] == 1


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "duplicate",
        "wrong_digest",
        "wrong_benchmark",
        "duplicate_hit",
        "unknown_hit",
        "mixed_kind",
    ],
)
def test_invalid_retrieval_receipts_rejected(kind):
    rows = cases()
    provided = list(receipts(rows))
    if kind == "missing":
        provided.pop()
    elif kind == "duplicate":
        provided.append(provided[0])
    else:
        update = {
            "wrong_digest": {"prepared_digest": "other-source"},
            "wrong_benchmark": {"benchmark_sha256": "other-benchmark"},
            "duplicate_hit": {"ranked_chunk_ids": ("c1", "c1")},
            "unknown_hit": {"ranked_chunk_ids": ("unknown",)},
            "mixed_kind": {"execution_kind": "real_retrieval"},
        }[kind]
        provided[0] = provided[0].model_copy(update=update)
    with pytest.raises(ValueError):
        benchmark.score_receipts(rows, tuple(provided), chunks(), source_digest="SYNTHETIC", k=5)


def test_policy_only_question_has_no_invented_retrieval_score():
    data = case_data()
    data.update(expected_outcome="out_of_scope", evidence_groups=[])
    data["required_parts"][0].update(outcome="out_of_scope", evidence_group_ids=[])
    rows = (benchmark.BenchmarkCase.model_validate(data),)
    result = benchmark.score_receipts(
        rows, receipts(rows, ()), chunks(), source_digest="SYNTHETIC", k=5
    )
    assert result["cases"][0]["metrics"]["answer_support"]["witness_group_recall"] is None


@pytest.mark.parametrize("tamper", ["manifest", "file_content", "extra_file", "missing_file"])
def test_frozen_inventory_detects_manifest_and_payload_tampering(tmp_path, monkeypatch, tamper):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))
    path = Path(__file__).parents[2] / "scripts/check_frozen_benchmark.py"
    spec = importlib.util.spec_from_file_location("frozen_benchmark_checker", path)
    assert spec and spec.loader
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    payload = tmp_path / "cases.jsonl"
    payload.write_text("SYNTHETIC contract payload\n", encoding="utf-8")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": {"cases.jsonl": digest}}), encoding="utf-8")
    pinned = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert checker.verify_inventory(tmp_path, pinned)
    if tamper == "manifest":
        manifest.write_text("{}", encoding="utf-8")
    elif tamper == "file_content":
        payload.write_text("UNREVIEWED changed question\n", encoding="utf-8")
    elif tamper == "extra_file":
        (tmp_path / "unreviewed.json").write_text("{}", encoding="utf-8")
    else:
        payload.unlink()
    with pytest.raises(ValueError, match="hash_mismatch|inventory_changed"):
        checker.verify_inventory(tmp_path, pinned)
