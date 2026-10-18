"""Meaningful runner, evidence and review boundaries; synthetic and offline only."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from scripts import natural_evaluation as runner
from scripts import natural_evaluation_scoring as scoring


def intent(missing=False):
    return {
        "intent_id": "U25" if missing else "U01",
        "answerability": "missing_exact_amount" if missing else "supported",
        "required_facts": []
        if missing
        else [
            {
                "fact_id": "fact",
                "source_groups": [
                    {"group_id": "group", "alternatives": [{"chunk_id": "c1"}, {"chunk_id": "alt"}]}
                ],
            }
        ],
    }


def completed_review(missing=False):
    return {
        "reviewer": "Synthetic reviewer",
        "required_facts": {} if missing else {"fact": True},
        "claim_inventory_complete": True,
        "claims": []
        if missing
        else [{"text": "Synthetic fact", "correct": True, "supported_by_context": True}],
        "all_parts_accounted_for": True,
        "language_correct": True,
        "no_prohibited_claims": True,
        "citations_semantically_correct": True,
        "missing_information_handled": True if missing else None,
    }


def test_approved_requests_are_exact_and_dialect_is_only_api_mapped():
    rows = runner.requests_from(Path(__file__).parents[2] / runner.REQUESTS)
    arabic = next(r for r in rows if r["language"] == "ar-JO")
    before = deepcopy(arabic)
    payload = runner.api_payload(arabic)
    assert payload == {"query": arabic["query"], "language": "ar", "history": []}
    assert arabic == before
    assert "case_id" not in payload and "gold" not in payload


def test_question_byte_change_is_rejected_before_any_runtime_exists(tmp_path):
    path = tmp_path / "requests.jsonl"
    path.write_text('{"query":"changed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="approved_question_bytes_changed"):
        runner.requests_from(path)


def test_group_or_alternatives_do_not_make_different_groups_optional():
    gold = intent()
    gold["required_facts"][0]["source_groups"].append(
        {"group_id": "second", "alternatives": [{"chunk_id": "c2"}]}
    )
    assert scoring.witness_recall({"alt"}, gold)["recall"] == 0.5
    assert scoring.witness_recall({"alt", "c2"}, gold)["all_groups_found"] is True
    assert scoring.witness_recall({"wrong-owner"}, gold)["recall"] == 0


def test_price_context_never_becomes_positive_amount_recall():
    assert scoring.witness_recall({"estimate-context"}, intent(True))["recall"] is None
    gold = intent(True)
    gold["optional_context_groups"] = [{"alternatives": [{"chunk_id": "estimate-context"}]}]
    assert scoring.witness_recall({"estimate-context"}, gold)["expected_groups"] == 0


def test_assembled_provenance_does_not_count_as_writer_exposure():
    trace = {
        "retrieval_calls": [{"batch": {"parts": [{"chunk_ids": ["c1"]}]}}],
        "workflow_runs": [{"evidence": {"groups": [{"occurrences": ["c1"]}]}}],
        "writer_contexts": [{"body": {"parts": [{"eligible_quote_chunk_ids": ["other"]}]}}],
        "dense_calls": [{"requested_limit": 5, "hits": [{"chunk_id": "c1"}]}],
    }
    seen = scoring.observed_evidence(trace)
    assert scoring.witness_recall(seen["candidate5"], intent())["recall"] == 1
    assert scoring.witness_recall(seen["writer"], intent())["recall"] == 0
    assert seen["dense_limits"] == [5]


def test_source_read_and_hours_context_do_not_invent_search_execution():
    seen = scoring.observed_evidence(
        {"writer_contexts": [{"body": {"parts": [{"eligible_quote_chunk_ids": ["c1"]}]}}]}
    )
    assert seen["search_observed"] is False and seen["dense_limits"] == []
    assert scoring.witness_recall(seen["writer"], intent())["recall"] == 1


def test_unjudged_candidate_is_not_irrelevant_or_a_zero_precision():
    assert (
        scoring.judged_precision({"c1", "new-source"}, {"candidate_relevance": {"c1": True}})
        is None
    )
    assert (
        scoring.judged_precision(
            {"c1", "new-source"}, {"candidate_relevance": {"c1": True, "new-source": False}}
        )
        == 0.5
    )


@pytest.mark.parametrize("bad", [None, {}, {"claim_inventory_complete": True}])
def test_absent_answer_review_never_becomes_success(bad):
    row = scoring.human_metrics(bad, intent(), http_ok=True)
    assert row["review_complete"] is False and row["complete_question_success"] is None


@pytest.mark.parametrize("mutation", ["truthy_string", "empty_claims", "numeric_reviewer"])
def test_incomplete_or_malformed_human_inventory_is_not_a_pass(mutation):
    review = completed_review()
    if mutation == "truthy_string":
        review["claim_inventory_complete"] = "false"
    elif mutation == "empty_claims":
        review["claims"] = []
    else:
        review["reviewer"] = 123
    assert scoring.human_metrics(review, intent(), http_ok=True)["review_complete"] is False


def test_false_fact_or_unfaithful_claim_fails_complete_question():
    review = completed_review()
    assert scoring.human_metrics(review, intent(), http_ok=True)["complete_question_success"]
    review["claims"][0]["supported_by_context"] = False
    assert (
        scoring.human_metrics(review, intent(), http_ok=True)["complete_question_success"] is False
    )
    assert (
        scoring.human_metrics(completed_review(True), intent(True), http_ok=True)[
            "complete_question_success"
        ]
        is True
    )


def test_reviewed_abstention_on_answerable_question_is_a_scored_failure():
    review = completed_review()
    review["required_facts"] = {"fact": False}
    review["claims"] = []
    result = scoring.human_metrics(review, intent(), http_ok=True)
    assert result["review_complete"] is True
    assert result["fact_recall"] == 0
    assert result["claim_precision"] is None and result["faithfulness"] is None
    assert result["complete_question_success"] is False


def test_failed_and_not_attempted_cases_remain_in_cohort_denominator():
    rows = [
        {
            "http_ok": True,
            "elapsed_seconds": 1,
            "human": scoring.human_metrics(completed_review(), intent(), http_ok=True),
        },
        {
            "http_ok": False,
            "elapsed_seconds": 2,
            "human": scoring.human_metrics(None, intent(), http_ok=False),
        },
        scoring.case_metrics(None, intent(), None, {}),
    ]
    summary = scoring.aggregate(rows)
    assert summary["requested_cases"] == 3 and summary["attempted_cases"] == 2
    assert summary["complete_question_success_rate"] == 1 / 3
    assert summary["http_success_rate"] == 1 / 3 and summary["cost_reported_usd"] is None


def test_citation_from_another_question_cannot_be_borrowed():
    chunks = {
        "c1": {
            "retrieval_text": "Synthetic fact",
            "original_text": "Synthetic fact",
            "canonical_url": "https://example.test/a",
            "document_id": "doc",
            "doctor_id": "owner",
            "canonical_doctor_id": None,
        }
    }
    response = {
        "questions": [{"id": "p1", "citation_ids": ["cite"]}, {"id": "p2", "citation_ids": []}],
        "citations": [
            {
                "id": "cite",
                "question_id": "p1",
                "chunk_id": "c1",
                "quote": "Synthetic fact",
                "url": "https://example.test/a",
                "document_id": "doc",
                "literal_owner_id": "owner",
                "canonical_owner_id": None,
            }
        ],
    }
    assert scoring.structural_citations(response, chunks) is True
    response["questions"][1]["citation_ids"] = ["cite"]
    assert scoring.structural_citations(response, chunks) is False
    response["questions"][1] = response["questions"][0]
    assert scoring.structural_citations(response, chunks) is False


def test_swapped_or_active_case_capture_is_rejected():
    request = {"case_id": "U01-en", "language": "en", "query": "Question?", "history": []}
    record = {"case_id": "U02-en", "language": "en", "http_status": 502, "trace": {}}
    with pytest.raises(ValueError, match="case_record_identity_mismatch"):
        scoring.bind_record(record, request, "digest")
    record["case_id"] = "U01-en"
    record["trace"] = {"case_id": "U01-en", "active_workflows": 1}
    with pytest.raises(ValueError, match="case_trace_identity"):
        scoring.bind_record(record, request, "digest")


def test_missing_usage_never_becomes_reserved_tokens_or_zero_cost():
    usage = {
        "physical_chat_attempts": 1,
        "physical_embedding_attempts": 0,
        "charged_chat_input": 12000,
        "charged_output": 4096,
        "receipts": [{"kind": "chat", "usage": {"input_tokens": None, "output_tokens": None}}],
    }
    result = scoring.reported_usage({"workflow_runs": [{"usage": usage}]})
    assert result["reported_chat_input_tokens"] is None
    assert result["reported_chat_output_tokens"] is None
    assert result["reported_embedding_input_tokens"] == 0
    usage["receipts"][0]["usage"] = {"input_tokens": 0, "output_tokens": 0}
    assert (
        scoring.reported_usage({"workflow_runs": [{"usage": usage}]})["reported_chat_input_tokens"]
        == 0
    )


def test_full_offline_score_preserves_cohort_and_rejects_changed_receipts(tmp_path, monkeypatch):
    plan_dir, run_dir = tmp_path / "plan", tmp_path / "run"
    plan_dir.mkdir()
    run_dir.mkdir()
    source_requests = Path(__file__).parents[2] / runner.REQUESTS
    (plan_dir / "requests.jsonl").write_bytes(source_requests.read_bytes())
    plan = {
        "requests_sha256": runner.digest(source_requests),
        "prepared_digest": "synthetic",
        "source_root": str(tmp_path),
        "transport": "synthetic_contract_test",
    }
    runner.write_new(plan_dir / "plan.json", plan)
    gold = [dict(intent(), intent_id=f"U{i:02}") for i in range(1, 25)] + [intent(True)]
    runner.write_new(plan_dir / "gold.json", {"intents": gold})
    requests = runner.requests_from(plan_dir / "requests.jsonl")
    first = requests[0]
    record = {
        "case_id": first["case_id"],
        "language": first["language"],
        "http_status": 502,
        "elapsed_seconds": 0.1,
        "response": None,
        "trace": {"case_id": first["case_id"], "active_workflows": 0, "workflow_runs": []},
    }
    runner.write_new(run_dir / f"{first['case_id']}.json", record)
    runner.write_new(
        run_dir / "execution-index.json",
        {
            "requested_cases": 2,
            "attempted_cases": 1,
            "case_files": [f"{first['case_id']}.json"],
            "not_attempted_case_ids": [requests[1]["case_id"]],
        },
    )
    runner.write_run_binding(plan_dir, run_dir, tmp_path, plan, "synthetic_contract_test")
    monkeypatch.setattr(scoring, "verify_plan", lambda *args: plan)
    monkeypatch.setattr(scoring, "load_source", lambda *args: ({}, {}))
    output = tmp_path / "score"
    scoring.score_run(tmp_path, plan_dir, run_dir, output, None)
    summary = json.loads((output / "summary.json").read_text("utf-8"))
    assert summary["execution_kind"] == "synthetic_contract_test"
    assert summary["overall"]["requested_cases"] == 2
    assert summary["overall"]["complete_question_success_rate"] == 0
    assert summary["overall"]["fact_recall_macro_reviewed_only"] is None
    case_path = run_dir / f"{first['case_id']}.json"
    original_case = case_path.read_bytes()
    case_path.write_bytes(original_case + b" ")
    with pytest.raises(ValueError, match="execution_case_hash_changed"):
        scoring.score_run(tmp_path, plan_dir, run_dir, tmp_path / "tampered", None)
    case_path.write_bytes(original_case)
    with (run_dir / "execution-index.json").open("a", encoding="utf-8") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="run_plan_binding_mismatch"):
        scoring.score_run(tmp_path, plan_dir, run_dir, tmp_path / "tampered-index", None)


def test_http_runner_sends_once_maps_language_and_stops_after_failure(tmp_path):
    app = FastAPI()
    received = []

    @app.post("/api/v1/chat")
    async def chat(request: Request):
        received.append(await request.json())
        return JSONResponse({"synthetic": True}, status_code=200 if len(received) == 1 else 502)

    class Capture:
        def reset(self, identity):
            self.case_id = identity

        def snapshot(self):
            return {"case_id": self.case_id, "active_workflows": 0}

    requests = [
        {"case_id": "U01-ar-JO", "language": "ar-JO", "query": "رقمكم؟", "history": []},
        {"case_id": "U01-en", "language": "en", "query": "Your number?", "history": []},
        {"case_id": "U02-en", "language": "en", "query": "Where?", "history": []},
    ]
    output = tmp_path / "run"
    rows = asyncio.run(runner.run_cases(app, Capture(), requests, output, limit=3))
    assert len(rows) == len(received) == 2
    assert received[0] == {"query": "رقمكم؟", "language": "ar", "history": []}
    index = json.loads((output / "execution-index.json").read_text("utf-8"))
    assert index["attempted_cases"] == 2 and index["not_attempted_case_ids"] == ["U02-en"]
    assert index["retries"] == 0 and not (output / "U02-en.json").exists()
    with pytest.raises(FileExistsError):
        asyncio.run(runner.run_cases(app, Capture(), requests, output, limit=3))
    assert len(received) == 2
