"""Offline witness scoring and explicitly human-authored answer judgments.

Unlisted evidence is unjudged, not irrelevant. Null judgments never become passes.
No model, retrieval, database or billing requests are issued by this module.
"""

import json
import statistics
from datetime import datetime
from pathlib import Path
from uuid import UUID

from scripts.natural_evaluation import (
    api_payload,
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


def structural_citations(
    response: dict | None, chunks: dict, *, full_source_identity: bool = False
) -> bool | None:
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
        if full_source_identity:
            fields = {
                "parent_block_id": "parent_block_id",
                "title": "page_title",
                "section": "section_path",
                "source_language": "language",
                "snapshot_id": "snapshot_id",
                "literal_owner_name": "doctor_name",
                "canonical_owner_name": "canonical_doctor_name",
                "source_issue_codes": "source_issue_codes",
            }
            if any(citation.get(wire) != source.get(saved) for wire, saved in fields.items()):
                return False
            if datetime.fromisoformat(citation["fetched_at"]) != datetime.fromisoformat(
                source["fetched_at"]
            ):
                return False
        seen.add(citation["id"])
    by_id = {c["id"]: c for c in citations}
    return all(
        identity in by_id and by_id[identity]["question_id"] == question["id"]
        for question in questions.values()
        for identity in question.get("citation_ids", [])
    )


def human_metrics(
    review: dict | None, intent: dict, *, http_ok: bool, context_available: bool = True
) -> dict:
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
    support_field = "supported_by_context" if context_available else "supported_by_cited_sources"
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
            and type(c.get(support_field)) is bool
            for c in review.get("claims", [])
        )
        complete = complete and (not any(facts.values()) or bool(review.get("claims")))
    if not complete:
        return {
            "review_complete": False,
            "fact_recall": None,
            "claim_precision": None,
            "faithfulness": None,
            "source_support_precision": None,
            "missing_information_handled": None,
            "complete_question_success": False if not http_ok else None,
        }
    facts, claims = review["required_facts"], review["claims"]
    fact_recall = sum(facts.values()) / len(facts) if facts else None
    correct = all(c["correct"] and c[support_field] for c in claims)
    success = http_ok and all(facts.values()) and correct
    success = success and all(review[k] for k in required_flags)
    success = success and (not missing or review["missing_information_handled"])
    return {
        "review_complete": True,
        "fact_recall": fact_recall,
        "claim_precision": sum(c["correct"] for c in claims) / len(claims) if claims else None,
        "faithfulness": (
            sum(c["supported_by_context"] for c in claims) / len(claims)
            if context_available and claims
            else None
        ),
        "source_support_precision": (
            sum(c["supported_by_cited_sources"] for c in claims) / len(claims)
            if not context_available and claims
            else None
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


def case_metrics(
    record: dict | None,
    intent: dict,
    review: dict | None,
    chunks: dict,
    *,
    context_available: bool = True,
) -> dict:
    if record is None:
        return {
            "execution": "not_attempted_after_stop",
            "http_ok": False,
            "human": human_metrics(
                None, intent, http_ok=False, context_available=context_available
            ),
        }
    trace = record.get("trace", {})
    if trace.get("capture_errors") or trace.get("concurrent_run_detected"):
        raise ValueError("trace_incomplete_or_concurrent")
    if not context_available:
        http_ok = record["http_status"] == 200 and record.get("error") is None
        citation_validity = structural_citations(
            record.get("response") if http_ok else None,
            chunks,
            full_source_identity=True,
        )
        referenced = (
            {
                identity
                for question in (record.get("response") or {}).get("questions", [])
                for identity in question.get("citation_ids", [])
            }
            if http_ok
            else set()
        )
        cited = (
            {c["chunk_id"] for c in record["response"]["citations"] if c["id"] in referenced}
            if citation_validity is True
            else set()
        )
        coverage = witness_recall(cited, intent) if citation_validity is True else None
        if coverage is not None:
            coverage["coverage"] = coverage.pop("recall")
        human = human_metrics(review, intent, http_ok=http_ok, context_available=False)
        if citation_validity is False:
            human["complete_question_success"] = False
        return {
            "execution": "attempted",
            "http_ok": http_ok,
            "http_status": record["http_status"],
            "elapsed_seconds": record["elapsed_seconds"],
            "internal_context_available": False,
            "candidate_recall5_per_search_part": None,
            "candidate_recall10_per_search_part": None,
            "dense_coverage_at_actual_limits": None,
            "dense_query_limits": None,
            "writer_eligible_coverage": None,
            "writer_observed": None,
            "candidate_judged_precision5": None,
            "candidate_judged_precision10": None,
            "cited_witness_coverage": coverage,
            "structural_citations_valid": citation_validity,
            "cost": None,
            "reported_usage": reported_usage({}),
            "human": human,
        }
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


def bind_record(
    record: dict,
    request: dict,
    prepared_digest: str,
    *,
    execution_kind: str = "live_local_mvp",
    snapshot_id: str | None = None,
) -> None:
    if record.get("case_id") != request["case_id"] or record.get("language") != request["language"]:
        raise ValueError("case_record_identity_mismatch")
    trace = record.get("trace", {})
    if execution_kind == "installed_portable_http":
        if trace.get("internal_trace_available") is not False or trace != {
            "schema_version": "natural-evaluation-http-observation-v1",
            "case_id": request["case_id"],
            "internal_trace_available": False,
            "cost": None,
        }:
            raise ValueError("http_observation_identity_or_schema_mismatch")
        if record.get("request_payload") != api_payload(request):
            raise ValueError("captured_request_differs_from_question")
        if record["http_status"] == 200 and record.get("error") is None:
            from telescope_rag.api.local import LocalChatResponse

            response = record.get("response")
            LocalChatResponse.model_validate_json(json.dumps(response))
            UUID(response["request_id"])
            knowledge = response.get("knowledge")
            if knowledge and (
                knowledge["prepared_digest"] != prepared_digest
                or snapshot_id is None
                or knowledge["snapshot_id"] != snapshot_id
            ):
                raise ValueError("response_knowledge_source_mismatch")
            if any(c["snapshot_id"] != snapshot_id for c in response["citations"]):
                raise ValueError("response_citation_snapshot_mismatch")
        return
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
        "source_support_precision_macro_reviewed_only": average(
            [r["human"].get("source_support_precision") for r in reviewed]
        ),
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
    cited = [r.get("cited_witness_coverage") for r in rows]
    values = [v["coverage"] if v else None for v in cited]
    output["cited_witness_coverage"] = {
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
    if binding["execution_kind"] not in {
        "live_local_mvp",
        "synthetic_contract_test",
        "installed_portable_http",
    }:
        raise ValueError("execution_kind_unknown")
    context_available = binding["execution_kind"] != "installed_portable_http"
    if (
        binding["plan_sha256"] != digest(plan_dir / "plan.json")
        or binding["requests_sha256"] != plan["requests_sha256"]
        or binding["prepared_digest"] != plan["prepared_digest"]
        or binding["index_sha256"] != digest(run_dir / "execution-index.json")
    ):
        raise ValueError("run_plan_binding_mismatch")
    if not context_available:
        expected_receipts = {"preflight-before.json", "http-preflight.json", "preflight-after.json"}
        receipt_hashes = binding.get("installed_receipts_sha256", {})
        if set(receipt_hashes) != expected_receipts or any(
            not (run_dir / name).is_file() or digest(run_dir / name) != receipt_hashes[name]
            for name in expected_receipts
        ):
            raise ValueError("installed_preflight_receipt_binding_mismatch")
        installed_before = json.loads((run_dir / "preflight-before.json").read_bytes())
        installed_after = json.loads((run_dir / "preflight-after.json").read_bytes())
        http_preflight = json.loads((run_dir / "http-preflight.json").read_bytes())
        if (
            installed_before != installed_after
            or installed_before.get("status") != "verified"
            or installed_before.get("internal_trace_available") is not False
            or http_preflight.get("status") != "verified"
            or http_preflight.get("readiness_http_status") != 200
            or http_preflight.get("openapi_http_status") != 200
            or http_preflight.get("runtime_unchanged_before_first_question") is not True
        ):
            raise ValueError("installed_preflight_not_verified_or_runtime_changed")
    requests = requests_from(plan_dir / "requests.jsonl")
    gold = json.loads((plan_dir / "gold.json").read_bytes())
    intents = {i["intent_id"]: i for i in gold["intents"]}
    source_manifest, chunks = load_source(Path(plan["source_root"]))
    if not context_available and (
        installed_before.get("version") != source_manifest.get("version")
        or installed_before.get("knowledge_id") != source_manifest.get("knowledge_id")
        or installed_before.get("prepared_digest") != plan["prepared_digest"]
        or installed_before.get("release_manifest_sha256") != plan["release_manifest_sha256"]
    ):
        raise ValueError("installed_preflight_gold_source_mismatch")
    snapshot_ids = {c["snapshot_id"] for c in chunks.values()} if not context_available else set()
    if not context_available and len(snapshot_ids) != 1:
        raise ValueError("gold_snapshot_inventory_invalid")
    snapshot_id = next(iter(snapshot_ids)) if snapshot_ids else None
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
    response_ids = set()
    for request, filename in zip(cohort[:attempted], filenames, strict=True):
        path = run_dir / filename
        if digest(path) != binding["case_sha256"][filename]:
            raise ValueError("execution_case_hash_changed")
        record = json.loads(path.read_bytes())
        bind_record(
            record,
            request,
            plan["prepared_digest"],
            execution_kind=binding["execution_kind"],
            snapshot_id=snapshot_id,
        )
        if not context_available and record["http_status"] == 200 and record.get("error") is None:
            response_id = UUID(record["response"]["request_id"]).hex
            if response_id in response_ids:
                raise ValueError("response_request_id_reused_in_cohort")
            response_ids.add(response_id)
        records[request["case_id"]] = record
    expected = review_template(cohort, list(intents.values()))
    if not context_available:
        expected["internal_context_available"] = False
        expected["instruction"] = (
            "Human source review only; null means unreviewed, never pass. "
            "For each factual claim provide text, correct and supported_by_cited_sources booleans. "
            "Judge the exact cited public sources; actual model context is unavailable, "
            "so supported_by_context and faithfulness cannot be judged. "
            "Cited witness coverage does not measure retrieval recall."
        )
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
        if not context_available and actual.get("internal_context_available") is not False:
            raise ValueError("human_review_context_availability_mismatch")
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
            records.get(case_id),
            intents[case_id.split("-")[0]],
            reviews.get(case_id),
            chunks,
            context_available=context_available,
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
            "limitations": (
                [
                    "Installed portable HTTP observes responses only; internal retrieval, "
                    "writer context, provider usage and cost remain unavailable (null).",
                    "Cited witness coverage counts source groups in validated citations; "
                    "it does not measure retrieval recall or exhaustive semantic coverage.",
                    "Source support judgments use cited public sources. Faithfulness to the actual "
                    "model context is unavailable, even when complete question success is judged.",
                    "Structural citation validity does not prove semantic entailment.",
                    "Arabic/English pairs share intents; they are not independent samples.",
                    "HTTP latency includes loopback networking and API processing; "
                    "this serial cohort is not a load test.",
                ]
                if not context_available
                else [
                    "Known positive witness groups, not exhaustive relevance or semantic recall.",
                    "Candidate recall is a union of top-k per planned search part, "
                    "not one global ranking.",
                    "Dense call/part association is unavailable; "
                    "dense coverage is request-level only.",
                    "Writer coverage uses actual offered eligible IDs; "
                    "provenance-only duplicates do not count.",
                    "Search recall excludes source-read/hours-only paths; "
                    "scored denominators are explicit.",
                    "Human precision requires relevance labels for every observed candidate; "
                    "unjudged is null.",
                    "Structural citation validity does not prove semantic entailment.",
                    "Arabic/English pairs share intents; they are not independent samples.",
                    "HTTP latency is in-process ASGI application time, "
                    "not deployed network or load performance.",
                ]
            ),
        },
    )
