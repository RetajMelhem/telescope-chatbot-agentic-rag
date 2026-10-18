"""Prepare, execute by explicit opt-in, and review the approved 50-question cohort.

Preparation/scoring never create network clients or read credentials. Live mode
uses the unchanged local factory and actual ASGI HTTP route, serially, once per
case. Gold is never passed to that factory, client, planner or writer.
"""

import argparse
import asyncio
import hashlib
import json
import math
import subprocess
import time
from collections import Counter
from pathlib import Path

REQUESTS = Path("tests/fixtures/evaluation/natural_questions_50_v1/requests.jsonl")
APPROVED_REQUESTS_SHA256 = "ff31dcb5ddfd730e0f97cd8accf2f7b3ebbaabe4444f5185269a34239391db0f"
SOURCE = Path("artifacts/natural-questions-50-source-v1")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def requests_from(path: Path, *, approved: bool = True) -> list[dict]:
    if approved and digest(path) != APPROVED_REQUESTS_SHA256:
        raise ValueError("approved_question_bytes_changed")
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    if len(rows) != 50 or Counter(r["language"] for r in rows) != {"ar-JO": 25, "en": 25}:
        raise ValueError("question_inventory_changed")
    expected = {f"U{i:02}-{language}" for i in range(1, 26) for language in ("ar-JO", "en")}
    if len({r["case_id"] for r in rows}) != 50 or {r["case_id"] for r in rows} != expected:
        raise ValueError("question_ids_changed")
    for row in rows:
        if set(row) != {"case_id", "language", "query", "history"} or row["history"] != []:
            raise ValueError("request_contains_non_request_fields")
    return rows


def api_payload(row: dict) -> dict:
    """The public API supports ar, not ar-JO; retain dialect in the case sidecar."""
    return {
        "query": row["query"],
        "language": "ar" if row["language"] == "ar-JO" else "en",
        "history": row["history"],
    }


def load_source(source: Path) -> tuple[dict, dict]:
    manifest = json.loads((source / "release.json").read_bytes())
    knowledge = source / "knowledge"
    for record in manifest["knowledge"]["files"]:
        path = (knowledge / record["path"]).resolve()
        if not path.is_relative_to(knowledge.resolve()):
            raise ValueError("source_path_outside_knowledge")
        if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
            raise ValueError("source_release_file_changed")
    from telescope_rag.ingestion.models import PreparedDocument
    from telescope_rag.ingestion.review import prepared_digest

    documents = []
    for path in (knowledge / "data/processed/m3-execution-approved-v6-v2").glob("*.json"):
        value = json.loads(path.read_bytes())
        if "chunks" in value:
            documents.append(PreparedDocument.model_validate(value))
    chunks = {c.chunk_id: c.model_dump(mode="json") for d in documents for c in d.chunks}
    if len(documents) != 107 or len(chunks) != 955:
        raise ValueError("source_inventory_changed")
    if prepared_digest(tuple(documents)) != manifest["knowledge"]["prepared_digest"]:
        raise ValueError("source_prepared_digest_changed")
    return manifest, chunks


def validate_gold(intents: list[dict], chunks: dict) -> None:
    if len(intents) != 25 or {i["intent_id"] for i in intents} != {
        f"U{i:02}" for i in range(1, 26)
    }:
        raise ValueError("gold_intent_inventory_invalid")
    fact_ids, group_ids = set(), set()
    for intent in intents:
        missing = intent["intent_id"] == "U25"
        if intent["answerability"] != ("missing_exact_amount" if missing else "supported"):
            raise ValueError("gold_outcome_changed")
        facts = intent["required_facts"]
        if bool(facts) == missing:
            raise ValueError("gold_missing_support_or_invented_price")
        for fact in facts:
            if fact["fact_id"] in fact_ids or not fact["source_groups"]:
                raise ValueError("gold_fact_invalid")
            fact_ids.add(fact["fact_id"])
            if not fact["acceptable_answer_en"] or not fact["acceptable_answer_ar"]:
                raise ValueError("gold_language_answer_missing")
            for group in fact["source_groups"]:
                if group["group_id"] in group_ids or not group["alternatives"]:
                    raise ValueError("gold_group_invalid")
                group_ids.add(group["group_id"])
                ids = [a["chunk_id"] for a in group["alternatives"]]
                if len(set(ids)) != len(ids):
                    raise ValueError("gold_duplicate_alternative")
                for alternative in group["alternatives"]:
                    chunk = chunks.get(alternative["chunk_id"])
                    if (
                        chunk is None
                        or not alternative["quote"]
                        or alternative["quote"] not in chunk["retrieval_text"]
                    ):
                        raise ValueError("gold_quote_not_bound_to_source")


def code_hashes(root: Path) -> dict:
    paths = [*root.joinpath("src").rglob("*.py"), *root.joinpath("src").rglob("*.html")]
    paths += [root / "uv.lock", root / "pyproject.toml"]
    paths += list(root.joinpath("scripts").glob("natural_evaluation*.py"))
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(paths)}


def review_template(requests: list[dict], intents: list[dict]) -> dict:
    by_id = {i["intent_id"]: i for i in intents}
    return {
        "schema_version": "natural-evaluation-human-review-v1",
        "instruction": "Human source review only; null means unreviewed, never pass.",
        "cases": [
            {
                "case_id": r["case_id"],
                "reviewer": None,
                "required_facts": {
                    f["fact_id"]: None for f in by_id[r["case_id"].split("-")[0]]["required_facts"]
                },
                "claim_inventory_complete": False,
                "claims": [],
                "all_parts_accounted_for": None,
                "language_correct": None,
                "no_prohibited_claims": None,
                "citations_semantically_correct": None,
                "missing_information_handled": None,
                "candidate_relevance": {},
                "notes": "",
            }
            for r in requests
        ],
    }


def prepare(root: Path, source: Path, output: Path) -> dict:
    requests = requests_from(root / REQUESTS)
    manifest, chunks = load_source(source)
    parts = [
        json.loads((source / name).read_bytes())
        for name in ("gold-general-authored.json", "gold-services-authored.json")
    ]
    intents = sorted([i for part in parts for i in part["intents"]], key=lambda i: i["intent_id"])
    validate_gold(intents, chunks)
    for part in parts:
        if part["prepared_digest"] != manifest["knowledge"]["prepared_digest"]:
            raise ValueError("authored_gold_source_mismatch")
    reviewed = {}
    for authored_name, review_name in (
        ("gold-general-authored.json", "gold-general-independent-review-final.json"),
        ("gold-services-authored.json", "gold-services-independent-review.json"),
    ):
        review = json.loads((source / review_name).read_bytes())
        if review["verdict"] != "pass" or review["reviewed_input_sha256"] != digest(
            source / authored_name
        ):
            raise ValueError("gold_independent_review_missing_or_stale")
        reviewed[review_name] = digest(source / review_name)
    output.mkdir(parents=True, exist_ok=False)
    (output / "requests.jsonl").write_bytes((root / REQUESTS).read_bytes())
    gold = {
        "schema_version": "natural-evaluation-gold-v1",
        "authored_before_bot_responses": True,
        "prepared_digest": manifest["knowledge"]["prepared_digest"],
        "limitations": "Selected known positive witnesses; not exhaustive relevance labels.",
        "intents": intents,
    }
    write_new(output / "gold.json", gold)
    write_new(output / "human-review-template.json", review_template(requests, intents))
    plan = {
        "schema_version": "natural-evaluation-plan-v1",
        "question_approval": "User approved all 50 questions including both price cases.",
        "live_execution_authorized": False,
        "execution_status": "not_executed",
        "source_root": str(source.resolve()),
        "prepared_digest": manifest["knowledge"]["prepared_digest"],
        "release_manifest_sha256": digest(source / "release.json"),
        "requests_sha256": digest(output / "requests.jsonl"),
        "gold_sha256": digest(output / "gold.json"),
        "independent_gold_review_sha256": reviewed,
        "code_sha256": code_hashes(root),
        "revision_at_preparation": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "transport": "actual local MVP POST /api/v1/chat via in-process ASGI HTTP",
        "latency_scope": "application HTTP latency; excludes deployed network/container queue",
        "limits": {
            "cases": 50,
            "concurrency": 1,
            "attempts_per_case": 1,
            "chat_calls_per_case": 2,
            "embedding_batches_per_case": 1,
            "chat_calls_total_max": 100,
            "embedding_batches_total_max": 50,
            "provider_retries": 0,
            "case_timeout_seconds": 155,
            "application_deadline_seconds": 150,
            "extra_judge_calls": 0,
        },
        "cost": {
            "estimate_usd": None,
            "hard_usd_cap_enforced": False,
            "note": "Call/deadline limits are not a dollar cap. Pricing, allowance and an "
            "appropriate provider-side spend limit must be checked before live authorization.",
        },
        "prerequisites": [
            "An explicitly selected prepared host runtime root with reviewed data/tokenizer.",
            "That project's .env OpenRouter key and .tools/qdrant-m3/read.key.",
            "Existing compatible localhost Qdrant; runner never installs/starts/restores it.",
            "Unchanged plan/request/gold/source/code hashes and explicit live authorization.",
        ],
        "metrics": [
            "Known-witness recall at 5/10 candidates per search part; read-only paths N/A.",
            "Dense known-witness coverage at actual query limits (normally 5), not dense@10.",
            "Writer-eligible witness coverage, distinct from all provenance occurrences.",
            "Human fact recall, claim precision, faithfulness, citation entailment "
            "and full success.",
            "Human missing-information handling for U25; exact-price support recall is null.",
            "Median/p95 application HTTP time; errors/timeouts remain in full cohort denominator.",
        ],
    }
    write_new(output / "plan.json", plan)
    return plan


def verify_plan(root: Path, directory: Path) -> dict:
    plan = json.loads((directory / "plan.json").read_bytes())
    if (
        digest(directory / "requests.jsonl") != plan["requests_sha256"]
        or digest(directory / "gold.json") != plan["gold_sha256"]
        or code_hashes(root) != plan["code_sha256"]
    ):
        raise ValueError("sealed_evaluation_inputs_changed")
    source = Path(plan["source_root"])
    if digest(source / "release.json") != plan["release_manifest_sha256"]:
        raise ValueError("sealed_source_manifest_changed")
    manifest, _ = load_source(source)
    if manifest["knowledge"]["prepared_digest"] != plan["prepared_digest"]:
        raise ValueError("sealed_source_changed")
    return plan


async def run_cases(app, capture, requests: list[dict], output: Path, *, limit: int) -> list[dict]:
    """Caller supplies an explicit app; tests inject fake services, never real providers."""
    import httpx2 as httpx

    if type(limit) is not int or not 1 <= limit <= len(requests):
        raise ValueError("invalid_case_limit")
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False)
    rows = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://127.0.0.1",
        timeout=155,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        for case in requests[:limit]:
            capture.reset(case["case_id"])
            row = {"case_id": case["case_id"], "language": case["language"]}
            start = time.perf_counter()
            try:
                async with asyncio.timeout(155):
                    response = await client.post("/api/v1/chat", json=api_payload(case))
                row.update(http_status=response.status_code, response=response.json(), error=None)
            except Exception as error:
                row.update(http_status=None, response=None, error=type(error).__name__)
            row["elapsed_seconds"] = time.perf_counter() - start
            row["trace"] = capture.snapshot()
            await asyncio.to_thread(write_new, output / f"{case['case_id']}.json", row)
            rows.append(row)
            print(json.dumps({"case_id": case["case_id"], "http_status": row["http_status"]}))
            # Unknown dispatch failure or non-200 stops; no automatic paid repeat.
            if row["http_status"] != 200:
                break
    await asyncio.to_thread(
        write_new,
        output / "execution-index.json",
        {
            "requested_cases": limit,
            "attempted_cases": len(rows),
            "not_attempted_case_ids": [r["case_id"] for r in requests[len(rows) : limit]],
            "case_files": [f"{r['case_id']}.json" for r in rows],
            "retries": 0,
        },
    )
    return rows


def execution_inputs(root: Path, directory: Path, runtime: Path, output: Path) -> tuple:
    plan = verify_plan(root, directory)
    requests = requests_from(directory / "requests.jsonl")
    if output.exists():
        raise ValueError("execution_output_already_exists")
    # Existence checks do not print/read values and happen before any client exists.
    if not (runtime / ".env").is_file() or not (runtime / ".tools/qdrant-m3/read.key").is_file():
        raise ValueError("prepared_runtime_credentials_missing")
    return plan, requests, runtime.resolve()


def write_run_binding(
    directory: Path, output: Path, runtime: Path, plan: dict, execution_kind: str
) -> None:
    write_new(
        output / "run-binding.json",
        {
            "execution_kind": execution_kind,
            "plan_sha256": digest(directory / "plan.json"),
            "requests_sha256": plan["requests_sha256"],
            "prepared_digest": plan["prepared_digest"],
            "transport": plan["transport"],
            "runtime_root": str(runtime),
            "index_sha256": digest(output / "execution-index.json"),
            "case_sha256": {path.name: digest(path) for path in sorted(output.glob("U*.json"))},
        },
    )


async def execute(root: Path, directory: Path, runtime: Path, output: Path, limit: int) -> None:
    plan, requests, runtime = await asyncio.to_thread(
        execution_inputs, root, directory, runtime, output
    )
    from scripts.natural_evaluation_trace import RecordedCostTransport, install_capture
    from telescope_rag.api.local import create_local_app

    cost_transport = RecordedCostTransport()
    app = create_local_app(runtime, provider_transport=cost_transport)
    capture = install_capture(app)
    cost_transport.capture = capture
    settings = app.state.offline_chat_service._settings
    if settings.provider_max_retries != 0 or settings.max_llm_calls != 2:
        raise ValueError("local_evaluation_profile_changed")
    if app.state.offline_chat_service._catalog.prepared_digest != plan["prepared_digest"]:
        raise ValueError("runtime_knowledge_differs_from_gold")
    async with app.router.lifespan_context(app):
        await run_cases(app, capture, requests, output, limit=limit)
    await asyncio.to_thread(write_run_binding, directory, output, runtime, plan, "live_local_mvp")


def percentile95(values: list[float]) -> float | None:
    return sorted(values)[math.ceil(0.95 * len(values)) - 1] if values else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run", "score"))
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--case-limit", type=int, default=50)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if args.mode == "prepare":
        if args.execute:
            parser.error("Preparation cannot dispatch requests.")
        prepare(root, args.source, args.output)
        print("Prepared source-bound answer key and run plan; no evaluation executed.")
    elif args.mode == "run":
        if not args.execute or args.plan is None or args.runtime_root is None:
            parser.error("Run requires --execute, --plan and --runtime-root after live approval.")
        asyncio.run(execute(root, args.plan, args.runtime_root, args.output, args.case_limit))
    else:
        if args.plan is None or args.run is None or args.execute:
            parser.error("Offline scoring requires --plan and --run; no --execute.")
        from scripts.natural_evaluation_scoring import score_run

        score_run(root, args.plan, args.run, args.output, args.review)


if __name__ == "__main__":
    main()
