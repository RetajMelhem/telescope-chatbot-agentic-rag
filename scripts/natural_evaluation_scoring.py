"""Offline witness scoring and explicitly human-authored answer judgments.

Unlisted evidence is unjudged, not irrelevant. Null judgments never become passes.
No model, retrieval, database or billing requests are issued by this module.
"""

import json
import statistics
from pathlib import Path
from uuid import UUID

from scripts.natural_evaluation import (
    digest,
    load_source,
    percentile95,
    requests_from,
    review_template,
    verify_plan,
    write_new,
)


def witness_recall(ids: set[str], intent: dict) -> dict:
    groups = [g for f in intent["required_facts"] for g in f["source_groups"]]
    hits = [g["group_id"] for g in groups if ids & {a["chunk_id"] for a in g["alternatives"]}]
    return {
        "expected_groups": len(groups),
        "hit_groups": hits,
        "recall": len(hits) / len(groups) if groups else None,
        "all_groups_found": len(hits) == len(groups) if groups else None,
    }


def observed_evidence(trace: dict) -> dict:
    batches = [c["batch"] for c in trace.get("retrieval_calls", []) if "batch" in c]
    parts = [p for b in batches for p in b["parts"]]
    writer_ids = {
        identity
        for context in trace.get("writer_contexts", [])
        for part in context["body"].get("parts", [])
        for identity in part.get("eligible_quote_chunk_ids", [])
    }
    dense = [c for c in trace.get("dense_calls", []) if "hits" in c]
    return {
        "parts": parts,
        "candidate5": {identity for p in parts for identity in p["chunk_ids"][:5]},
        "candidate10": {identity for p in parts for identity in p["chunk_ids"][:10]},
        "writer": writer_ids,
        "dense": {h["chunk_id"] for call in dense for h in call["hits"]},
        "dense_limits": [c["requested_limit"] for c in dense],
        "search_observed": bool(parts),
        "writer_observed": bool(trace.get("writer_contexts")),
    }


def structural_citations(response: dict | None, chunks: dict) -> bool | None:
    """Literal identity/quote checks only; this cannot establish entailment."""
    if response is None:
        return None
    citations = response.get("citations", [])
    seen = set()
    questions = {q["id"]: q for q in response.get("questions", [])}
    if len(questions) != len(response.get("questions", [])):
        return False
    for citation in citations:
        source = chunks.get(citation.get("chunk_id"))
        quote = citation.get("quote")
        if (
            source is None
            or citation.get("id") in seen
            or not isinstance(quote, str)
            or not quote
            or (quote not in source["retrieval_text"] and quote not in source["original_text"])
            or citation.get("url") != source["canonical_url"]
            or citation.get("document_id") != source["document_id"]
            or citation.get("literal_owner_id") != source["doctor_id"]
            or citation.get("canonical_owner_id") != source["canonical_doctor_id"]
            or citation.get("question_id") not in questions
        ):
            return False
        seen.add(citation["id"])
    by_id = {c["id"]: c for c in citations}
    return all(
        identity in by_id and by_id[identity]["question_id"] == question["id"]
        for question in questions.values()
        for identity in question.get("citation_ids", [])
    )


def human_metrics(review: dict | None, intent: dict, *, http_ok: bool) -> dict:
    expected = {f["fact_id"] for f in intent["required_facts"]}
    missing = intent["answerability"] == "missing_exact_amount"
    required_flags = [
        "all_parts_accounted_for",
        "language_correct",
        "no_prohibited_claims",
        "citations_semantically_correct",
    ]
    complete = bool(
        review
        and isinstance(review.get("reviewer"), str)
        and review["reviewer"].strip()
        and review.get("claim_inventory_complete") is True
    )
    if complete:
        facts = review.get("required_facts", {})
        complete = set(facts) == expected and all(type(v) is bool for v in facts.values())
        complete = complete and all(type(review.get(k)) is bool for k in required_flags)
        complete = complete and (
            not missing or type(review.get("missing_information_handled")) is bool
        )
        complete = complete and all(
            isinstance(c.get("text"), str)
            and c["text"].strip()
            and type(c.get("correct")) is bool
            and type(c.get("supported_by_context")) is bool
            for c in review.get("claims", [])
        )
        complete = complete and (not any(facts.values()) or bool(review.get("claims")))
    if not complete:
        return {
            "review_complete": False,
            "fact_recall": None,
            "claim_precision": None,
            "faithfulness": None,
            "missing_information_handled": None,
            "complete_question_success": False if not http_ok else None,
        }
    facts, claims = review["required_facts"], review["claims"]
    fact_recall = sum(facts.values()) / len(facts) if facts else None
    correct = all(c["correct"] and c["supported_by_context"] for c in claims)
    success = http_ok and all(facts.values()) and correct
    success = success and all(review[k] for k in required_flags)
    success = success and (not missing or review["missing_information_handled"])
    return {
        "review_complete": True,
        "fact_recall": fact_recall,
        "claim_precision": sum(c["correct"] for c in claims) / len(claims) if claims else None,
        "faithfulness": (
            sum(c["supported_by_context"] for c in claims) / len(claims) if claims else None
        ),
        "missing_information_handled": review["missing_information_handled"] if missing else None,
        "complete_question_success": bool(success),
    }


def judged_precision(ids: set[str], review: dict | None) -> float | None:
    labels = review.get("candidate_relevance", {}) if review else {}
    if not ids or any(type(labels.get(identity)) is not bool for identity in ids):
        return None
    return sum(labels[i] for i in ids) / len(ids)


def average(values: list) -> float | None:
    known = [v for v in values if v is not None]
    return statistics.mean(known) if known else None


def reported_usage(trace: dict) -> dict:
    runs = trace.get("workflow_runs", [])
    result = {}
    for kind, fields in (
        ("chat", ("input_tokens", "output_tokens")),
        ("embedding", ("input_tokens",)),
    ):
        receipts = [r for run in runs for r in run["usage"]["receipts"] if r["kind"] == kind]
        attempts = sum(run["usage"][f"physical_{kind}_attempts"] for run in runs)
        result[f"physical_{kind}_attempts"] = attempts if runs else None
        for field in fields:
            values = [receipt["usage"].get(field) for receipt in receipts]
            result[f"reported_{kind}_{field}"] = (
                sum(values)
                if runs and len(values) == attempts and all(v is not None for v in values)
                else None
            )
    return result


def case_metrics(record: dict | None, intent: dict, review: dict | None, chunks: dict) -> dict:
    if record is None:
        return {
            "execution": "not_attempted_after_stop",
            "http_ok": False,
            "human": human_metrics(None, intent, http_ok=False),
        }
    trace = record.get("trace", {})
    if trace.get("capture_errors") or trace.get("concurrent_run_detected"):
        raise ValueError("trace_incomplete_or_concurrent")
    evidence = observed_evidence(trace)
    if (evidence["candidate10"] | evidence["writer"] | evidence["dense"]) - chunks.keys():
        raise ValueError("trace_unknown_source_occurrence")
    result = {
        "execution": "attempted",
        "http_ok": record["http_status"] == 200,
        "http_status": record["http_status"],
        "elapsed_seconds": record["elapsed_seconds"],
        "candidate_recall5_per_search_part": (
            witness_recall(evidence["candidate5"], intent) if evidence["search_observed"] else None
        ),
        "candidate_recall10_per_search_part": (
            witness_recall(evidence["candidate10"], intent) if evidence["search_observed"] else None
        ),
        "dense_coverage_at_actual_limits": (
            witness_recall(evidence["dense"], intent) if evidence["dense_limits"] else None
        ),
        "dense_query_limits": evidence["dense_limits"],
        "writer_eligible_coverage": witness_recall(evidence["writer"], intent),
        "writer_observed": evidence["writer_observed"],
        "candidate_judged_precision5": judged_precision(evidence["candidate5"], review),
        "candidate_judged_precision10": judged_precision(evidence["candidate10"], review),
        "structural_citations_valid": structural_citations(record.get("response"), chunks),
        "cost": trace.get("cost"),
        "reported_usage": reported_usage(trace),
        "human": human_metrics(review, intent, http_ok=record["http_status"] == 200),
    }
    if result["structural_citations_valid"] is False:
        result["human"]["complete_question_success"] = False
    return result


def bind_record(record: dict, request: dict, prepared_digest: str) -> None:
    if record.get("case_id") != request["case_id"] or record.get("language") != request["language"]:
        raise ValueError("case_record_identity_mismatch")
    trace = record.get("trace", {})
    runs = trace.get("workflow_runs", [])
    if (
        trace.get("case_id") != request["case_id"]
        or trace.get("active_workflows") != 0
        or len(runs) > 1
        or (record["http_status"] == 200 and len(runs) != 1)
    ):
        raise ValueError("case_trace_identity_or_inventory_mismatch")
    response = record.get("response")
    for run in runs:
        observed = run.get("request")
        expected = {
            "query": request["query"],
            "language": "ar" if request["language"] == "ar-JO" else "en",
            "history": request["history"],
        }
        if observed != expected:
            raise ValueError("captured_request_differs_from_question")
        evidence = run.get("evidence")
        if evidence and evidence["prepared_digest"] != prepared_digest:
            raise ValueError("captured_evidence_source_mismatch")
        if record["http_status"] == 200:
            from telescope_rag.api.local import LocalChatResponse

            LocalChatResponse.model_validate_json(json.dumps(response))
            if UUID(response["request_id"]).hex != UUID(run["result"]["request_id"]).hex:
                raise ValueError("response_workflow_identity_mismatch")
    for call in trace.get("retrieval_calls", []):
        if call.get("batch", {}).get("prepared_digest", prepared_digest) != prepared_digest:
            raise ValueError("captured_retrieval_source_mismatch")
    if response and response.get("knowledge"):
        if response["knowledge"]["prepared_digest"] != prepared_digest:
            raise ValueError("response_knowledge_source_mismatch")


def aggregate(rows: list[dict]) -> dict:
    timed = [r["elapsed_seconds"] for r in rows if "elapsed_seconds" in r]
    reviewed = [r for r in rows if r["human"]["review_complete"]]
    determined = [r for r in rows if r["human"]["complete_question_success"] is not None]
    output = {
        "requested_cases": len(rows),
        "attempted_cases": len(timed),
        "http_success_rate": sum(r["http_ok"] for r in rows) / len(rows),
        "not_attempted_cases": len(rows) - len(timed),
        "human_reviewed_cases": len(reviewed),
        "median_http_seconds": statistics.median(timed) if timed else None,
        "p95_http_seconds": percentile95(timed),
        "complete_question_success_rate": (
            sum(r["human"]["complete_question_success"] for r in rows) / len(rows)
            if len(determined) == len(rows)
            else None
        ),
        "complete_question_success_rate_upper_bound": (
            sum(r["human"]["complete_question_success"] is not False for r in rows) / len(rows)
        ),
        "fact_recall_macro_reviewed_only": average([r["human"]["fact_recall"] for r in reviewed]),
        "claim_precision_macro_reviewed_only": average(
            [r["human"]["claim_precision"] for r in reviewed]
        ),
        "faithfulness_macro_reviewed_only": average([r["human"]["faithfulness"] for r in reviewed]),
        "missing_information_handling_reviewed_only": average(
            [r["human"]["missing_information_handled"] for r in reviewed]
        ),
    }
    for name in (
        "candidate_recall5_per_search_part",
        "candidate_recall10_per_search_part",
        "dense_coverage_at_actual_limits",
        "writer_eligible_coverage",
    ):
        values = [r.get(name, {}).get("recall") if r.get(name) else None for r in rows]
        output[name] = {
            "macro": average(values),
            "eligible_scored_cases": sum(v is not None for v in values),
        }
    output["cost_reported_usd"] = (
        sum(r["cost"]["reported_usd"] for r in rows)
        if all(r.get("cost") and r["cost"].get("complete") for r in rows)
        else None
    )
    attempted_rows = [r for r in rows if "reported_usage" in r]
    output["reported_usage_totals_attempted_only"] = {}
    for key in (
        "physical_chat_attempts",
        "physical_embedding_attempts",
        "reported_chat_input_tokens",
        "reported_chat_output_tokens",
        "reported_embedding_input_tokens",
    ):
        values = [r["reported_usage"][key] for r in attempted_rows]
        output["reported_usage_totals_attempted_only"][key] = (
            sum(values) if values and all(v is not None for v in values) else None
        )
    return output


def score_run(root: Path, plan_dir: Path, run_dir: Path, output: Path, review_path: Path | None):
    plan = verify_plan(root, plan_dir)
    binding = json.loads((run_dir / "run-binding.json").read_bytes())
    if binding["execution_kind"] not in {"live_local_mvp", "synthetic_contract_test"}:
        raise ValueError("execution_kind_unknown")
    if (
        binding["plan_sha256"] != digest(plan_dir / "plan.json")
        or binding["requests_sha256"] != plan["requests_sha256"]
        or binding["prepared_digest"] != plan["prepared_digest"]
        or binding["index_sha256"] != digest(run_dir / "execution-index.json")
    ):
        raise ValueError("run_plan_binding_mismatch")
    requests = requests_from(plan_dir / "requests.jsonl")
    gold = json.loads((plan_dir / "gold.json").read_bytes())
    intents = {i["intent_id"]: i for i in gold["intents"]}
    _, chunks = load_source(Path(plan["source_root"]))
    index = json.loads((run_dir / "execution-index.json").read_bytes())
    count = index["requested_cases"]
    if type(count) is not int or not 1 <= count <= 50:
        raise ValueError("invalid_run_cohort_count")
    cohort = requests[:count]
    attempted = index["attempted_cases"]
    if type(attempted) is not int or not 0 <= attempted <= count:
        raise ValueError("invalid_attempted_count")
    filenames = [f"{r['case_id']}.json" for r in cohort[:attempted]]
    actual_files = {p.name for p in run_dir.glob("U*.json")}
    if (
        index["case_files"] != filenames
        or set(binding["case_sha256"]) != set(filenames)
        or actual_files != set(filenames)
        or index["not_attempted_case_ids"] != [r["case_id"] for r in cohort[attempted:]]
    ):
        raise ValueError("execution_case_inventory_changed")
    records = {}
    for request, filename in zip(cohort[:attempted], filenames, strict=True):
        path = run_dir / filename
        if digest(path) != binding["case_sha256"][filename]:
            raise ValueError("execution_case_hash_changed")
        record = json.loads(path.read_bytes())
        bind_record(record, request, plan["prepared_digest"])
        records[request["case_id"]] = record
    expected = review_template(cohort, list(intents.values()))
    for row in expected["cases"]:
        record = records.get(row["case_id"])
        row["case_file_sha256"] = digest(run_dir / f"{row['case_id']}.json") if record else None
        if record:
            row["candidate_relevance"] = {
                identity: None
                for identity in sorted(observed_evidence(record["trace"])["candidate10"])
            }
    reviews = {}
    if review_path:
        actual = json.loads(review_path.read_bytes())
        reviews = {r["case_id"]: r for r in actual["cases"]}
        if len(reviews) != len(actual["cases"]) or reviews.keys() != {r["case_id"] for r in cohort}:
            raise ValueError("human_review_case_inventory_changed")
        for row in expected["cases"]:
            if reviews[row["case_id"]].get("case_file_sha256") != row["case_file_sha256"]:
                raise ValueError("human_review_not_bound_to_case")
    scored = []
    for request in cohort:
        case_id = request["case_id"]
        metrics = case_metrics(
            records.get(case_id), intents[case_id.split("-")[0]], reviews.get(case_id), chunks
        )
        scored.append({"case_id": case_id, "language": request["language"], **metrics})
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "human-review-template.json", expected)
    write_new(output / "case-scores.json", scored)
    write_new(
        output / "summary.json",
        {
            "execution_kind": binding["execution_kind"],
            "plan_sha256": binding["plan_sha256"],
            "overall": aggregate(scored),
            "by_language": {
                language: aggregate([r for r in scored if r["language"] == language])
                for language in {r["language"] for r in scored}
            },
            "limitations": [
                "Known positive witness groups, not exhaustive relevance or semantic recall.",
                "Candidate recall is a union of top-k per planned search part, "
                "not one global ranking.",
                "Dense call/part association is unavailable; dense coverage is request-level only.",
                "Writer coverage uses actual offered eligible IDs; "
                "provenance-only duplicates do not count.",
                "Search recall excludes source-read/hours-only paths; "
                "scored denominators are explicit.",
                "Human precision requires relevance labels for every observed candidate; "
                "unjudged is null.",
                "Structural citation validity does not prove semantic entailment.",
                "Arabic/English pairs share intents and are not independent statistical samples.",
                "HTTP latency is in-process ASGI application time, "
                "not deployed network or load performance.",
            ],
        },
    )
