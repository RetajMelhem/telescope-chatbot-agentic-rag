"""Explicit, bounded in-container diagnostic replay; never a baseline HTTP score.

The unchanged image constructs its ordinary container app in a separate process.
Public evaluation traces and chat response bodies are retained locally, without
headers, credential values or embedding vectors. The serving process is untouched.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path

from scripts.natural_evaluation import digest, requests_from, verify_plan, write_new
from scripts.natural_evaluation_portable import preflight

PROBE = r"""
import asyncio, json, sys, types
from pathlib import Path
import httpx2 as httpx
from telescope_rag.api.local import create_local_app

trace_module = types.ModuleType("diagnostic_trace")
sys.modules[trace_module.__name__] = trace_module
exec(compile(TRACE_SOURCE, "diagnostic_trace.py", "exec"), trace_module.__dict__)

class ChatAudit(httpx.AsyncBaseTransport):
    def __init__(self):
        self.inner = httpx.AsyncHTTPTransport(retries=0)
        self.rows = []
    async def handle_async_request(self, request):
        if request.url.host != "openrouter.ai" or request.method != "POST":
            raise ValueError("diagnostic_provider_target_invalid")
        response = await self.inner.handle_async_request(request)
        if request.url.path != "/api/v1/chat/completions":
            return response
        raw = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > 2000000:
                    raise ValueError("diagnostic_response_too_large")
                raw.extend(chunk)
            body = json.loads(raw)
            self.rows.append({"status_code":response.status_code,
                "response":{k:body[k] for k in
                    ("id","model","provider","usage","choices") if k in body}})
            return httpx.Response(response.status_code, content=bytes(raw),
                headers={"content-type":response.headers.get("content-type", "")})
        finally:
            await response.aclose()
    async def aclose(self):
        await self.inner.aclose()

async def run():
    audit = ChatAudit()
    app = create_local_app(Path("/runtime"), runtime="container", provider_transport=audit)
    capture = trace_module.install_capture(app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,
            raise_app_exceptions=False),base_url="http://127.0.0.1",timeout=155,
            follow_redirects=False,trust_env=False) as client:
            for case in CASES:
                capture.reset(case["case_id"])
                audit.rows = []
                payload = {"query":case["query"], "history":case["history"],
                    "language":"ar" if case["language"] == "ar-JO" else "en"}
                row={"case_id":case["case_id"],"request_payload":payload}
                try:
                    async with asyncio.timeout(155):
                        response=await client.post("/api/v1/chat",json=payload)
                    row.update(http_status=response.status_code,response=response.json())
                except Exception as error:
                    row.update(http_status=None,error_type=type(error).__name__)
                row.update(trace=capture.snapshot(),provider_chat_responses=audit.rows)
                print("EVALUATION_CASE_JSON="+json.dumps(row,ensure_ascii=True),flush=True)
asyncio.run(run())
"""


def selected_cases(plan_dir: Path, baseline: Path) -> list[dict]:
    approved = {r["case_id"]: r for r in requests_from(plan_dir / "requests.jsonl")}
    problems = json.loads((baseline / "problem-cases.json").read_bytes())
    binding = json.loads((baseline / "run-binding.json").read_bytes())
    if problems["baseline_binding_sha256"] != digest(baseline / "run-binding.json"):
        raise ValueError("diagnostic_baseline_binding_changed")
    selected = []
    for problem in problems["cases"]:
        case = approved[problem["case_id"]]
        name = f"{case['case_id']}.json"
        if (
            digest(baseline / name) != problem["baseline_case_sha256"]
            or binding["case_sha256"][name] != problem["baseline_case_sha256"]
            or problem["query"] != case["query"]
            or problem["language"] != case["language"]
        ):
            raise ValueError("diagnostic_problem_case_changed")
        selected.append(case)
    if not 1 <= len(selected) <= 7 or len({r["case_id"] for r in selected}) != len(selected):
        raise ValueError("diagnostic_case_limit_invalid")
    return selected


def run(
    root: Path,
    plan_dir: Path,
    baseline: Path,
    install_root: Path,
    output: Path,
    case_ids: list[str] | None = None,
) -> None:
    plan = verify_plan(root, plan_dir)
    cases = selected_cases(plan_dir, baseline)
    if case_ids is not None:
        if len(set(case_ids)) != len(case_ids) or not set(case_ids) <= {
            r["case_id"] for r in cases
        }:
            raise ValueError("diagnostic_case_selection_invalid")
        cases = [r for r in cases if r["case_id"] in case_ids]
    before = preflight(plan, install_root)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "preflight-before.json", before)
    trace_source = (root / "scripts/natural_evaluation_trace.py").read_text("utf-8")
    payload = (
        f"TRACE_SOURCE={json.dumps(trace_source)}\n"
        f"CASES={json.dumps(cases, ensure_ascii=True)}\n" + PROBE
    )
    # This is Python source on stdin, never a shell-built command or credential.
    process = subprocess.Popen(
        ["docker", "exec", "-i", before["api_container_id"], "python", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(payload)
    process.stdin.close()
    saved = []
    for line in process.stdout:
        if not line.startswith("EVALUATION_CASE_JSON="):
            continue
        record = json.loads(line.partition("=")[2])
        expected = cases[len(saved)]
        if record["case_id"] != expected["case_id"]:
            process.terminate()
            raise ValueError("diagnostic_case_order_invalid")
        write_new(output / f"{record['case_id']}.json", record)
        saved.append(record["case_id"])
        print(
            json.dumps({"case_id": record["case_id"], "http_status": record["http_status"]}),
            flush=True,
        )
    code = process.wait(timeout=30)
    after = preflight(plan, install_root)
    write_new(output / "preflight-after.json", after)
    write_new(
        output / "diagnostic-index.json",
        {
            "mode": "in_container_diagnostic_asgi",
            "same_image_application_source": True,
            "baseline_http_run_modified": False,
            "requested_cases": [r["case_id"] for r in cases],
            "saved_cases": saved,
            "process_exit_code": code,
            "runtime_unchanged": before == after,
            "diagnostic_script_sha256": digest(Path(__file__)),
            "trace_helper_sha256": digest(root / "scripts/natural_evaluation_trace.py"),
            "plan_sha256": digest(plan_dir / "plan.json"),
            "baseline_binding_sha256": digest(baseline / "run-binding.json"),
        },
    )
    if code != 0 or len(saved) != len(cases) or before != after:
        raise ValueError("diagnostic_run_incomplete_or_runtime_changed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--install-root", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "TelescopeRag"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--case-ids", nargs="+")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Diagnostic replay requires --execute and authorized provider calls.")
    run(Path.cwd(), args.plan, args.baseline, args.install_root, args.output, args.case_ids)


if __name__ == "__main__":
    main()
