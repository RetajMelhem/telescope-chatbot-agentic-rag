"""Prepare, then explicitly execute six development-only planner requests.

No retrieval, drafting, embedding or index request is issued. Literal
validation never substitutes for a recorded human/LLM semantic review.
"""

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from scripts.check_frozen_benchmark import verify_inventory
from scripts.planner_review import (
    load_fixtures,
    validate_cohort,
    validate_reviews,
    validate_source_evidence,
)
from scripts.retrieval_benchmark import load_corpus
from telescope_rag.core.settings import Settings, load_settings
from telescope_rag.graph.anchoring import AnchoredPlannerReply, AnchorError, resolve_anchored_plan
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import PlannerReply, WorkflowRequest
from telescope_rag.graph.planning import planner_messages
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import ChatMessage, ChatProvider
from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.providers.validation import output_schema
from telescope_rag.retrieval.assembly import EvidenceCatalog

FIXTURES = Path("artifacts/m5-planner-cases-v1")
MANIFEST = "7c147ef1ab344d5a32f5ef1dbe0e00b26be047452388f38fa6d9b4ad8ec15c6a"
SOURCE_HASHES = Path("artifacts/m3-retrieval-benchmark-v1/authoring/source-input-hashes.json")
DEVELOPMENT_IDS = tuple(
    f"{family}-{lang}" for family in ("PL01", "PL05") for lang in ("ar", "ar-JO", "en")
)
OUTPUT_CAP = 1000  # Exactly the graph's current planning cap; no tuning in this screen.


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def screen_settings(
    *, key: str = "synthetic-screen-preparation", profile: str = "baseline"
) -> Settings:
    values = {n: f.get_default(call_default_factory=True) for n, f in Settings.model_fields.items()}
    values.update(
        openrouter_api_key=key,
        chat_input_accounting="reported_usage",
        provider_max_retries=0,
        max_llm_calls=1,
        chat_reasoning_effort="none" if profile == "source_types_no_reasoning" else None,
    )
    return Settings(_env_file=None, **values)


def planner_payload(
    messages: tuple[ChatMessage, ...], settings: Settings, *, profile="baseline"
) -> dict:
    model = AnchoredPlannerReply if profile == "literal_anchors" else PlannerReply
    payload = {
        "model": settings.openrouter_chat_model,
        "messages": [m.model_dump() for m in messages],
        "response_format": {"type": "json_schema", "json_schema": output_schema(model)},
        "max_completion_tokens": OUTPUT_CAP,
        "stream": False,
        "provider": {"require_parameters": True, "allow_fallbacks": False},
    }
    if settings.chat_reasoning_effort is not None:
        payload["reasoning"] = {"effort": settings.chat_reasoning_effort}
    return payload


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def development_packets(cases, bindings: SourceBindings, *, profile="baseline") -> list[dict]:
    selected = sorted((c for c in cases if c.split == "development"), key=lambda c: c.case_id)
    if tuple(c.case_id for c in selected) != DEVELOPMENT_IDS:
        raise ValueError("development_inventory_mismatch")
    config = screen_settings(profile=profile)
    packets = []
    for case in selected:
        payload = planner_payload(
            planner_messages(case.request, bindings, max_parts=4, profile=profile),
            config,
            profile=profile,
        )
        packets.append(
            {
                "case_id": case.case_id,
                "request": case.request.model_dump(mode="json"),
                "payload": payload,
                "payload_sha256": payload_hash(payload),
            }
        )
    return packets


def build_plan(root: Path, *, profile="baseline") -> tuple[dict, SourceBindings]:
    if profile not in {"baseline", "source_types_no_reasoning", "literal_anchors"}:
        raise ValueError("unknown_planner_profile")
    directory = root / FIXTURES
    manifest = verify_inventory(directory, MANIFEST)
    source_hashes = json.loads((root / SOURCE_HASHES).read_bytes())
    if len(source_hashes) != 122 or any(file_hash(root / p) != h for p, h in source_hashes.items()):
        raise ValueError("sealed_source_input_changed")
    historical_changes = {}
    for name, expected in manifest["bindings"].items():
        actual = file_hash(root / name)
        if actual != expected:
            if not name.endswith(".py") or not name.startswith(("src/", "scripts/")):
                raise ValueError("frozen_noncode_binding_changed")
            historical_changes[name] = {"historical_sha256": expected, "current_sha256": actual}
    bundle = root / manifest["source_bundle"]
    documents, _ = load_corpus(bundle)
    catalog = EvidenceCatalog(documents, expected_digest=manifest["prepared_digest"])
    cases = load_fixtures((directory / "cases.jsonl",))
    validate_cohort(
        cases,
        catalog,
        expected_families=tuple(f"PL{i:02}" for i in range(1, 9)),
        development_families=("PL01", "PL05"),
    )
    reviews = json.loads((directory / "independent-reviews.json").read_bytes())
    validate_reviews(cases, reviews)
    source_checks = validate_source_evidence(reviews, catalog, bundle=bundle, packet_root=directory)
    bindings = SourceBindings(catalog, include_block_types=profile != "baseline")
    code = sorted(
        p for parent in (root / "src/telescope_rag", root / "scripts") for p in parent.rglob("*.py")
    )
    return {
        "version": "luna-development-planner-screen-v1",
        "profile": profile,
        "fixture_manifest_sha256": MANIFEST,
        "prepared_digest": catalog.prepared_digest,
        "sealed_source_hash_inventory_sha256": file_hash(root / SOURCE_HASHES),
        "source_integrity": source_checks,
        "code_sha256": {p.relative_to(root).as_posix(): file_hash(p) for p in code},
        "historical_code_binding_changes": historical_changes,
        "model": "openai/gpt-6-luna",
        "requests_max": 6,
        "per_request_output_cap": OUTPUT_CAP,
        "retries": 0,
        "screen_timeout_seconds": 180,
        "local_input_count_required": False,
        "cost_quote_usd": None,
        "per_run_dollar_cap_configured": False,
        "reserved_evaluation_requests": 0,
        "embedding_calls": 0,
        "qdrant_calls": 0,
        "answer_generation_calls": 0,
        "packets": development_packets(cases, bindings, profile=profile),
        "semantic_scoring": "Actual root language review required after execution; "
        "no exact-gold or keyword semantic judge.",
    }, bindings


async def run_packets(
    packets, bindings, settings, chat: ChatProvider, directory: Path, *, profile="baseline"
) -> dict:
    if tuple(p["case_id"] for p in packets) != DEVELOPMENT_IDS:
        raise ValueError("development_inventory_mismatch")
    rows = []
    for packet in packets:
        request = WorkflowRequest.model_validate_json(json.dumps(packet["request"]))
        messages = planner_messages(
            request, bindings, max_parts=settings.max_subquestions, profile=profile
        )
        if (
            payload_hash(planner_payload(messages, settings, profile=profile))
            != packet["payload_sha256"]
        ):
            raise ValueError("screen_payload_changed")
        budget = ExecutionBudget(settings)
        row = {
            "case_id": packet["case_id"],
            "payload_sha256": packet["payload_sha256"],
            "proposal": None,
            "schema_valid": False,
            "literal_bindings_valid": False,
            "error_code": None,
            "semantic_review": "pending",
        }
        started = time.monotonic()
        fatal = False
        model = AnchoredPlannerReply if profile == "literal_anchors" else PlannerReply
        try:
            result = await chat.complete(
                messages, model, max_output_tokens=OUTPUT_CAP, budget=budget
            )
            if type(result.data) is not model:
                raise ValueError("screen_reply_type_invalid")
            row["proposal"] = result.data.model_dump(mode="json")
            row["schema_valid"] = True
            try:
                proposal = result.data
                if profile == "literal_anchors":
                    proposal, anchors = resolve_anchored_plan(proposal, request, packet["case_id"])
                    row["derived_proposal"] = proposal.model_dump(mode="json")
                    row["request_anchors"] = [asdict(a) for a in anchors]
                bindings.validate(proposal, request, packet["case_id"], max_parts=4)
                row["literal_bindings_valid"] = True
            except ValueError as error:
                row["error_code"] = (
                    str(error)
                    if type(error) is ValueError or isinstance(error, AnchorError)
                    else "invalid_plan"
                )
        except ProviderError as error:
            row["error_code"] = error.code
            fatal = error.status_code in {400, 401, 402, 403, 404} or error.code in {
                "reported_model_mismatch",
                "missing_reported_model",
                "missing_provider_credentials",
            }
        finally:
            row["elapsed_seconds"] = time.monotonic() - started
            row["reported_input_tokens"] = budget.input_charged["chat"]
            row["charged_output_tokens"] = budget.output_charged
            row["physical_attempts"] = budget.attempts["chat"]
            row["receipts"] = [
                {**asdict(r), "usage": r.usage.model_dump()} for r in budget.receipts
            ]
            write_new(directory / f"{packet['case_id']}.json", row)
            rows.append(row)
        if fatal:
            break
    summary = {
        "cases_attempted": len(rows),
        "cases_planned": 6,
        "physical_attempts": sum(r["physical_attempts"] for r in rows),
        "schema_valid": sum(r["schema_valid"] for r in rows),
        "literal_bindings_valid": sum(r["literal_bindings_valid"] for r in rows),
        "case_results": [
            {k: r[k] for k in ("case_id", "schema_valid", "literal_bindings_valid", "error_code")}
            for r in rows
        ],
        "semantic_review_completed": False,
        "production_ready": False,
        "embedding_calls": 0,
        "qdrant_calls": 0,
        "answer_generation_calls": 0,
        "reserved_evaluation_requests": 0,
    }
    write_new(directory / "summary.json", summary)
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--profile",
        choices=("baseline", "source_types_no_reasoning", "literal_anchors"),
        default="baseline",
    )
    args = parser.parse_args()
    root = Path.cwd()
    plan, bindings = build_plan(root, profile=args.profile)
    if not args.execute:
        args.output.mkdir(parents=True, exist_ok=False)
        write_new(args.output / "plan.json", plan)
        print(json.dumps({"prepared_requests": 6, "paid_requests": 0, "output": str(args.output)}))
        return
    if json.loads((args.output / "plan.json").read_bytes()) != plan:
        raise ValueError("screen_plan_or_current_code_changed")
    status = await asyncio.to_thread(
        subprocess.check_output, ["git", "status", "--porcelain"], text=True
    )
    if status.strip():
        raise ValueError("screen_requires_committed_code")
    # Exclusive marker refuses repetition, including partially failed/ambiguous runs.
    write_new(
        args.output / "started.json",
        {
            "at_utc": datetime.now(UTC).isoformat(),
            "commit": (
                await asyncio.to_thread(
                    subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True
                )
            ).strip(),
            "requests_allowed": 6,
        },
    )
    env = root / ".env"
    before = file_hash(env)
    config = screen_settings(
        key=load_settings().openrouter_api_key.get_secret_value(), profile=args.profile
    )
    try:
        async with asyncio.timeout(plan["screen_timeout_seconds"]):
            async with OpenRouterProviders(config) as providers:
                summary = await run_packets(
                    plan["packets"],
                    bindings,
                    config,
                    providers.chat,
                    args.output,
                    profile=args.profile,
                )
        print(json.dumps(summary))
    finally:
        write_new(
            args.output / "finished.json",
            {"at_utc": datetime.now(UTC).isoformat(), "dotenv_unchanged": file_hash(env) == before},
        )


if __name__ == "__main__":
    asyncio.run(main())
