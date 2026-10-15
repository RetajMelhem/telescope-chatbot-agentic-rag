"""Synthetic comparison boundaries; no frozen queries, secrets or real network access."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def comparison(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))
    from scripts import compare_retrieval

    return compare_retrieval


def test_request_export_rejects_gold_and_duplicate_identity(comparison, tmp_path):
    path = tmp_path / "requests.jsonl"
    request = {"case_id": "synthetic-en", "query": "What hours?", "language": "en", "history": []}
    path.write_text(json.dumps({**request, "expected_outcome": "supported"}), encoding="utf-8")
    with pytest.raises(ValueError):
        comparison.load_requests(path)
    path.write_text(json.dumps(request) + "\n" + json.dumps(request), encoding="utf-8")
    with pytest.raises(ValueError, match="inventory_invalid"):
        comparison.load_requests(path)


def test_paired_modes_use_same_single_query_and_preserve_exact_occurrences(comparison):
    from telescope_rag.retrieval.lexical import BM25Index

    calls, records = [], []
    request = comparison.BenchmarkRequest(
        case_id="synthetic-ar-JO",
        language="ar-JO",
        query="بدي الطبيب",
        history=[{"role": "assistant", "content": "Do not treat history as evidence"}],
    )

    class Reader:
        async def search(self, vector, *, limit):
            calls.append((vector, limit))
            return (
                SimpleNamespace(chunk=SimpleNamespace(chunk_id="owner-b"), score=0.8),
                SimpleNamespace(chunk=SimpleNamespace(chunk_id="owner-a"), score=0.8),
            )

    async def scenario():
        ranking, _, payloads = await comparison.rank_requests(
            [request],
            {request.case_id: (1.0,)},
            Reader(),
            BM25Index({"owner-a": "الطبيب", "owner-b": "الطبيب", "owner-c": "علاج"}),
            record=lambda index, row: records.append((index, row)),
        )
        assert calls == [((1.0,), 20)]
        assert ranking["dense"][0]["ranked_chunk_ids"] == ["owner-a", "owner-b"]
        assert ranking["hybrid"][0]["ranked_chunk_ids"] == ["owner-a", "owner-b"]
        assert payloads == {"owner-a", "owner-b"}
        assert len(records) == 1 and set(records[0][1]["rankings"]) == {"dense", "bm25", "hybrid"}

    asyncio.run(scenario())


def test_later_failure_preserves_completed_case_and_does_not_retry(comparison):
    from telescope_rag.retrieval.lexical import BM25Index

    calls, saved = [], []
    requests = [
        comparison.BenchmarkRequest(case_id=str(i), language="en", query="word", history=[])
        for i in (1, 2)
    ]

    class Reader:
        async def search(self, vector, *, limit):
            calls.append(vector)
            if len(calls) == 2:
                raise ValueError("synthetic_transport_failure")
            return (SimpleNamespace(chunk=SimpleNamespace(chunk_id="one"), score=0.5),)

    async def scenario():
        with pytest.raises(ValueError, match="synthetic_transport_failure"):
            await comparison.rank_requests(
                requests,
                {"1": (1.0,), "2": (2.0,)},
                Reader(),
                BM25Index({"one": "word"}),
                record=lambda index, row: saved.append(row),
            )
        assert calls == [(1.0,), (2.0,)]
        assert len(saved) == 1 and saved[0]["case_id"] == "1"

    asyncio.run(scenario())


def test_null_role_not_success_or_failure_and_history_excluded_only_from_selection(comparison):
    scored = {
        "cases": [
            {
                "case_id": "single-en",
                "language": "en",
                "metrics": {
                    "answer_support": {"witness_group_recall": 0.5},
                    "uncertainty_or_clarification": {"witness_group_recall": None},
                },
            },
            {
                "case_id": "history-en",
                "language": "en",
                "metrics": {
                    "answer_support": {"witness_group_recall": 1.0},
                    "uncertainty_or_clarification": {"witness_group_recall": None},
                },
            },
        ]
    }
    result = comparison.aggregate(
        scored,
        {"single-en": "development", "history-en": "development"},
        {"single-en"},
    )
    assert result["all/development/en"]["answer_support"]["macro_recall"] == 0.75
    assert result["eligible/development/en"]["answer_support"]["macro_recall"] == 0.5
    assert result["all/development/en"]["uncertainty_or_clarification"] == {
        "cases": 0,
        "macro_recall": None,
    }


def candidate_metrics(value):
    return {
        f"eligible/{split}/{language}": {
            role: {"macro_recall": value}
            for role in ("answer_support", "uncertainty_or_clarification")
        }
        for split in ("development", "evaluation")
        for language in ("all", "en", "ar", "ar-JO")
    }


@pytest.mark.parametrize("regression", ["language", "context", "evaluation", "null", "tie"])
def test_aggregate_gain_cannot_hide_regression_or_missing_role(comparison, regression):
    dense, hybrid = candidate_metrics(0.5), candidate_metrics(0.6)
    if regression == "language":
        hybrid["eligible/development/ar"]["answer_support"]["macro_recall"] = 0.4
    elif regression == "context":
        hybrid["eligible/development/en"]["uncertainty_or_clarification"]["macro_recall"] = 0.4
    elif regression == "evaluation":
        hybrid["eligible/evaluation/all"]["answer_support"]["macro_recall"] = 0.4
    elif regression == "null":
        hybrid["eligible/development/ar-JO"]["answer_support"]["macro_recall"] = None
    else:
        hybrid = deepcopy(dense)
    decision = comparison.select_mode(dense, hybrid)
    assert decision["result"] == "inconclusive_dense_baseline_retained"
    assert decision["requires_manual_source_review_before_adoption"]
    assert not decision["production_ready"]


def test_clear_preliminary_gain_still_requires_semantic_adjudication(comparison):
    decision = comparison.select_mode(candidate_metrics(0.5), candidate_metrics(0.6))
    assert decision["result"] == "preliminary_hybrid_candidate"
    assert decision["requires_manual_source_review_before_adoption"]


@pytest.mark.parametrize(
    "marker",
    ["result.json", "failure.json", "provider-metadata-before.json", "query-batch-0001.json"],
)
def test_started_run_cannot_silently_repeat_paid_dispatch(comparison, tmp_path, marker):
    assert not comparison.already_started(tmp_path)
    (tmp_path / marker).write_text("{}", encoding="utf-8")
    assert comparison.already_started(tmp_path)


@pytest.mark.parametrize("mismatch", ["prepared", "configuration", "collection", "candidate"])
def test_different_approved_copy_cannot_use_frozen_benchmark_label(
    comparison, monkeypatch, tmp_path, mismatch
):
    directory = tmp_path / "artifacts/m3-candidate-execution-v6-v1"
    directory.mkdir(parents=True)
    (directory / "plan.json").write_text(
        json.dumps(
            {
                "collection_digest": "raw-expected",
                "configuration_hash": "config-expected",
                "candidate": comparison.CANDIDATE,
            }
        ),
        encoding="utf-8",
    )
    frozen = {
        "prepared_digest": "prepared-expected",
        "benchmark_sha256": comparison.BENCHMARK_HASH,
    }
    bundle = SimpleNamespace(
        documents=(),
        audit=SimpleNamespace(
            prepared_digest="prepared-expected", collection_digest="raw-expected"
        ),
        configuration=object(),
    )
    monkeypatch.setattr(comparison, "verify", lambda *args: frozen)
    monkeypatch.setattr(comparison, "load_reviewed_bundle", lambda *args: bundle)
    monkeypatch.setattr(
        comparison,
        "prepared_digest",
        lambda _: "other" if mismatch == "prepared" else "prepared-expected",
    )
    monkeypatch.setattr(
        comparison,
        "configuration_hash",
        lambda _: "other" if mismatch == "configuration" else "config-expected",
    )
    if mismatch == "collection":
        bundle.audit.collection_digest = "other"
    if mismatch == "candidate":
        monkeypatch.setattr(comparison, "CANDIDATE", "other")
    with pytest.raises(ValueError, match="execution_copy_binding_mismatch"):
        comparison.prepare(tmp_path)
