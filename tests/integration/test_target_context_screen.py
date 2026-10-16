"""Frozen fresh input contracts and semantic-review receipts; no language judge."""

import hashlib
import json
from types import SimpleNamespace

import pytest
from test_luna_planner_screen import preparation

from scripts import run_target_context_screen as fresh
from scripts.run_luna_planner_screen import development_packets
from telescope_rag.graph.contracts import WorkflowRequest


def fixture(root):
    directory = root / fresh.CASES
    directory.mkdir(parents=True)
    rows = [
        {
            "case_id": f"synthetic-{i:02}",
            "request": {
                "query": f"Synthetic original question {i}.",
                "history": [],
                "language": "en",
            },
            "review_criteria": "Synthetic expected meaning; never model input.",
            "source_witness_chunk_ids": ["synthetic-gold-never-input"],
        }
        for i in range(18)
    ]
    data = directory / "cases.json"
    data.write_text(json.dumps({"cases": rows}), encoding="utf-8")
    manifest = directory / "manifest.json"
    manifest.write_text(
        json.dumps({"files": {"cases.json": fresh.file_hash(data)}}), encoding="utf-8"
    )
    return directory, fresh.file_hash(manifest)


def test_frozen_cases_export_only_requests_and_no_gold(tmp_path, monkeypatch):
    _, digest = fixture(tmp_path)
    monkeypatch.setattr(fresh, "MANIFEST_SHA256", digest)
    cases = fresh.frozen_cases(tmp_path)
    bindings, _ = preparation("answer_targets")
    ids = tuple(c.case_id for c in cases)
    packets = development_packets(
        cases,
        bindings,
        profile="answer_targets",
        output_cap=4096,
        case_ids=ids,
        inventory=ids,
    )
    assert len(packets) == 18
    for case, packet in zip(cases, packets, strict=True):
        assert isinstance(case.request, WorkflowRequest)
        body = json.dumps(packet["payload"])
        assert "never model input" not in body and "synthetic-gold" not in body
        assert case.case_id not in body and "reasoning" not in packet["payload"]
        assert packet["payload"]["max_completion_tokens"] == 4096


@pytest.mark.parametrize("tamper", ["manifest", "cases"])
def test_tampered_fresh_evidence_refuses_before_any_credentials(tmp_path, monkeypatch, tamper):
    directory, digest = fixture(tmp_path)
    monkeypatch.setattr(fresh, "MANIFEST_SHA256", digest)
    (directory / f"{tamper}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh_manifest_changed|fresh_case_file_changed"):
        fresh.frozen_cases(tmp_path)


def development_review(root):
    capture = root / "synthetic-capture"
    capture.mkdir()
    code = {"src/synthetic.py": "synthetic-code-hash"}
    ids = [f"synthetic-{i}" for i in range(6)]
    (capture / "plan.json").write_text(
        json.dumps(
            {
                "profile": "answer_targets",
                "code_sha256": code,
                "case_ids": ids,
            }
        ),
        encoding="utf-8",
    )
    rows = []
    for identity in ids:
        data = b'{"schema_valid": true, "literal_bindings_valid": true}'
        (capture / f"{identity}.json").write_bytes(data)
        rows.append(
            {
                "case_id": identity,
                "semantic_admitted": True,
                "result_sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    review = {
        "actual_plans_reviewed": 6,
        "semantic_passes": 6,
        "profile": "answer_targets",
        "execution_directory": "synthetic-capture",
        "reviews": rows,
    }
    path = root / "review.json"
    return SimpleNamespace(capture=capture, code=code, review=review, path=path)


@pytest.mark.parametrize("tamper", [None, "count", "verdict", "code", "result", "inventory"])
def test_admission_gate_binds_manual_review_to_exact_candidate_outputs(tmp_path, tamper):
    v = development_review(tmp_path)
    if tamper == "count":
        v.review["semantic_passes"] = 4
    elif tamper == "verdict":
        v.review["reviews"][0]["semantic_admitted"] = False
    elif tamper == "code":
        v.code = {"different.py": "different"}
    elif tamper == "result":
        (v.capture / "synthetic-0.json").write_text("{}", encoding="utf-8")
    elif tamper == "inventory":
        v.review["reviews"][0]["case_id"] = "wrong"
    v.path.write_text(json.dumps(v.review), encoding="utf-8")
    if tamper:
        with pytest.raises(ValueError):
            fresh.require_development_acceptance(v.path, tmp_path, v.code)
    else:
        assert fresh.require_development_acceptance(v.path, tmp_path, v.code) == fresh.file_hash(
            v.path
        )
