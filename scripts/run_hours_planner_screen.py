"""Freeze and explicitly execute at most twelve opt-in hours planner requests.

The actual graph planning/validation nodes run, then stop. No retrieval, answer,
embedding, index operation or automatic repair is possible through this runner.
Expected decisions stay outside model payloads; semantic review is separate.
"""

import argparse
import asyncio
import json
import subprocess
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field

from scripts.retrieval_benchmark import load_corpus
from scripts.run_luna_planner_screen import file_hash, payload_hash, screen_settings, write_new
from telescope_rag.core.settings import Settings, load_settings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.graph.hours_inputs import HoursPlannerReply
from telescope_rag.graph.hours_workflow import HoursRagWorkflow
from telescope_rag.graph.workflow import WorkflowError, _RunContext
from telescope_rag.ingestion.admission import AdmissionPlan
from telescope_rag.knowledge.hours import PublicHoursPlan
from telescope_rag.knowledge.source_authority import reviewed_directory_authority
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import ChatMessage, ChatProvider
from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.providers.validation import output_schema
from telescope_rag.retrieval.assembly import EvidenceCatalog

SOURCE = Path("data/processed/m3-llm-semantic-token-validated-v6")
SOURCE_HASHES = Path("artifacts/m3-retrieval-benchmark-v1/authoring/source-input-hashes.json")
HOURS_PLAN = Path("artifacts/m5-public-hours-v1/reviewed-hours-plan.json")
DIGEST = "a46be2d3fd18f11d46c79ff9bc992de22aab496836894a708bc57c1e8b48af88"
HOURS_DIGEST = "609a93a48f86b802c3ab2356a128fbc3b8736079dfd241b5ffa1572f1a5e59f7"
OUTPUT_CAP = 4096  # Explicit one-call screen capacity, not a serving setting change.


class ScreenCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    case_id: str = Field(pattern=r"^H[0-9]{2}-(en|ar|ar-JO)$")
    request: WorkflowRequest
    expected_decisions: tuple[str, ...] = Field(min_length=1, max_length=12)


class ScreenCases(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    cases: tuple[ScreenCase, ...] = Field(min_length=1, max_length=12)


class _NoDownstream:
    verified = False
    version = "planner-screen-no-assembly"

    def count(self, text: str) -> int:
        raise AssertionError("planner_screen_must_not_assemble")

    async def retrieve(self, *args, **kwargs):
        raise AssertionError("planner_screen_must_not_retrieve")


def wire_payload(messages: tuple[ChatMessage, ...], settings: Settings) -> dict:
    return {
        "model": settings.openrouter_chat_model,
        "messages": [m.model_dump() for m in messages],
        "response_format": {"type": "json_schema", "json_schema": output_schema(HoursPlannerReply)},
        "max_completion_tokens": OUTPUT_CAP,
        "stream": False,
        "provider": {"require_parameters": True, "allow_fallbacks": False},
    }


class _Captured(Exception):
    pass


class _CaptureChat:
    messages: tuple[ChatMessage, ...] | None = None

    async def complete(self, messages, output_model, *, max_output_tokens, budget):
        if output_model is not HoursPlannerReply or max_output_tokens != OUTPUT_CAP:
            raise ValueError("hours_screen_contract_changed")
        self.messages = tuple(messages)
        raise _Captured


class _ExactChat:
    def __init__(self, delegate: ChatProvider, packet: dict, settings: Settings):
        self.delegate, self.packet, self.settings = delegate, packet, settings
        self.used = False

    async def complete(self, messages, output_model, *, max_output_tokens, budget):
        actual = wire_payload(tuple(messages), self.settings)
        if (
            self.used
            or output_model is not HoursPlannerReply
            or max_output_tokens != OUTPUT_CAP
            or actual != self.packet["payload"]
            or payload_hash(actual) != self.packet["payload_sha256"]
        ):
            raise ValueError("hours_screen_payload_changed")
        self.used = True
        return await self.delegate.complete(
            messages, output_model, max_output_tokens=max_output_tokens, budget=budget
        )


def build_workflow(
    root: Path,
    config: Settings,
    chat: ChatProvider,
    clock: datetime,
    hours_profile: Literal["v12", "identity_links_v13"] = "v12",
) -> HoursRagWorkflow:
    documents, _ = load_corpus(root / SOURCE)
    catalog = EvidenceCatalog(documents, expected_digest=DIGEST)
    authority = reviewed_directory_authority(
        AdmissionPlan.model_validate_json(
            (root / SOURCE / "metadata/source-admission-plan.json").read_bytes()
        ),
        json.loads((root / SOURCE / "metadata/primary-directory.json").read_bytes()),
        prepared_digest=DIGEST,
    )
    return HoursRagWorkflow(
        settings=config,
        chat=chat,
        retriever=_NoDownstream(),
        catalog=catalog,
        counter=_NoDownstream(),
        directory_authority=authority,
        hours_plan=PublicHoursPlan.model_validate_json((root / HOURS_PLAN).read_bytes()),
        expected_hours_plan_digest=HOURS_DIGEST,
        planner_output_tokens=OUTPUT_CAP,
        clock=lambda: clock,
        hours_profile=hours_profile,
    )


def source_bindings(root: Path) -> dict[str, str]:
    sources = json.loads((root / SOURCE_HASHES).read_bytes())
    if len(sources) != 122 or any(file_hash(root / p) != h for p, h in sources.items()):
        raise ValueError("hours_screen_source_changed")
    return sources | {HOURS_PLAN.as_posix(): file_hash(root / HOURS_PLAN)}


def code_bindings(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): file_hash(p)
        for parent in ("src", "scripts")
        for p in (root / parent).rglob("*.py")
        if "__pycache__" not in p.parts
    }


async def freeze_plan(
    root: Path,
    cases_path: Path,
    clock: datetime,
    hours_profile: Literal["v12", "identity_links_v13"] = "v12",
) -> dict:
    if clock.utcoffset() is None:
        raise ValueError("hours_screen_clock_invalid")
    cohort = ScreenCases.model_validate_json(await asyncio.to_thread(cases_path.read_bytes))
    if len({c.case_id for c in cohort.cases}) != len(cohort.cases):
        raise ValueError("hours_screen_duplicate_case")
    config = screen_settings(profile="local_constraints", output_cap=OUTPUT_CAP)
    capture = _CaptureChat()
    workflow = build_workflow(root, config, capture, clock, hours_profile)
    packets = []
    for case in cohort.cases:
        context = _RunContext(uuid5(NAMESPACE_URL, case.case_id).hex, ExecutionBudget(config))
        capture.messages = None
        await workflow._validate_request({"request": case.request}, Runtime(context=context))
        try:
            await workflow._plan_query({"request": case.request}, Runtime(context=context))
        except _Captured:
            pass
        if capture.messages is None:
            raise ValueError("hours_screen_capture_failed")
        payload = wire_payload(capture.messages, config)
        packets.append(
            {
                "case_id": case.case_id,
                "request": case.request.model_dump(mode="json"),
                "payload": payload,
                "payload_sha256": payload_hash(payload),
                "expected_decisions": list(case.expected_decisions),
            }
        )
    return {
        "version": "hours-planner-screen-v1",
        **({"hours_profile": hours_profile} if hours_profile != "v12" else {}),
        "clock_utc": clock.astimezone(UTC).isoformat(),
        "clock_basis": "frozen application clock for this development screen",
        "packets": packets,
        "cases_sha256": file_hash(cases_path),
        "source_sha256": source_bindings(root),
        "code_sha256": code_bindings(root),
        "output_cap_per_call": OUTPUT_CAP,
        "reasoning_control": None,
        "max_attempts": len(packets),
        "automatic_retries": 0,
        "screen_deadline_seconds": 30 * len(packets) + 30,
        "semantic_review": "pending actual outputs; no automated semantic verdict",
        "production_adoption": False,
    }


async def run_packet(packet: dict, workflow: HoursRagWorkflow, config: Settings) -> dict:
    request = WorkflowRequest.model_validate_json(json.dumps(packet["request"]))
    context = _RunContext(uuid5(NAMESPACE_URL, packet["case_id"]).hex, ExecutionBudget(config))
    runtime = Runtime(context=context)
    row = {
        "case_id": packet["case_id"],
        "payload_sha256": packet["payload_sha256"],
        "proposal": None,
        "schema_valid": False,
        "literal_bindings_valid": False,
        "error_code": None,
        "semantic_review": "pending",
        "fatal": False,
    }
    started = time.monotonic()
    try:
        async with asyncio.timeout(context.budget.remaining_seconds()):
            await workflow._validate_request({"request": request}, runtime)
            result = await workflow._plan_query({"request": request}, runtime)
            row["proposal"] = result["proposal"].model_dump(mode="json")
            row["schema_valid"] = True
            validated = await workflow._validate_plan({"request": request, **result}, runtime)
            row["literal_bindings_valid"] = True
            row["assembly_request"] = validated["plan"].assembly_request.model_dump(mode="json")
            row["operations"] = validated["plan"].operations
            row["request_anchors"] = [asdict(a) for a in context.request_anchors]
            row["answer_targets"] = [asdict(a) for a in context.answer_targets]
            row["computed_hours"] = [
                {
                    "part_id": r.part_id,
                    "input": r.supplied.model_dump(mode="json"),
                    "query": r.query.model_dump(mode="json"),
                    "field_bindings": [asdict(b) for b in r.field_bindings],
                    "assessment": r.assessment.model_dump(mode="json"),
                }
                for r in context.computed_hours
            ]
    except ProviderError as error:
        row["error_code"] = error.code
        row["fatal"] = error.status_code in {400, 401, 402, 403, 404} or error.code in {
            "reported_model_mismatch",
            "missing_reported_model",
            "missing_provider_credentials",
        }
    except WorkflowError as error:
        row["error_code"] = str(error)
    except TimeoutError:
        row["error_code"] = "deadline_exceeded"
    except Exception:
        row["error_code"] = "hours_screen_validation_failed"
        row["fatal"] = True
    row.update(
        elapsed_seconds=time.monotonic() - started,
        stages=context.stages,
        physical_attempts=context.budget.attempts["chat"],
        logical_chat_calls=context.budget.operations["chat"],
        reported_input_tokens=context.budget.input_charged["chat"],
        charged_output_tokens=context.budget.output_charged,
        receipts=[{**asdict(r), "usage": r.usage.model_dump()} for r in context.budget.receipts],
    )
    return row


async def execute(root: Path, output: Path, cases: Path) -> dict:
    plan = json.loads((output / "plan.json").read_bytes())
    clock = datetime.fromisoformat(plan["clock_utc"])
    profile = plan.get("hours_profile", "v12")
    rebuilt = await freeze_plan(root, cases, clock, profile)
    status = await asyncio.to_thread(
        subprocess.check_output, ["git", "status", "--porcelain"], cwd=root
    )
    if rebuilt != plan or status.strip():
        raise ValueError("hours_screen_plan_or_checkout_changed")
    write_new(
        output / "started.json",
        {
            "at_utc": datetime.now(UTC).isoformat(),
            "max_requests": plan["max_attempts"],
            "plan_sha256": file_hash(output / "plan.json"),
            "commit": (
                await asyncio.to_thread(
                    subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=root, text=True
                )
            ).strip(),
            "authorization": (
                "User requested starting the documented bounded hours-planner next step; "
                "this exact frozen profile/cohort is a development screen without adoption."
            ),
        },
    )
    before = file_hash(root / ".env")
    config = screen_settings(
        key=load_settings(root / ".env").openrouter_api_key.get_secret_value(),
        profile="local_constraints",
        output_cap=OUTPUT_CAP,
    )
    rows = []
    try:
        async with asyncio.timeout(plan["screen_deadline_seconds"]):
            async with OpenRouterProviders(config) as providers:
                for packet in plan["packets"]:
                    workflow = build_workflow(
                        root, config, _ExactChat(providers.chat, packet, config), clock, profile
                    )
                    row = await run_packet(packet, workflow, config)
                    write_new(output / (packet["case_id"] + ".json"), row)
                    rows.append(row)
                    print(
                        json.dumps(
                            {
                                k: row[k]
                                for k in (
                                    "case_id",
                                    "schema_valid",
                                    "literal_bindings_valid",
                                    "error_code",
                                    "physical_attempts",
                                )
                            }
                        ),
                        flush=True,
                    )
                    if row["fatal"]:
                        break
        summary = {
            "cases_planned": len(plan["packets"]),
            "cases_attempted": len(rows),
            "physical_attempts": sum(r["physical_attempts"] for r in rows),
            "schema_valid": sum(r["schema_valid"] for r in rows),
            "literal_bindings_valid": sum(r["literal_bindings_valid"] for r in rows),
            "actual_semantic_reviews": 0,
            "model_acceptance": False,
            "retrieval_answer_embedding_qdrant_requests": 0,
            "automatic_retries": 0,
        }
        write_new(output / "summary.json", summary)
        return summary
    finally:
        write_new(
            output / "finished.json",
            {
                "at_utc": datetime.now(UTC).isoformat(),
                "dotenv_unchanged": file_hash(root / ".env") == before,
                "cases_recorded": len(rows),
                "no_automatic_resume": True,
            },
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--hours-profile", choices=("v12", "identity_links_v13"), default="v12")
    args = parser.parse_args()
    if args.execute:
        print(json.dumps(await execute(Path.cwd(), args.output, args.cases)))
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        plan = await freeze_plan(Path.cwd(), args.cases, datetime.now(UTC), args.hours_profile)
        write_new(args.output / "plan.json", plan)
        print(json.dumps({"prepared_requests": len(plan["packets"]), "paid_requests": 0}))


if __name__ == "__main__":
    asyncio.run(main())
