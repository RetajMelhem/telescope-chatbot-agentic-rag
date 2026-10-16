"""Explicitly prepared fresh target/context screen; no original reserved dispatch."""

import argparse
import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from scripts.run_luna_planner_screen import (
    build_plan,
    development_packets,
    file_hash,
    run_packets,
    screen_settings,
    write_new,
)
from telescope_rag.core.settings import load_settings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.providers.openrouter import OpenRouterProviders

CASES = Path("artifacts/m5-target-context-cases-v1")
MANIFEST_SHA256 = "5c2e81917da4e4174de99452953641329bea2735a250db4023f9e69aa6fdf6d1"


def frozen_cases(root: Path):
    directory = root / CASES
    if file_hash(directory / "manifest.json") != MANIFEST_SHA256:
        raise ValueError("fresh_manifest_changed")
    manifest = json.loads((directory / "manifest.json").read_bytes())
    for name, digest in manifest["files"].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or file_hash(path) != digest:
            raise ValueError("fresh_case_file_changed")
    rows = json.loads((directory / "cases.json").read_bytes())["cases"]
    if len(rows) != 18 or len({r["case_id"] for r in rows}) != 18:
        raise ValueError("fresh_case_inventory_changed")
    return tuple(
        SimpleNamespace(
            case_id=r["case_id"],
            split="development",
            request=WorkflowRequest.model_validate_json(json.dumps(r["request"])),
        )
        for r in sorted(rows, key=lambda r: r["case_id"])
    )


def fresh_plan(root: Path):
    # This revalidates the original source, review and DOM evidence; no original
    # fixture gold is exported to the new provider messages.
    plan, bindings = build_plan(root, profile="answer_targets", output_cap=4096)
    cases = frozen_cases(root)
    ids = tuple(c.case_id for c in cases)
    plan.update(
        version="fresh-target-context-screen-v1",
        case_ids=list(ids),
        requests_max=18,
        screen_timeout_seconds=600,
        fresh_case_manifest_sha256=MANIFEST_SHA256,
        packets=development_packets(
            cases,
            bindings,
            profile="answer_targets",
            output_cap=4096,
            case_ids=ids,
            inventory=ids,
        ),
    )
    return plan, bindings


def require_development_acceptance(path: Path, root: Path, expected_code: dict[str, str]):
    review = json.loads(path.read_bytes())
    if (
        review.get("actual_plans_reviewed") != 6
        or review.get("semantic_passes") != 6
        or review.get("profile") != "answer_targets"
        or len(review.get("reviews", [])) != 6
    ):
        raise ValueError("fresh_screen_requires_development_semantic_acceptance")
    capture = (root / review["execution_directory"]).resolve()
    if not capture.is_relative_to(root.resolve()):
        raise ValueError("development_capture_outside_workspace")
    plan = json.loads((capture / "plan.json").read_bytes())
    if plan["profile"] != "answer_targets" or plan["code_sha256"] != expected_code:
        raise ValueError("development_review_different_candidate")
    if {r["case_id"] for r in review["reviews"]} != set(plan["case_ids"]):
        raise ValueError("development_review_inventory_mismatch")
    for row in review["reviews"]:
        result_path = capture / f"{row['case_id']}.json"
        if not result_path.resolve().is_relative_to(capture):
            raise ValueError("development_result_outside_capture")
        if not row["semantic_admitted"] or file_hash(result_path) != row["result_sha256"]:
            raise ValueError("development_review_result_mismatch")
        result = json.loads(result_path.read_bytes())
        if not result["schema_valid"] or not result["literal_bindings_valid"]:
            raise ValueError("development_result_not_valid")
    return file_hash(path)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--development-review", type=Path)
    args = parser.parse_args()
    root = Path.cwd()
    plan, bindings = fresh_plan(root)
    if not args.execute:
        args.output.mkdir(parents=True, exist_ok=False)
        write_new(args.output / "plan.json", plan)
        print(json.dumps({"prepared_requests": 18, "paid_requests": 0}))
        return
    if json.loads((args.output / "plan.json").read_bytes()) != plan:
        raise ValueError("fresh_plan_or_current_code_changed")
    if args.development_review is None:
        raise ValueError("development_semantic_review_required")
    review_hash = require_development_acceptance(args.development_review, root, plan["code_sha256"])
    if (
        await asyncio.to_thread(
            subprocess.check_output, ["git", "status", "--porcelain"], text=True
        )
    ).strip():
        raise ValueError("fresh_screen_requires_committed_code")
    write_new(
        args.output / "started.json",
        {
            "at_utc": datetime.now(UTC).isoformat(),
            "commit": (
                await asyncio.to_thread(
                    subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True
                )
            ).strip(),
            "requests_allowed": 18,
            "development_review_sha256": review_hash,
        },
    )
    before = file_hash(root / ".env")
    config = screen_settings(
        profile="answer_targets",
        output_cap=4096,
        key=load_settings().openrouter_api_key.get_secret_value(),
    )
    try:
        async with asyncio.timeout(plan["screen_timeout_seconds"]):
            async with OpenRouterProviders(config) as providers:
                result = await run_packets(
                    plan["packets"],
                    bindings,
                    config,
                    providers.chat,
                    args.output,
                    profile="answer_targets",
                    output_cap=4096,
                    case_ids=tuple(plan["case_ids"]),
                    inventory=tuple(plan["case_ids"]),
                )
        print(json.dumps(result))
    finally:
        write_new(
            args.output / "finished.json",
            {
                "at_utc": datetime.now(UTC).isoformat(),
                "dotenv_unchanged": file_hash(root / ".env") == before,
            },
        )


if __name__ == "__main__":
    asyncio.run(main())
