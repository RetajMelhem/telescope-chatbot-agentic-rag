"""Once-only comparison of sealed v6/role versus v8 purpose-contract planning packets.

No semantic judge, retrieval, draft, embedding, index access or automatic retry.
"""

import argparse
import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scripts.retrieval_benchmark import load_corpus
from scripts.run_luna_planner_screen import (
    SOURCE_HASHES,
    file_hash,
    payload_hash,
    planner_payload,
    run_packets,
    screen_settings,
    write_new,
)
from scripts.run_metadata_comparison import fatal_result
from telescope_rag.core.settings import load_settings
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.graph.planning import planner_messages
from telescope_rag.ingestion.admission import AdmissionPlan
from telescope_rag.knowledge.source_authority import reviewed_directory_authority
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.retrieval.assembly import EvidenceCatalog

PREPARATION = Path("artifacts/m5-purpose-contract-preparation-v1")
SEAL_SHA256 = "18ccdd4086f71845456aa832dce70c50474f082613eb3d946e0e27015615dff5"
SOURCE = Path("data/processed/m3-llm-semantic-token-validated-v6")
ARMS = ("control", "purpose_contract")
PROFILES = {"control": "policy_targets", "purpose_contract": "purpose_contract"}


def verify_packets(plan, bindings, settings):
    ids = tuple(plan["case_ids"])
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("purpose_case_inventory_changed")
    expected = [(i, a) for n, i in enumerate(ids) for a in (ARMS if n % 2 == 0 else ARMS[::-1])]
    packets = plan["packets"]
    if [(p["case_id"], p["arm"]) for p in packets] != expected:
        raise ValueError("purpose_dispatch_inventory_or_order_changed")
    for offset in range(0, len(packets), 2):
        left, right = packets[offset : offset + 2]
        if left["request"] != right["request"] or {
            k: v for k, v in left["payload"].items() if k != "messages"
        } != {k: v for k, v in right["payload"].items() if k != "messages"}:
            raise ValueError("purpose_pair_wire_contract_changed")
        for packet in (left, right):
            if set(packet) != {"case_id", "arm", "request", "payload", "payload_sha256"}:
                raise ValueError("purpose_packet_fields_changed")
            request = WorkflowRequest.model_validate_json(json.dumps(packet["request"]))
            profile = PROFILES[packet["arm"]]
            actual = planner_payload(
                planner_messages(request, bindings[packet["arm"]], max_parts=4, profile=profile),
                settings,
                profile=profile,
                output_cap=4096,
            )
            if actual != packet["payload"] or payload_hash(actual) != packet["payload_sha256"]:
                raise ValueError("purpose_builder_or_frozen_payload_changed")


def comparison_plan(root: Path):
    seal = root / PREPARATION / "evidence-seal.json"
    if file_hash(seal) != SEAL_SHA256:
        raise ValueError("purpose_preparation_seal_changed")
    sealed = json.loads(seal.read_bytes())["files"]
    for name, expected in sealed.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or file_hash(path) != expected:
            raise ValueError("purpose_preparation_evidence_changed")
    source_hashes = json.loads((root / SOURCE_HASHES).read_bytes())
    if len(source_hashes) != 122 or any(file_hash(root / p) != h for p, h in source_hashes.items()):
        raise ValueError("purpose_sealed_source_changed")
    frozen = json.loads((root / PREPARATION / "frozen-contrasts.json").read_bytes())
    original = json.loads((root / PREPARATION / "final/prepared-packets.json").read_bytes())[
        "packets"
    ]
    ids = tuple(c["case_id"] for c in frozen["cases"])
    lookup = {(p["case_id"], p["arm"]): p for p in original}
    if len(ids) != 24 or len(original) != 48 or len(lookup) != 48:
        raise ValueError("purpose_frozen_inventory_changed")
    documents, _ = load_corpus(root / SOURCE)
    catalog = EvidenceCatalog(documents, expected_digest=frozen["prepared_digest"])
    authority = reviewed_directory_authority(
        AdmissionPlan.model_validate_json(
            (root / SOURCE / "metadata/source-admission-plan.json").read_bytes()
        ),
        json.loads((root / SOURCE / "metadata/primary-directory.json").read_bytes()),
        prepared_digest=catalog.prepared_digest,
    )
    bindings = {
        a: SourceBindings(
            catalog,
            include_block_types=True,
            directory_authority=authority,
            purpose_contract=a == "purpose_contract",
        )
        for a in ARMS
    }
    packets = []
    for n, identity in enumerate(ids):
        for arm in ARMS if n % 2 == 0 else ARMS[::-1]:
            old = lookup[identity, arm]
            packets.append(
                {k: old[k] for k in ("case_id", "arm", "request", "payload", "payload_sha256")}
            )
    plan = {
        "version": "purpose-contract-paired-planner-v1",
        "case_ids": ids,
        "packets": packets,
        "requests_max": 48,
        "prepared_digest": catalog.prepared_digest,
        "preparation_seal_sha256": SEAL_SHA256,
        "preparation_files": len(sealed),
        "code_sha256": {
            p.relative_to(root).as_posix(): file_hash(p)
            for folder in ("src", "scripts")
            for p in sorted((root / folder).rglob("*.py"))
        },
        "fixed_alternating_arm_order": True,
        "cases_already_exposed": True,
        "single_variable_causal_experiment": False,
        "default_adoption": False,
        "screen_timeout_seconds": 1600,
        "semantic_scoring": "Individual primary language review required; no script grades.",
    }
    verify_packets(plan, bindings, screen_settings(profile="policy_targets", output_cap=4096))
    return plan, bindings


async def run_comparison(plan, bindings, settings, chat, directory: Path):
    # Authenticate the entire list before the first potentially billable attempt.
    verify_packets(plan, bindings, settings)
    rows = []
    for packet in plan["packets"]:
        identity, arm = packet["case_id"], packet["arm"]
        output = directory / arm / identity
        output.mkdir(parents=True, exist_ok=False)
        await run_packets(
            [packet],
            bindings[arm],
            settings,
            chat,
            output,
            profile=PROFILES[arm],
            case_ids=(identity,),
            inventory=tuple(plan["case_ids"]),
            output_cap=4096,
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
    # JSON round-trip normalizes only container representation, never message text.
    plan = json.loads(json.dumps(plan))
    if not args.execute:
        args.output.mkdir(parents=True, exist_ok=False)
        write_new(args.output / "plan.json", plan)
        print(json.dumps({"prepared_requests": 48, "paid_requests": 0}))
        return
    if json.loads((args.output / "plan.json").read_bytes()) != plan:
        raise ValueError("purpose_plan_or_code_changed")
    if (
        await asyncio.to_thread(
            subprocess.check_output, ["git", "status", "--porcelain"], text=True
        )
    ).strip():
        raise ValueError("purpose_requires_committed_code")
    write_new(
        args.output / "started.json",
        {
            "at_utc": datetime.now(UTC).isoformat(),
            "requests_allowed": 48,
            "commit": (
                await asyncio.to_thread(
                    subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True
                )
            ).strip(),
        },
    )
    before = file_hash(root / ".env")
    config = screen_settings(
        profile="policy_targets",
        output_cap=4096,
        key=load_settings().openrouter_api_key.get_secret_value(),
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
