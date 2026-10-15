"""Offline benchmark validation and scoring of supplied retrieval receipts only.

This module makes no requests, loads no credentials, and cannot embed or index.
Semantic correctness is an authored/reviewed fixture property, never inferred here.
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telescope_rag.ingestion.models import PreparedChunk, PreparedDocument
from telescope_rag.ingestion.review import prepared_digest

Language = Literal["en", "ar", "ar-JO"]
Outcome = Literal["supported", "partial", "unsupported", "clarification", "out_of_scope"]
PartOutcome = Literal["supported", "unsupported", "clarification", "out_of_scope"]
EvidenceRole = Literal["answer_support", "uncertainty_context", "clarification_context"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class HistoryMessage(Record):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class Quote(Record):
    chunk_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class EvidenceGroup(Record):
    group_id: str = Field(min_length=1)
    role: EvidenceRole
    chunk_ids: tuple[str, ...] = Field(min_length=1)
    source_reason: str = Field(min_length=1)
    quotes: tuple[Quote, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def explicit_quote_for_every_alternative(self):
        if len(set(self.chunk_ids)) != len(self.chunk_ids):
            raise ValueError("duplicate_evidence_alternative")
        if {q.chunk_id for q in self.quotes} != set(self.chunk_ids):
            raise ValueError("every_alternative_needs_quote")
        return self


class RequestPart(Record):
    part_id: str = Field(min_length=1)
    request: str = Field(min_length=1)
    outcome: PartOutcome
    required_claims: tuple[str, ...] = Field(min_length=1)
    prohibited_claims: tuple[str, ...]
    evidence_group_ids: tuple[str, ...]


class BenchmarkCase(Record):
    case_id: str = Field(min_length=1)
    intent_id: str = Field(min_length=1)
    language: Language
    query: str = Field(min_length=1)
    history: tuple[HistoryMessage, ...]
    tags: tuple[str, ...] = Field(min_length=1)
    expected_outcome: Outcome
    required_parts: tuple[RequestPart, ...] = Field(min_length=1)
    evidence_groups: tuple[EvidenceGroup, ...]
    prohibited_actions: tuple[str, ...] = Field(min_length=1)
    policy_references: tuple[str, ...] = Field(min_length=1)
    semantic_rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def complete_request_and_evidence_accounting(self):
        if self.case_id != f"{self.intent_id}-{self.language}":
            raise ValueError("case_identity_language_mismatch")
        groups = {g.group_id: g for g in self.evidence_groups}
        if len(groups) != len(self.evidence_groups):
            raise ValueError("duplicate_evidence_group")
        parts = {p.part_id for p in self.required_parts}
        if len(parts) != len(self.required_parts):
            raise ValueError("duplicate_request_part")
        used = {i for p in self.required_parts for i in p.evidence_group_ids}
        if used != groups.keys():
            raise ValueError("missing_or_orphan_evidence_group")
        support_used = set()
        for part in self.required_parts:
            if len(set(part.evidence_group_ids)) != len(part.evidence_group_ids):
                raise ValueError("duplicate_part_group")
            support = {i for i in part.evidence_group_ids if groups[i].role == "answer_support"}
            if part.outcome == "supported":
                if not support:
                    raise ValueError("supported_part_requires_answer_evidence")
                support_used.update(support)
            elif support:
                raise ValueError("unknown_or_excluded_part_cannot_claim_answer_support")
        if support_used != {g.group_id for g in self.evidence_groups if g.role == "answer_support"}:
            raise ValueError("unused_answer_support")
        outcomes = {p.outcome for p in self.required_parts}
        expected = next(iter(outcomes)) if len(outcomes) == 1 else "partial"
        if self.expected_outcome != expected:
            raise ValueError("overall_outcome_drops_or_overstates_request_parts")
        return self


class SemanticReview(Record):
    case_id: str
    case_sha256: str
    reviewer_agent: str
    model: Literal["gpt-6.1-sol"]
    verdict: Literal["pass", "repair_required"]
    rationale: str = Field(min_length=1)
    reviewed_chunk_ids: tuple[str, ...]
    findings: tuple[str, ...]
    request_language_preserved: bool


class RetrievalReceipt(Record):
    """A supplied ranked list; the scorer never creates it or calls retrieval."""

    case_id: str
    prepared_digest: str
    benchmark_sha256: str
    execution_kind: Literal["real_retrieval", "synthetic_contract_test"]
    ranked_chunk_ids: tuple[str, ...]


def canonical_bytes(value: dict | list) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def case_hash(case: BenchmarkCase) -> str:
    return hashlib.sha256(canonical_bytes(case.model_dump(mode="json"))).hexdigest()


def benchmark_hash(cases: tuple[BenchmarkCase, ...]) -> str:
    rows = [c.model_dump(mode="json") for c in sorted(cases, key=lambda c: c.case_id)]
    return hashlib.sha256(canonical_bytes(rows)).hexdigest()


def load_cases(path: Path) -> tuple[BenchmarkCase, ...]:
    if path.suffix == ".jsonl":
        return tuple(
            BenchmarkCase.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return tuple(BenchmarkCase.model_validate(v) for v in json.loads(path.read_bytes()))


def load_corpus(bundle: Path) -> tuple[tuple[PreparedDocument, ...], dict[str, PreparedChunk]]:
    documents = tuple(
        PreparedDocument.model_validate_json(p.read_bytes())
        for p in sorted(bundle.glob("*.json"))
        if len(p.stem) == 64
    )
    if not documents:
        raise ValueError("empty_source_bundle")
    chunks = [c for d in documents for c in d.chunks]
    by_id = {c.chunk_id: c for c in chunks}
    if len(by_id) != len(chunks):
        raise ValueError("duplicate_source_chunk_id")
    return documents, by_id


def validate_cases(
    cases: tuple[BenchmarkCase, ...],
    chunks: dict[str, PreparedChunk],
    *,
    expected_intents: int | None = None,
) -> dict:
    """Validate authored anchors; this does not judge language/semantic support."""
    if not cases or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("empty_or_duplicate_case_inventory")
    intents = defaultdict(list)
    references = set()
    for case in cases:
        intents[case.intent_id].append(case)
        for group in case.evidence_groups:
            for chunk_id in group.chunk_ids:
                if chunk_id not in chunks:
                    raise ValueError("unknown_source_chunk")
                url = urlsplit(chunks[chunk_id].canonical_url)
                if url.scheme != "https" or url.hostname not in {
                    "telescopecenter.com",
                    "www.telescopecenter.com",
                }:
                    raise ValueError("non_official_evidence_source")
                references.add(chunk_id)
            if any(q.quote not in chunks[q.chunk_id].retrieval_text for q in group.quotes):
                raise ValueError("quotation_not_in_exact_chunk")
    if expected_intents is not None and len(intents) != expected_intents:
        raise ValueError("intent_coverage_mismatch")
    for variants in intents.values():
        if Counter(v.language for v in variants) != Counter({"en": 1, "ar": 1, "ar-JO": 1}):
            raise ValueError("missing_or_duplicate_language_variant")
        shapes = {
            (v.expected_outcome, tuple((p.part_id, p.outcome) for p in v.required_parts))
            for v in variants
        }
        if len(shapes) != 1:
            raise ValueError("language_variant_request_structure_drift")
    return {
        "cases": len(cases),
        "intents": len(intents),
        "languages": dict(Counter(c.language for c in cases)),
        "outcomes": dict(Counter(c.expected_outcome for c in cases)),
        "distinct_witness_chunks": len(references),
        "benchmark_sha256": benchmark_hash(cases),
        "semantic_acceptance_established_by_validator": False,
    }


def validate_reviews(
    cases: tuple[BenchmarkCase, ...],
    reviews: tuple[SemanticReview, ...],
    authors: dict[str, str],
) -> None:
    by_id = {r.case_id: r for r in reviews}
    if len(by_id) != len(reviews) or by_id.keys() != {c.case_id for c in cases}:
        raise ValueError("semantic_review_coverage_incomplete_or_duplicate")
    for case in cases:
        review = by_id[case.case_id]
        if review.case_sha256 != case_hash(case):
            raise ValueError("stale_semantic_review")
        if review.reviewer_agent == authors[case.intent_id]:
            raise ValueError("independent_review_cannot_be_self_review")
        refs = {i for g in case.evidence_groups for i in g.chunk_ids}
        if set(review.reviewed_chunk_ids) != refs:
            raise ValueError("semantic_review_source_coverage_mismatch")
        if review.verdict != "pass" or not review.request_language_preserved or review.findings:
            raise ValueError("unresolved_semantic_review_findings")


def score_receipts(
    cases: tuple[BenchmarkCase, ...],
    receipts: tuple[RetrievalReceipt, ...],
    chunks: dict[str, PreparedChunk],
    *,
    source_digest: str,
    k: int,
) -> dict:
    """Strict witness-group recall only, not answer correctness or overall readiness.

    All supplied cases must have one receipt. OR alternatives occur inside a
    group; all groups are AND requirements. Policy-only cases get null recall.
    """
    if k < 1:
        raise ValueError("invalid_top_k")
    by_id = {r.case_id: r for r in receipts}
    if len(by_id) != len(receipts) or by_id.keys() != {c.case_id for c in cases}:
        raise ValueError("retrieval_receipt_coverage_incomplete_or_duplicate")
    expected_hash = benchmark_hash(cases)
    rows = []
    kinds = {r.execution_kind for r in receipts}
    if len(kinds) != 1:
        raise ValueError("synthetic_and_real_receipts_cannot_be_mixed")
    for case in cases:
        receipt = by_id[case.case_id]
        if receipt.prepared_digest != source_digest or receipt.benchmark_sha256 != expected_hash:
            raise ValueError("retrieval_receipt_binding_mismatch")
        if len(set(receipt.ranked_chunk_ids)) != len(receipt.ranked_chunk_ids):
            raise ValueError("duplicate_ranked_occurrence")
        if set(receipt.ranked_chunk_ids) - chunks.keys():
            raise ValueError("unknown_retrieved_chunk")
        top = set(receipt.ranked_chunk_ids[:k])
        metrics = {}
        for label, roles in {
            "answer_support": {"answer_support"},
            "uncertainty_or_clarification": {"uncertainty_context", "clarification_context"},
        }.items():
            groups = [g for g in case.evidence_groups if g.role in roles]
            hits = [g.group_id for g in groups if top.intersection(g.chunk_ids)]
            metrics[label] = {
                "hit_groups": hits,
                "expected_groups": len(groups),
                "witness_group_recall": len(hits) / len(groups) if groups else None,
                "all_witness_groups_found": len(hits) == len(groups) if groups else None,
            }
        rows.append(
            {
                "case_id": case.case_id,
                "language": case.language,
                "expected_outcome": case.expected_outcome,
                "metrics": metrics,
                "answer_semantics_assessed": False,
            }
        )
    return {
        "execution_kind": next(iter(kinds)),
        "prepared_digest": source_digest,
        "benchmark_sha256": expected_hash,
        "top_k": k,
        "cases": rows,
        "limits": "Known witness recall only; alternative correct evidence needs manual review. "
        "No claim of exhaustive relevance, answer correctness, faithfulness or readiness.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--expected-intents", type=int, default=30)
    args = parser.parse_args()
    documents, chunks = load_corpus(args.bundle)
    if prepared_digest(documents) != args.expected_digest:
        raise ValueError("sealed_source_digest_mismatch")
    result = validate_cases(load_cases(args.cases), chunks, expected_intents=args.expected_intents)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
