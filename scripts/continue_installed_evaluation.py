"""Explicitly continue an approved cohort's unsent suffix, preserving both batches.

Each remaining question is attempted once even when another question fails. The
original run and sealed evaluation modules are never changed. No imports dispatch
requests; the CLI requires --execute after explicit continuation authorization.
"""

import argparse
import asyncio
import json
import os
import shutil
from pathlib import Path

from scripts import natural_evaluation_portable as portable
from scripts.natural_evaluation import (
    digest,
    requests_from,
    verify_plan,
    write_new,
    write_run_binding,
)
from scripts.natural_evaluation_scoring import bind_record, score_run

RECEIPTS = ("preflight-before.json", "http-preflight.json", "preflight-after.json")


def _read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _hashes(directory: Path, names: list[str]) -> dict:
    return {name: digest(directory / name) for name in names}


def _unchanged(parent: Path, hashes: dict, helper_hash: str) -> None:
    _require(_hashes(parent, list(hashes)) == hashes, "parent_run_changed")
    _require(digest(Path(__file__)) == helper_hash, "continuation_helper_changed")


def _paths(output: Path, parent: Path) -> tuple[Path, Path]:
    return output.resolve(), parent.resolve()


def validate_parent(root: Path, plan_dir: Path, parent: Path, output: Path) -> tuple:
    """The existing strict scorer validates every parent binding before any network."""
    plan = verify_plan(root, plan_dir)
    _require(plan.get("transport_kind") == "installed_portable_http", "plan_transport_invalid")
    requests = requests_from(plan_dir / "requests.jsonl")
    binding, index = _read(parent / "run-binding.json"), _read(parent / "execution-index.json")
    _require(
        binding["execution_kind"] == "installed_portable_http"
        and index.get("status") == "stopped"
        and index.get("retries") == 0
        and index["requested_cases"] == len(requests) == 50
        and type(index["attempted_cases"]) is int
        and 0 < index["attempted_cases"] < 50,
        "parent_is_not_stopped_full_cohort_prefix",
    )
    score_run(root, plan_dir, parent, output / "parent-validation", None)
    names = ["run-binding.json", "execution-index.json", *RECEIPTS, *index["case_files"]]
    hashes = _hashes(parent, names)
    before, after = (_read(parent / name) for name in (RECEIPTS[0], RECEIPTS[2]))
    _require(before == after and before["status"] == "verified", "parent_runtime_not_verified")
    return plan, requests, index["attempted_cases"], before, hashes


def _assemble(
    root: Path,
    plan_dir: Path,
    plan: dict,
    parent: Path,
    output: Path,
    install_root: Path,
    requests: list[dict],
    previous_count: int,
    rows: list[dict],
    provenance: dict,
) -> None:
    combined = output / "combined"
    combined.mkdir()
    count = previous_count + len(rows)
    for index, request in enumerate(requests[:count]):
        name = f"{request['case_id']}.json"
        source = parent if index < previous_count else output
        shutil.copyfile(source / name, combined / name)
    for name in RECEIPTS:
        source = output if name == "preflight-after.json" else parent
        shutil.copyfile(source / name, combined / name)
    batch_receipts = combined / "continuation-batch-receipts"
    batch_receipts.mkdir()
    for name in RECEIPTS:
        shutil.copyfile(output / name, batch_receipts / name)
    write_new(combined / "continuation-provenance.json", provenance)
    write_new(
        combined / "execution-index.json",
        {
            "requested_cases": len(requests),
            "attempted_cases": count,
            "not_attempted_case_ids": [r["case_id"] for r in requests[count:]],
            "case_files": [f"{r['case_id']}.json" for r in requests[:count]],
            "retries": 0,
            "status": "complete" if count == len(requests) else "stopped",
            "execution_description": (
                "Assembled from two separately authorized serial batches; not a new run."
            ),
            "continuation_provenance_sha256": digest(combined / "continuation-provenance.json"),
            "continuation_receipts_sha256": _hashes(batch_receipts, list(RECEIPTS)),
            "plan_sha256": digest(plan_dir / "plan.json"),
            "internal_trace_available": False,
        },
    )
    write_run_binding(plan_dir, combined, install_root, plan, "installed_portable_http")
    score_run(root, plan_dir, combined, output / "combined-validation", None)


async def continue_run(
    root: Path, plan_dir: Path, parent: Path, output: Path, install_root: Path
) -> list[dict]:
    output, parent = await asyncio.to_thread(_paths, output, parent)
    _require(
        not output.is_relative_to(parent) and not parent.is_relative_to(output),
        "continuation_output_overlaps_parent",
    )
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False)
    plan, requests, previous_count, parent_before, parent_hashes = {}, [], 0, None, {}
    helper_hash = digest(Path(__file__))
    rows, before, failure = [], None, None
    try:
        plan, requests, previous_count, parent_before, parent_hashes = await asyncio.to_thread(
            validate_parent, root, plan_dir, parent, output
        )
        before = await asyncio.to_thread(portable.preflight, plan, install_root)
        _require(before == parent_before, "continuation_target_differs_from_parent")
        write_new(output / RECEIPTS[0], before)
        async with portable._client(before["base_url"]) as client:
            http_receipt = await portable.verify_http(client)
            _unchanged(parent, parent_hashes, helper_hash)
            current = await asyncio.to_thread(portable.preflight, plan, install_root)
            _require(current == before, "continuation_target_changed")
            http_receipt["runtime_unchanged_before_first_question"] = True
            write_new(output / RECEIPTS[1], http_receipt)
            for request in requests[previous_count:]:
                current = await asyncio.to_thread(portable.preflight, plan, install_root)
                _require(current == before, "continuation_target_changed")
                row = await portable._case(client, request)
                if row["http_status"] == 200 and row.get("error") is None:
                    try:
                        bind_record(
                            row,
                            request,
                            plan["prepared_digest"],
                            execution_kind="installed_portable_http",
                            snapshot_id=plan["snapshot_id"],
                        )
                    except Exception as error:
                        row["error"] = portable._safe_error(error)
                write_new(output / f"{request['case_id']}.json", row)
                rows.append(row)
                print(
                    json.dumps(
                        {
                            "case_id": request["case_id"],
                            "http_status": row["http_status"],
                            "error": row["error"],
                        }
                    ),
                    flush=True,
                )
                if row["error"] in {
                    "response_knowledge_source_mismatch",
                    "response_citation_snapshot_mismatch",
                }:
                    raise ValueError("continuation_response_source_changed")
                if row["error"] == "CancelledError":
                    raise ValueError("continuation_cancelled")
                # Explicit user instruction: complete all unsent cases, preserving failures.
    except (asyncio.CancelledError, KeyboardInterrupt):
        failure = "continuation_cancelled"
    except Exception as error:
        failure = portable._safe_error(error)
    finally:
        for name in RECEIPTS[:2]:
            if not (output / name).exists():
                write_new(output / name, {"status": "failed", "error": failure})
        try:
            _require(bool(parent_hashes), "parent_validation_incomplete")
            _unchanged(parent, parent_hashes, helper_hash)
            after = await asyncio.to_thread(portable.preflight, plan, install_root)
            _require(after == before == parent_before, "continuation_target_changed")
            write_new(output / RECEIPTS[2], after)
        except Exception as error:
            code = portable._safe_error(error)
            failure = failure or code
            write_new(output / RECEIPTS[2], {"status": "failed", "error": code})
        remaining = requests[previous_count:]
        write_new(
            output / "execution-index.json",
            {
                "requested_cases": len(remaining),
                "attempted_cases": len(rows),
                "not_attempted_case_ids": [r["case_id"] for r in remaining[len(rows) :]],
                "case_files": [f"{r['case_id']}.json" for r in rows],
                "retries": 0,
                "status": "failed" if failure else "complete",
                "error": failure,
                "continue_after_case_failures": True,
                "internal_trace_available": False,
            },
        )
        provenance = {
            "schema_version": "natural-evaluation-continuation-v1",
            "description": (
                "Two separately authorized batches; original results preserved byte for byte."
            ),
            "authorization": (
                "Explicit continuation of every unsent question once, including after "
                "per-case errors; no retries or application fixes."
            ),
            "helper_sha256": helper_hash,
            "parent_run": str(parent),
            "parent_files_sha256": parent_hashes,
            "parent_attempted_cases": previous_count,
            "plan_sha256": digest(plan_dir / "plan.json"),
            "requests_sha256": plan.get("requests_sha256"),
            "prepared_digest": plan.get("prepared_digest"),
            "continuation_receipts_sha256": _hashes(output, list(RECEIPTS)),
            "continuation_index_sha256": digest(output / "execution-index.json"),
            "continuation_cases_sha256": _hashes(output, [f"{r['case_id']}.json" for r in rows]),
            "status": "failed" if failure else "complete",
            "error": failure,
        }
        write_new(output / "continuation-provenance.json", provenance)
    if failure:
        raise ValueError(failure)
    _assemble(
        root,
        plan_dir,
        plan,
        parent,
        output,
        install_root,
        requests,
        previous_count,
        rows,
        provenance,
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--parent-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--install-root",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TelescopeRag",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Continuation requires --execute after explicit user authorization.")
    asyncio.run(
        continue_run(
            Path.cwd().resolve(), args.plan, args.parent_run, args.output, args.install_root
        )
    )


if __name__ == "__main__":
    main()
