"""Continuation preserves the attempted prefix and sends only the unsent suffix."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx2 as httpx
import pytest

from scripts import continue_installed_evaluation as continuation
from scripts.natural_evaluation import REQUESTS, digest, requests_from, write_new


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    root = Path(__file__).parents[2]
    requests = requests_from(root / REQUESTS)
    plan_dir, parent = tmp_path / "plan", tmp_path / "parent"
    plan_dir.mkdir()
    parent.mkdir()
    plan = {
        "transport_kind": "installed_portable_http",
        "prepared_digest": "synthetic-digest",
        "snapshot_id": "synthetic-snapshot",
        "requests_sha256": digest(root / REQUESTS),
        "transport": "installed HTTP",
    }
    write_new(plan_dir / "plan.json", plan)
    before = {
        "status": "verified",
        "base_url": "http://127.0.0.1:8123",
        "internal_trace_available": False,
        "api_container_id": "owned-container",
    }
    http = {
        "status": "verified",
        "readiness_http_status": 200,
        "openapi_http_status": 200,
        "runtime_unchanged_before_first_question": True,
    }
    for name in continuation.RECEIPTS:
        write_new(parent / name, http if name == "http-preflight.json" else before)
    for request in requests[:19]:
        write_new(
            parent / f"{request['case_id']}.json",
            {"case_id": request["case_id"], "preserved": True},
        )
    write_new(
        parent / "execution-index.json",
        {
            "requested_cases": 50,
            "attempted_cases": 19,
            "status": "stopped",
            "retries": 0,
            "case_files": [f"{r['case_id']}.json" for r in requests[:19]],
            "not_attempted_case_ids": [r["case_id"] for r in requests[19:]],
        },
    )
    write_new(parent / "run-binding.json", {"execution_kind": "installed_portable_http"})
    events, posts = [], []
    monkeypatch.setattr(continuation, "verify_plan", lambda *_: plan)
    monkeypatch.setattr(continuation, "requests_from", lambda *_: requests)

    def score(_root, _plan, run, output, _review):
        events.append(f"score:{run.name}")
        output.mkdir()
        if run.name == "combined":
            index = json.loads((run / "execution-index.json").read_bytes())
            binding = json.loads((run / "run-binding.json").read_bytes())
            assert binding["index_sha256"] == digest(run / "execution-index.json")
            assert len(binding["case_sha256"]) == index["attempted_cases"]
            assert all(
                digest(run / name) == value for name, value in binding["case_sha256"].items()
            )

    def preflight(*_):
        events.append("preflight")
        return before.copy()

    async def verify_http(_client):
        events.append("get-only")
        return http.copy()

    monkeypatch.setattr(continuation, "score_run", score)
    monkeypatch.setattr(continuation.portable, "preflight", preflight)
    monkeypatch.setattr(continuation.portable, "verify_http", verify_http)

    def response(request):
        posts.append(json.loads(request.content))
        events.append("post")
        language = posts[-1]["language"]
        return httpx.Response(
            200,
            json={
                "schema_version": "local-mvp-response-v1",
                "mode": "local_mvp",
                "answer_style": "conversational",
                "request_id": str(uuid4()),
                "status": "not_found",
                "answer": "Unknown",
                "answer_format": "plain_text",
                "language": language,
                "questions": [
                    {
                        "id": "q1",
                        "question": "Question?",
                        "status": "unknown",
                        "answer": "Unknown",
                        "citation_ids": [],
                        "reason_code": None,
                        "admitted_scope_complete": None,
                        "hours": None,
                    }
                ],
                "citations": [],
                "unresolved_questions": ["q1"],
                "knowledge": None,
            },
        )

    def client(_base):
        events.append("client")
        return httpx.AsyncClient(
            base_url="http://127.0.0.1:8123",
            transport=httpx.MockTransport(response),
            trust_env=False,
            follow_redirects=False,
        )

    monkeypatch.setattr(continuation.portable, "_client", client)
    return SimpleNamespace(
        root=root,
        plan_dir=plan_dir,
        parent=parent,
        plan=plan,
        requests=requests,
        before=before,
        events=events,
        posts=posts,
        response=response,
        client=client,
        output=tmp_path / "continuation",
        install_root=tmp_path / "installed",
    )


def run(cohort):
    return asyncio.run(
        continuation.continue_run(
            cohort.root, cohort.plan_dir, cohort.parent, cohort.output, cohort.install_root
        )
    )


def test_only_31_unsent_cases_dispatched_and_original_bytes_preserved(cohort):
    original = {p.name: p.read_bytes() for p in cohort.parent.iterdir()}
    rows = run(cohort)
    assert len(rows) == len(cohort.posts) == 31
    assert [r["case_id"] for r in rows] == [r["case_id"] for r in cohort.requests[19:]]
    assert cohort.posts[0] == {
        "query": cohort.requests[19]["query"],
        "language": "en",
        "history": [],
    }
    assert (
        cohort.events.index("score:parent")
        < cohort.events.index("preflight")
        < cohort.events.index("client")
        < cohort.events.index("post")
    )
    assert {p.name: p.read_bytes() for p in cohort.parent.iterdir()} == original
    combined = cohort.output / "combined"
    assert all(
        (combined / name).read_bytes() == original[name]
        for name in original
        if name.startswith("U")
    )
    index = json.loads((combined / "execution-index.json").read_bytes())
    assert (
        index["attempted_cases"] == 50
        and index["not_attempted_case_ids"] == []
        and index["retries"] == 0
    )
    provenance = json.loads((cohort.output / "continuation-provenance.json").read_bytes())
    assert provenance["helper_sha256"] == digest(Path(continuation.__file__))
    assert (
        provenance["parent_attempted_cases"] == 19
        and len(provenance["continuation_cases_sha256"]) == 31
    )
    assert "two" in index["execution_description"].lower()


def test_case_failures_all_preserved_and_never_cause_repeat_or_skip(cohort, monkeypatch):
    def response(request):
        position = len(cohort.posts)
        if position < 4:
            cohort.posts.append(json.loads(request.content))
            if position == 0:
                return httpx.Response(502, json={"error": {"code": "offline_draft_failed"}})
            if position == 1:
                return httpx.Response(503, json={"error": {"code": "unavailable"}})
            if position == 2:
                raise httpx.ReadTimeout("synthetic-private-marker")
            return httpx.Response(200, json={"malformed": True})
        return cohort.response(request)

    monkeypatch.setattr(
        continuation.portable,
        "_client",
        lambda _: httpx.AsyncClient(
            base_url="http://127.0.0.1:8123",
            transport=httpx.MockTransport(response),
            trust_env=False,
        ),
    )
    rows = run(cohort)
    assert len(rows) == len(cohort.posts) == 31
    assert [r["http_status"] for r in rows[:4]] == [502, 503, None, 200]
    assert rows[2]["error"] == "ReadTimeout" and rows[3]["error"] == "invalid_local_mvp_response"
    assert "synthetic-private-marker" not in (
        cohort.output / f"{rows[2]['case_id']}.json"
    ).read_text("utf-8")


@pytest.mark.parametrize("change", ["kind", "status", "retries", "count"])
def test_invalid_parent_refused_without_any_client(cohort, change):
    path = cohort.parent / ("run-binding.json" if change == "kind" else "execution-index.json")
    value = json.loads(path.read_bytes())
    key, bad = {
        "kind": ("execution_kind", "live_local_mvp"),
        "status": ("status", "complete"),
        "retries": ("retries", 1),
        "count": ("requested_cases", 49),
    }[change]
    value[key] = bad
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="parent_is_not_stopped_full_cohort_prefix"):
        run(cohort)
    assert cohort.posts == [] and "client" not in cohort.events
    assert all((cohort.output / name).is_file() for name in continuation.RECEIPTS)


def test_offline_parent_validation_failure_precedes_docker_and_http(cohort, monkeypatch):
    def rejected(*_):
        raise ValueError("execution_case_hash_changed")

    monkeypatch.setattr(continuation, "score_run", rejected)
    with pytest.raises(ValueError, match="execution_case_hash_changed"):
        run(cohort)
    assert cohort.events == [] and cohort.posts == []
    assert (cohort.output / "execution-index.json").is_file()


def test_target_change_stops_suffix_and_preserves_already_attempted_case(cohort, monkeypatch):
    count = 0

    def preflight(*_):
        nonlocal count
        count += 1
        return {**cohort.before, **({"api_container_id": "changed"} if count >= 4 else {})}

    monkeypatch.setattr(continuation.portable, "preflight", preflight)
    with pytest.raises(ValueError, match="continuation_target_changed"):
        run(cohort)
    assert len(cohort.posts) == 1
    index = json.loads((cohort.output / "execution-index.json").read_bytes())
    assert index["attempted_cases"] == 1 and len(index["not_attempted_case_ids"]) == 30
    assert not (cohort.output / "combined").exists()


def test_existing_output_never_repeats_any_question(cohort):
    run(cohort)
    with pytest.raises(FileExistsError):
        run(cohort)
    assert len(cohort.posts) == 31


def test_cancellation_preserved_then_stops_without_sending_next_case(cohort, monkeypatch):
    def cancelled(request):
        cohort.posts.append(json.loads(request.content))
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        continuation.portable,
        "_client",
        lambda _: httpx.AsyncClient(
            base_url="http://127.0.0.1:8123",
            transport=httpx.MockTransport(cancelled),
            trust_env=False,
        ),
    )
    with pytest.raises(ValueError, match="continuation_cancelled"):
        run(cohort)
    assert len(cohort.posts) == 1
    index = json.loads((cohort.output / "execution-index.json").read_bytes())
    assert index["attempted_cases"] == 1 and len(index["not_attempted_case_ids"]) == 30
    row = json.loads((cohort.output / index["case_files"][0]).read_bytes())
    assert row["error"] == "CancelledError"


def test_changed_response_source_preserved_then_stops(cohort, monkeypatch):
    def wrong_source(*_, **__):
        raise ValueError("response_knowledge_source_mismatch")

    monkeypatch.setattr(continuation, "bind_record", wrong_source)
    with pytest.raises(ValueError, match="continuation_response_source_changed"):
        run(cohort)
    assert len(cohort.posts) == 1
    index = json.loads((cohort.output / "execution-index.json").read_bytes())
    row = json.loads((cohort.output / index["case_files"][0]).read_bytes())
    assert row["error"] == "response_knowledge_source_mismatch" and row["response"] is not None
