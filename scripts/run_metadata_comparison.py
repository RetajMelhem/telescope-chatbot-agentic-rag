"""Once-only paired v6 wire experiment; reviewed source metadata is the sole difference."""

import argparse
import asyncio
import copy
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scripts.run_luna_planner_screen import (
    build_plan,
    file_hash,
    payload_hash,
    planner_payload,
    run_packets,
    screen_settings,
    write_new,
)
from scripts.run_source_scope_screen import source_scope_plan
from telescope_rag.core.settings import load_settings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.graph.planning import planner_messages
from telescope_rag.providers.openrouter import OpenRouterProviders

PROPOSAL = Path("artifacts/m5-source-scope-screen-v2/next-metadata-only-comparison-proposal.json")
SEAL = Path("artifacts/m5-source-scope-screen-v2/evidence-seal.json")
ARMS = ("control", "source_metadata_only")
PROFILE = "policy_targets"


def verify_pairs(packets, case_ids):
    """Structural wire invariants, never semantic acceptance."""
    expected = [
        (case, arm)
        for index, case in enumerate(case_ids)
        for arm in (ARMS if index % 2 == 0 else ARMS[::-1])
    ]
    if [(p["case_id"], p["arm"]) for p in packets] != expected:
        raise ValueError("paired_inventory_or_order_changed")
    for offset in range(0, len(packets), 2):
        left, right = packets[offset : offset + 2]
        if left["request"] != right["request"]:
            raise ValueError("paired_request_changed")
        payloads = []
        manifests = []
        for packet in (left, right):
            if set(packet) != {"case_id", "arm", "request", "payload", "payload_sha256"}:
                raise ValueError("paired_packet_fields_changed")
            if payload_hash(packet["payload"]) != packet["payload_sha256"]:
                raise ValueError("paired_payload_hash_changed")
            payload = copy.deepcopy(packet["payload"])
            body = json.loads(payload["messages"][-1]["content"])
            manifests.append(body.pop("source_manifest"))
            payload["messages"][-1]["content"] = body
            payloads.append(payload)
        if payloads[0] != payloads[1] or manifests[0] == manifests[1]:
            raise ValueError("paired_single_difference_violated")


def comparison_plan(root: Path):
    sealed = json.loads((root / SEAL).read_bytes())["files"]
    for name, digest in sealed.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or file_hash(path) != digest:
            raise ValueError("previous_experiment_evidence_changed")
    if PROPOSAL.as_posix() not in sealed:
        raise ValueError("comparison_proposal_not_sealed")
    proposal = json.loads((root / PROPOSAL).read_bytes())
    base, treatment = source_scope_plan(root)
    _, control = build_plan(root, profile=PROFILE, output_cap=4096)
    bindings = dict(zip(ARMS, (control, treatment), strict=True))
    ids = tuple(base["case_ids"])
    packets = proposal["packets"]
    verify_pairs(packets, ids)
    if len(ids) != 48 or len(packets) != 96:
        raise ValueError("comparison_inventory_changed")
    config = screen_settings(profile=PROFILE, output_cap=4096)
    for packet in packets:
        # Authenticate against the current builder and original source bindings, not
        # merely a self-consistent serialized hash. No gold enters the wire.
        request = WorkflowRequest.model_validate_json(json.dumps(packet["request"]))
        actual = planner_payload(
            planner_messages(request, bindings[packet["arm"]], max_parts=4, profile=PROFILE),
            config,
            profile=PROFILE,
            output_cap=4096,
        )
        if actual != packet["payload"]:
            raise ValueError("comparison_builder_or_frozen_payload_changed")
    base.update(
        version="v6-source-metadata-paired-comparison-v1",
        profile=PROFILE,
        proposal_sha256=file_hash(root / PROPOSAL),
        previous_evidence_seal_sha256=file_hash(root / SEAL),
        previous_sealed_files=len(sealed),
        requests_max=96,
        case_pairs=48,
        screen_timeout_seconds=3100,
        packets=packets,
        only_treatment_difference="source_manifest",
        fixed_alternating_arm_order=True,
        cases_already_exposed=True,
        default_adoption=False,
    )
    return base, bindings


def fatal_result(row):
    return any(r["status_code"] in {400, 401, 402, 403, 404} for r in row["receipts"]) or row[
        "error_code"
    ] in {"reported_model_mismatch", "missing_reported_model", "missing_provider_credentials"}


async def run_comparison(plan, bindings, config, chat, directory: Path):
    ids = tuple(plan["case_ids"])
    verify_pairs(plan["packets"], ids)
    # Validate the WHOLE dispatch list before any billable attempt.
    for packet in plan["packets"]:
        request = WorkflowRequest.model_validate_json(json.dumps(packet["request"]))
        actual = planner_payload(
            planner_messages(request, bindings[packet["arm"]], max_parts=4, profile=PROFILE),
            config,
            profile=PROFILE,
            output_cap=4096,
        )
        if actual != packet["payload"]:
            raise ValueError("comparison_builder_or_frozen_payload_changed")
    rows = []
    for packet in plan["packets"]:
        identity, arm = packet["case_id"], packet["arm"]
        output = directory / arm / identity
        output.mkdir(parents=True, exist_ok=False)
        # Reuse the same production adapter and literal validation, with one
        # exclusive result directory per arm/case. No semantic repair/retry.
        await run_packets(
            [packet],
            bindings[arm],
            config,
            chat,
            output,
            profile=PROFILE,
            output_cap=4096,
            case_ids=(identity,),
            inventory=ids,
        )
        row = json.loads((output / f"{identity}.json").read_bytes())
        rows.append({"arm": arm, **row})
        print(
            json.dumps(
                {
                    "completed": len(rows),
                    "planned": len(plan["packets"]),
                    "case": identity,
                    "arm": arm,
                    "schema_valid": row["schema_valid"],
                    "error": row["error_code"],
                }
            ),
            flush=True,
        )
        if fatal_result(row):
            break
    summary = {
        "planned": len(plan["packets"]),
        "attempted": len(rows),
        "physical_attempts": sum(r["physical_attempts"] for r in rows),
        "schema_valid": sum(r["schema_valid"] for r in rows),
        "literal_valid": sum(r["literal_bindings_valid"] for r in rows),
        "stopped_fatal": bool(rows and fatal_result(rows[-1])),
        "semantic_review_completed": False,
        "production_ready": False,
        "embedding_calls": 0,
        "qdrant_calls": 0,
        "answer_generation_calls": 0,
        "reserved_evaluation_requests": 0,
        "results": [
            {
                k: r[k]
                for k in ("case_id", "arm", "schema_valid", "literal_bindings_valid", "error_code")
            }
            for r in rows
        ],
    }
    write_new(directory / "summary.json", summary)
    return summary


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    plan, bindings = comparison_plan(root)
    if not args.execute:
        args.output.mkdir(parents=True, exist_ok=False)
        write_new(args.output / "plan.json", plan)
        print(json.dumps({"prepared_requests": 96, "paid_requests": 0}))
        return
    if json.loads((args.output / "plan.json").read_bytes()) != plan:
        raise ValueError("comparison_plan_or_code_changed")
    if (
        await asyncio.to_thread(
            subprocess.check_output, ["git", "status", "--porcelain"], text=True
        )
    ).strip():
        raise ValueError("comparison_requires_committed_code")
    write_new(
        args.output / "started.json",
        {
            "at_utc": datetime.now(UTC).isoformat(),
            "commit": (
                await asyncio.to_thread(
                    subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True
                )
            ).strip(),
            "requests_allowed": 96,
        },
    )
    before = file_hash(root / ".env")
    config = screen_settings(
        profile=PROFILE, output_cap=4096, key=load_settings().openrouter_api_key.get_secret_value()
    )
    try:
        async with asyncio.timeout(plan["screen_timeout_seconds"]):
            async with OpenRouterProviders(config) as providers:
                await run_comparison(plan, bindings, config, providers.chat, args.output)
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
