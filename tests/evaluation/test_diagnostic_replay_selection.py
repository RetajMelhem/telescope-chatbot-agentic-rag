"""Paid diagnostic replays must stay within exact, immutable problem requests."""

import json
from pathlib import Path

import pytest

from scripts.diagnose_natural_cases import selected_cases
from scripts.natural_evaluation import REQUESTS, digest, write_new


def fixture(tmp_path):
    plan, baseline = tmp_path / "plan", tmp_path / "baseline"
    plan.mkdir()
    baseline.mkdir()
    (plan / "requests.jsonl").write_bytes((Path(__file__).parents[2] / REQUESTS).read_bytes())
    case = next(
        json.loads(line)
        for line in (plan / "requests.jsonl").read_text("utf-8").splitlines()
        if json.loads(line)["case_id"] == "U01-en"
    )
    write_new(baseline / "U01-en.json", {"case_id": case["case_id"]})
    case_hash = digest(baseline / "U01-en.json")
    write_new(baseline / "run-binding.json", {"case_sha256": {"U01-en.json": case_hash}})
    problems = {
        "baseline_binding_sha256": digest(baseline / "run-binding.json"),
        "cases": [{**case, "baseline_case_sha256": case_hash}],
    }
    write_new(baseline / "problem-cases.json", problems)
    return plan, baseline, problems, case


def test_selection_returns_request_only_and_never_gold(tmp_path):
    plan, baseline, _, case = fixture(tmp_path)
    assert selected_cases(plan, baseline) == [case]
    assert set(selected_cases(plan, baseline)[0]) == {"case_id", "query", "language", "history"}


@pytest.mark.parametrize("mutation", ["query", "duplicate", "binding"])
def test_diagnostic_cannot_repeat_or_change_a_sealed_problem_case(tmp_path, mutation):
    plan, baseline, problems, _ = fixture(tmp_path)
    if mutation == "query":
        problems["cases"][0]["query"] = "A different live request."
    elif mutation == "duplicate":
        problems["cases"].append(problems["cases"][0].copy())
    else:
        problems["baseline_binding_sha256"] = "changed"
    (baseline / "problem-cases.json").write_text(json.dumps(problems), encoding="utf-8")
    with pytest.raises(ValueError, match="diagnostic_"):
        selected_cases(plan, baseline)
