"""Offline scoring of installed HTTP observations, without invented internal traces."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

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
                "source_groups": [{"group_id": "group", "alternatives": [{"chunk_id": "c1"}]}],
            }
        ],
    }


def source():
    return {
        "c1": {
            "retrieval_text": "Published clinic fact.",
            "original_text": "Published clinic fact.",
            "canonical_url": "https://example.test/clinic",
            "document_id": "doc",
            "parent_block_id": "block",
            "page_title": "Clinic",
            "section_path": ["Contact"],
            "language": "en",
            "snapshot_id": "snapshot",
            "fetched_at": "2026-10-01T10:00:00Z",
            "doctor_id": None,
            "doctor_name": None,
            "canonical_doctor_id": None,
            "canonical_doctor_name": None,
            "source_issue_codes": [],
        }
    }


def request():
    return {"case_id": "U01-ar-JO", "query": "اعطيني رقمكم", "language": "ar-JO", "history": []}


def observation(row=None):
    row = row or request()
    return {
        "case_id": row["case_id"],
        "language": row["language"],
        "request_payload": runner.api_payload(row),
        "http_status": 200,
        "elapsed_seconds": 1.25,
        "error": None,
        "trace": {
            "schema_version": "natural-evaluation-http-observation-v1",
            "case_id": row["case_id"],
            "internal_trace_available": False,
            "cost": None,
        },
        "response": {
            "schema_version": "local-mvp-response-v1",
            "request_id": str(uuid4()),
            "status": "draft_ready",
            "answer": "Published clinic fact.",
            "language": "ar" if row["language"] == "ar-JO" else "en",
            "questions": [
                {
                    "id": "p1",
                    "question": row["query"],
                    "status": "candidate",
                    "answer": "Published clinic fact.",
                    "citation_ids": ["C1"],
                    "reason_code": None,
                    "admitted_scope_complete": True,
                    "hours": None,
                }
            ],
            "citations": [
                {
                    "id": "C1",
                    "question_id": "p1",
                    "chunk_id": "c1",
                    "document_id": "doc",
                    "parent_block_id": "block",
                    "url": "https://example.test/clinic",
                    "title": "Clinic",
                    "section": ["Contact"],
                    "source_language": "en",
                    "fetched_at": "2026-10-01T13:00:00+03:00",
                    "snapshot_id": "snapshot",
                    "literal_owner_id": None,
                    "literal_owner_name": None,
                    "canonical_owner_id": None,
                    "canonical_owner_name": None,
                    "source_issue_codes": [],
                    "quote": "Published clinic fact.",
                }
            ],
            "unresolved_questions": [],
            "knowledge": {
                "prepared_digest": "prepared",
                "snapshot_id": "snapshot",
                "fetched_at": "2026-10-01T10:00:00Z",
            },
        },
    }


def review(missing=False):
    return {
        "reviewer": "Offline fixture reviewer",
        "required_facts": {} if missing else {"fact": True},
        "claim_inventory_complete": True,
        "claims": []
        if missing
        else [
            {
                "text": "Published clinic fact.",
                "correct": True,
                "supported_by_cited_sources": True,
            }
        ],
        "all_parts_accounted_for": True,
        "language_correct": True,
        "no_prohibited_claims": True,
        "citations_semantically_correct": True,
        "missing_information_handled": True if missing else None,
    }


def bind(record, row=None):
    scoring.bind_record(
        record,
        row or request(),
        "prepared",
        execution_kind="installed_portable_http",
        snapshot_id="snapshot",
    )


def test_http_binding_accepts_real_api_payload_and_no_fabricated_workflow():
    record = observation()
    bind(record)
    assert "workflow_runs" not in record["trace"]
    record["request_payload"]["language"] = "ar-JO"
    with pytest.raises(ValueError, match="captured_request_differs_from_question"):
        bind(record)


@pytest.mark.parametrize(
    "field,value",
    [
        ("case_id", "U02-en"),
        ("schema_version", "another-schema"),
        ("internal_trace_available", 0),
        ("cost", {"reported_usd": 0}),
        ("workflow_runs", []),
    ],
)
def test_http_trace_rejects_swapped_or_invented_internals(field, value):
    record = observation()
    record["trace"][field] = value
    with pytest.raises(ValueError, match="http_observation_identity_or_schema_mismatch"):
        bind(record)


@pytest.mark.parametrize(
    "field,value",
    [
        ("prepared_digest", "other-knowledge"),
        ("snapshot_id", "other-snapshot"),
    ],
)
def test_http_response_cannot_claim_another_gold_source(field, value):
    record = observation()
    record["response"]["knowledge"][field] = value
    with pytest.raises(ValueError, match="response_knowledge_source_mismatch"):
        bind(record)


def test_http_success_must_be_the_local_api_schema_and_uuid():
    record = observation()
    record["response"]["schema_version"] = "unknown"
    with pytest.raises(ValueError):
        bind(record)
    record = observation()
    record["response"]["request_id"] = "not-a-uuid"
    with pytest.raises(ValueError):
        bind(record)
    record = observation()
    record["response"]["citations"][0]["snapshot_id"] = "different"
    with pytest.raises(ValueError, match="response_citation_snapshot_mismatch"):
        bind(record)


def test_http_citations_measure_only_cited_witness_coverage_and_source_support():
    result = scoring.case_metrics(
        observation(), intent(), review(), source(), context_available=False
    )
    for key in (
        "candidate_recall5_per_search_part",
        "candidate_recall10_per_search_part",
        "dense_coverage_at_actual_limits",
        "dense_query_limits",
        "writer_eligible_coverage",
        "candidate_judged_precision5",
        "candidate_judged_precision10",
        "cost",
    ):
        assert result[key] is None
    assert result["writer_observed"] is None
    assert result["cited_witness_coverage"]["coverage"] == 1
    assert "recall" not in result["cited_witness_coverage"]
    assert all(value is None for value in result["reported_usage"].values())
    assert result["human"]["faithfulness"] is None
    assert result["human"]["source_support_precision"] == 1
    assert result["human"]["complete_question_success"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("literal_owner_name", "Invented doctor"),
        ("parent_block_id", "other-block"),
        ("section", ["Other section"]),
        ("source_language", "ar"),
        ("fetched_at", "2026-10-02T10:00:00Z"),
        ("quote", "Unpublished statement"),
        ("url", "https://other.test/"),
    ],
)
def test_invalid_citation_cannot_supply_coverage_or_success(field, value):
    record = observation()
    record["response"]["citations"][0][field] = value
    result = scoring.case_metrics(record, intent(), review(), source(), context_available=False)
    assert result["structural_citations_valid"] is False
    assert result["cited_witness_coverage"] is None
    assert result["human"]["complete_question_success"] is False


def test_unreferenced_citation_does_not_count_as_a_cited_answer_witness():
    record = observation()
    record["response"]["questions"][0]["citation_ids"] = []
    result = scoring.case_metrics(record, intent(), None, source(), context_available=False)
    assert result["structural_citations_valid"] is True
    assert result["cited_witness_coverage"]["coverage"] == 0


def test_source_support_cannot_be_substituted_with_unobservable_context_judgment():
    judged = review()
    judged["claims"][0]["supported_by_context"] = True
    del judged["claims"][0]["supported_by_cited_sources"]
    result = scoring.human_metrics(judged, intent(), http_ok=True, context_available=False)
    assert result["review_complete"] is False
    judged = review()
    judged["claims"][0]["supported_by_cited_sources"] = False
    result = scoring.human_metrics(judged, intent(), http_ok=True, context_available=False)
    assert result["review_complete"] is True
    assert result["source_support_precision"] == 0
    assert result["complete_question_success"] is False


def test_price_abstention_has_no_positive_retrieval_or_citation_group_denominator():
    result = scoring.human_metrics(
        review(True), intent(True), http_ok=True, context_available=False
    )
    assert result["complete_question_success"] is True
    assert result["fact_recall"] is None and result["faithfulness"] is None
    assert result["source_support_precision"] is None
    record = observation()
    record["response"]["citations"] = []
    record["response"]["questions"][0]["citation_ids"] = []
    result = scoring.case_metrics(
        record, intent(True), review(True), source(), context_available=False
    )
    assert result["cited_witness_coverage"]["coverage"] is None


def setup_score_run(tmp_path, monkeypatch, *, duplicate_request_id=False, failed=False):
    plan_dir, run_dir = tmp_path / "plan", tmp_path / "run"
    plan_dir.mkdir()
    run_dir.mkdir()
    approved = Path(__file__).parents[2] / runner.REQUESTS
    (plan_dir / "requests.jsonl").write_bytes(approved.read_bytes())
    plan = {
        "requests_sha256": runner.digest(approved),
        "prepared_digest": "prepared",
        "source_root": str(tmp_path),
        "release_manifest_sha256": "manifest",
        "transport": "installed_portable_http",
    }
    runner.write_new(plan_dir / "plan.json", plan)
    intents = [dict(intent(), intent_id=f"U{i:02}") for i in range(1, 25)] + [intent(True)]
    runner.write_new(plan_dir / "gold.json", {"intents": intents})
    rows = runner.requests_from(plan_dir / "requests.jsonl")[:2]
    records = [observation(row) for row in rows]
    if duplicate_request_id:
        records[1]["response"]["request_id"] = records[0]["response"]["request_id"]
    if failed:
        records = records[:1]
        records[0].update(http_status=502, response={"code": "provider_error"})
    for record in records:
        runner.write_new(run_dir / f"{record['case_id']}.json", record)
    runner.write_new(
        run_dir / "execution-index.json",
        {
            "requested_cases": 2,
            "attempted_cases": len(records),
            "case_files": [f"{record['case_id']}.json" for record in records],
            "not_attempted_case_ids": [row["case_id"] for row in rows[len(records) :]],
        },
    )
    runner.write_run_binding(plan_dir, run_dir, tmp_path, plan, "installed_portable_http")
    binding_path = run_dir / "run-binding.json"
    binding = json.loads(binding_path.read_bytes())
    receipt_names = ("preflight-before.json", "http-preflight.json", "preflight-after.json")
    for name in receipt_names:
        if name == "http-preflight.json":
            receipt = {
                "status": "verified",
                "readiness_http_status": 200,
                "openapi_http_status": 200,
                "runtime_unchanged_before_first_question": True,
            }
        else:
            receipt = {
                "status": "verified",
                "version": "v0.1.0",
                "knowledge_id": "knowledge",
                "prepared_digest": "prepared",
                "release_manifest_sha256": "manifest",
                "internal_trace_available": False,
            }
        runner.write_new(run_dir / name, receipt)
    binding["installed_receipts_sha256"] = {
        name: runner.digest(run_dir / name) for name in receipt_names
    }
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    monkeypatch.setattr(scoring, "verify_plan", lambda *args: plan)
    monkeypatch.setattr(
        scoring,
        "load_source",
        lambda *args: ({"version": "v0.1.0", "knowledge_id": "knowledge"}, source()),
    )
    return plan_dir, run_dir


def test_http_score_template_and_summary_preserve_observation_limits(tmp_path, monkeypatch):
    plan_dir, run_dir = setup_score_run(tmp_path, monkeypatch)
    output = tmp_path / "score"
    scoring.score_run(tmp_path, plan_dir, run_dir, output, None)
    template = json.loads((output / "human-review-template.json").read_bytes())
    assert template["internal_context_available"] is False
    assert "supported_by_cited_sources" in template["instruction"]
    assert "cannot be judged" in template["instruction"]
    summary = json.loads((output / "summary.json").read_bytes())
    assert summary["overall"]["cited_witness_coverage"]["macro"] == 1
    assert summary["overall"]["writer_eligible_coverage"]["eligible_scored_cases"] == 0
    assert summary["overall"]["cost_reported_usd"] is None
    assert all(
        value is None
        for value in summary["overall"]["reported_usage_totals_attempted_only"].values()
    )
    reviewed = deepcopy(template)
    for row in reviewed["cases"]:
        row.update(review())
    review_path = tmp_path / "review.json"
    runner.write_new(review_path, reviewed)
    scoring.score_run(tmp_path, plan_dir, run_dir, tmp_path / "reviewed", review_path)
    summary = json.loads((tmp_path / "reviewed/summary.json").read_bytes())
    assert summary["overall"]["complete_question_success_rate"] == 1
    assert summary["overall"]["faithfulness_macro_reviewed_only"] is None
    assert summary["overall"]["source_support_precision_macro_reviewed_only"] == 1


def test_http_score_rejects_reused_request_identity_across_languages(tmp_path, monkeypatch):
    plan_dir, run_dir = setup_score_run(tmp_path, monkeypatch, duplicate_request_id=True)
    with pytest.raises(ValueError, match="response_request_id_reused_in_cohort"):
        scoring.score_run(tmp_path, plan_dir, run_dir, tmp_path / "score", None)


def test_http_score_requires_unchanged_installed_preflight_receipts(tmp_path, monkeypatch):
    plan_dir, run_dir = setup_score_run(tmp_path, monkeypatch)
    (run_dir / "preflight-after.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="installed_preflight_receipt_binding_mismatch"):
        scoring.score_run(tmp_path, plan_dir, run_dir, tmp_path / "score", None)


def test_http_error_and_stopped_case_stay_in_denominator_with_unknown_usage(tmp_path, monkeypatch):
    plan_dir, run_dir = setup_score_run(tmp_path, monkeypatch, failed=True)
    output = tmp_path / "score"
    scoring.score_run(tmp_path, plan_dir, run_dir, output, None)
    summary = json.loads((output / "summary.json").read_bytes())["overall"]
    assert summary["requested_cases"] == 2 and summary["attempted_cases"] == 1
    assert summary["complete_question_success_rate"] == 0
    assert summary["http_success_rate"] == 0
    assert summary["cited_witness_coverage"]["eligible_scored_cases"] == 0
    assert summary["cost_reported_usd"] is None


def test_http_200_with_validation_error_still_fails_without_discarding_record():
    record = observation()
    record["error"] = "response_schema_invalid"
    record["response"] = {"schema_version": "unexpected"}
    bind(record)
    result = scoring.case_metrics(record, intent(), review(), source(), context_available=False)
    assert result["execution"] == "attempted"
    assert result["http_ok"] is False
    assert result["human"]["complete_question_success"] is False
    assert result["cited_witness_coverage"] is None
    assert scoring.aggregate([result])["complete_question_success_rate"] == 0


@pytest.mark.parametrize("mutation", ["changed_runtime", "failed_preflight", "wrong_knowledge"])
def test_rehashed_preflight_cannot_hide_runtime_or_gold_mismatch(tmp_path, monkeypatch, mutation):
    plan_dir, run_dir = setup_score_run(tmp_path, monkeypatch)
    if mutation == "changed_runtime":
        names = ["preflight-after.json"]
        field, value = "api_started_at", "different"
    elif mutation == "failed_preflight":
        names = ["http-preflight.json"]
        field, value = "status", "failed"
    else:
        names = ["preflight-before.json", "preflight-after.json"]
        field, value = "prepared_digest", "other"
    binding_path = run_dir / "run-binding.json"
    binding = json.loads(binding_path.read_bytes())
    for name in names:
        path = run_dir / name
        receipt = json.loads(path.read_bytes())
        receipt[field] = value
        path.write_text(json.dumps(receipt), encoding="utf-8")
        binding["installed_receipts_sha256"][name] = runner.digest(path)
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(ValueError, match="installed_preflight_"):
        scoring.score_run(tmp_path, plan_dir, run_dir, tmp_path / "score", None)
