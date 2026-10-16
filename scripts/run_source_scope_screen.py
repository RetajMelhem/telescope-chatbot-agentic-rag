"""One fixed source-scope development screen: 36 exposed and 12 new cases."""

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
from scripts.run_policy_target_screen import frozen_cases as policy_cases
from scripts.run_target_context_screen import frozen_cases as target_cases
from telescope_rag.core.settings import load_settings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.providers.openrouter import OpenRouterProviders

CASES = Path("artifacts/m5-source-scope-cases-v1")
MANIFEST_SHA256 = "a7ed521b97521f5b422dee32dafac5f024edb0201da33ebbb0d3764a848b3c68"
PROFILE = "source_scoped"


def frozen_cases(root: Path):
    directory = root / CASES
    if file_hash(directory / "manifest.json") != MANIFEST_SHA256:
        raise ValueError("source_scope_manifest_changed")
    manifest = json.loads((directory / "manifest.json").read_bytes())
    for name, digest in manifest["files"].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or file_hash(path) != digest:
            raise ValueError("source_scope_case_file_changed")
    rows = json.loads((directory / "cases.json").read_bytes())["cases"]
    expected = {f"S{i:02}-{lang}" for i in range(1, 5) for lang in ("ar", "ar-JO", "en")}
    if len(rows) != 12 or {r["case_id"] for r in rows} != expected:
        raise ValueError("source_scope_case_inventory_changed")
    return tuple(
        SimpleNamespace(
            case_id=r["case_id"],
            split="development",
            request=WorkflowRequest.model_validate_json(json.dumps(r["request"])),
        )
        for r in sorted(rows, key=lambda r: r["case_id"])
    )


def source_scope_plan(root: Path):
    plan, bindings = build_plan(root, profile=PROFILE, output_cap=4096)
    original = tuple(
        SimpleNamespace(
            case_id=p["case_id"],
            split="development",
            request=WorkflowRequest.model_validate_json(json.dumps(p["request"])),
        )
        for p in plan["packets"]
    )
    cases = tuple(
        sorted(
            original + target_cases(root) + policy_cases(root) + frozen_cases(root),
            key=lambda c: c.case_id,
        )
    )
    ids = tuple(c.case_id for c in cases)
    if len(ids) != len(set(ids)) or len(ids) != 48:
        raise ValueError("source_scope_screen_inventory_changed")
    plan.update(
        version="source-scope-screen-v1",
        case_ids=list(ids),
        requests_max=48,
        exposed_regression_cases=36,
        newly_frozen_cases=12,
        screen_timeout_seconds=1600,
        source_scope_case_manifest_sha256=MANIFEST_SHA256,
        directory_authority=bindings.directory_authority.model_dump(mode="json"),
        packets=development_packets(
            cases, bindings, profile=PROFILE, output_cap=4096, case_ids=ids, inventory=ids
        ),
    )
    return plan, bindings


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    plan, bindings = source_scope_plan(root)
    if not args.execute:
        args.output.mkdir(parents=True, exist_ok=False)
        write_new(args.output / "plan.json", plan)
        print(json.dumps({"prepared_requests": 48, "paid_requests": 0}))
        return
    if json.loads((args.output / "plan.json").read_bytes()) != plan:
        raise ValueError("source_scope_plan_or_current_code_changed")
    if (
        await asyncio.to_thread(
            subprocess.check_output, ["git", "status", "--porcelain"], text=True
        )
    ).strip():
        raise ValueError("source_scope_screen_requires_committed_code")
    write_new(
        args.output / "started.json",
        {
            "at_utc": datetime.now(UTC).isoformat(),
            "commit": (
                await asyncio.to_thread(
                    subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True
                )
            ).strip(),
            "requests_allowed": 48,
        },
    )
    before = file_hash(root / ".env")
    config = screen_settings(
        profile=PROFILE, output_cap=4096, key=load_settings().openrouter_api_key.get_secret_value()
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
                    profile=PROFILE,
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
