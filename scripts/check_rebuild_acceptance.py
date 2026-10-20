"""Check the rebuilt corpus against the accepted thresholds.

Every gate from the Phase 5 proposal is evaluated here against measured
artifacts, so the accept or reject decision is produced by one code path
rather than by reading numbers by hand.

Usage:
    python scripts/check_rebuild_acceptance.py \
        --baseline artifacts/m7-precision-v1/baseline-report.json \
        --rebuilt artifacts/m7-precision-v1/rebuilt-report.json \
        --baseline-verify artifacts/m7-precision-v1/verify-real-retriever.json \
        --rebuilt-verify artifacts/m7-precision-v1/verify-rebuilt.json \
        --execution artifacts/m7-candidate-execution-v2 \
        --admitted data/processed/m7-admitted-v1 \
        --published data/processed/m3-execution-approved-v6-v2
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from telescope_rag.ingestion.models import PreparedDocument  # noqa: E402

SHIPPED = "dense_fetch=5 dense_keep=5 lex=3 ctx=2 dedup=False lang_scope=False"
PHASE2 = "dense_fetch=20 dense_keep=8 lex=2 ctx=1 dedup=True lang_scope=True"
PUBLISHED_LINES = 1939
FACT_PAIRS = 52


def load_bundle(directory: pathlib.Path) -> list[PreparedDocument]:
    return [
        PreparedDocument.model_validate_json(p.read_bytes())
        for p in sorted(directory.glob("*.json"))
        if len(p.stem) == 64
    ]


def policy_row(report: dict[str, Any], policy: str) -> dict[str, Any]:
    for entry in report["policies"]:
        values = entry["policy"]
        signature = (
            f"dense_fetch={values['dense_fetch']} dense_keep={values['dense_keep']} "
            f"lex={values['lexical_keep']} ctx={values['context_keep']} "
            f"dedup={values['collapse_duplicates']} lang_scope={values['scope_language']}"
        )
        if signature == policy:
            return entry
    raise SystemExit(f"policy not present in the report: {policy}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=pathlib.Path, required=True)
    parser.add_argument("--rebuilt", type=pathlib.Path, required=True)
    parser.add_argument("--baseline-verify", type=pathlib.Path, required=True)
    parser.add_argument("--rebuilt-verify", type=pathlib.Path, required=True)
    parser.add_argument("--execution", type=pathlib.Path, required=True)
    parser.add_argument("--admitted", type=pathlib.Path, required=True)
    parser.add_argument("--published", type=pathlib.Path, required=True)
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    rebuilt = json.loads(args.rebuilt.read_text(encoding="utf-8"))
    base_verify = json.loads(args.baseline_verify.read_text(encoding="utf-8"))
    reb_verify = json.loads(args.rebuilt_verify.read_text(encoding="utf-8"))

    base_ship = policy_row(baseline, SHIPPED)
    base_phase2 = policy_row(baseline, PHASE2)
    reb_ship = policy_row(rebuilt, SHIPPED)
    reb_phase2 = policy_row(rebuilt, PHASE2)

    result = json.loads((args.execution / "result.json").read_text(encoding="utf-8"))
    verification = json.loads((args.execution / "verification.json").read_text(encoding="utf-8"))
    batches = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(args.execution.glob("batch-*.json"))
    ]
    attempts = [a for b in batches for a in b.get("attempts", [])]
    count_mismatches = [
        a
        for a in attempts
        if a.get("usage", {}).get("input_tokens") not in (None, a["input_reserved"])
    ]

    admitted = load_bundle(args.admitted)
    published = load_bundle(args.published)
    admitted_text = re.sub(
        r"\s+",
        " ",
        " ".join(c.retrieval_text + " " + c.original_text for d in admitted for c in d.chunks),
    )
    published_lines = set()
    for document in published:
        for chunk in document.chunks:
            for raw in chunk.original_text.split("\n"):
                line = re.sub(r"\s+", " ", raw).strip()
                if len(line) >= 12:
                    published_lines.add(line)
    lost = [line for line in published_lines if line not in admitted_text]

    gold = json.loads(
        (REPO / "tests/fixtures/evaluation/natural_questions_50_v1/facts-v1.json").read_text(
            encoding="utf-8"
        )
    )
    texts = {"en": [], "ar": []}
    for document in admitted:
        for chunk in document.chunks:
            texts[chunk.language].append(chunk.retrieval_text)
    pairs = 0
    for intent in gold["intents"]:
        for fact in intent["facts"]:
            for language in ("en", "ar"):
                variants = fact["variants"].get(language, [])
                if any(v in t for v in variants for t in texts[language]):
                    pairs += 1

    base_rows = {r["case_id"]: r for r in base_phase2["rows"]}
    reb_rows = {r["case_id"]: r for r in reb_phase2["rows"]}
    regressions = [
        case_id
        for case_id, row in reb_rows.items()
        if row["fact_recall"] is not None
        and base_rows[case_id]["fact_recall"] == 1.0
        and row["fact_recall"] == 0.0
    ]
    new_zero = [
        case_id
        for case_id, row in reb_rows.items()
        if row["fact_recall"] == 0.0 and base_rows[case_id]["fact_recall"] != 0.0
    ]

    gates = [
        (
            "A1 macro fact recall, phase-2 policy",
            reb_phase2["macro_fact_recall"] >= base_phase2["macro_fact_recall"],
            f"{reb_phase2['macro_fact_recall']:.4f} >= {base_phase2['macro_fact_recall']:.4f}",
        ),
        (
            "A2 macro fact recall, shipped policy",
            reb_ship["macro_fact_recall"] >= base_ship["macro_fact_recall"],
            f"{reb_ship['macro_fact_recall']:.4f} >= {base_ship['macro_fact_recall']:.4f}",
        ),
        (
            "A3 macro evidence precision, phase-2 policy",
            reb_phase2["macro_evidence_precision"] >= base_phase2["macro_evidence_precision"],
            f"{reb_phase2['macro_evidence_precision']:.4f} >= "
            f"{base_phase2['macro_evidence_precision']:.4f}",
        ),
        (
            "A4 full recall and zero recall",
            reb_phase2["questions_with_full_recall"] >= base_phase2["questions_with_full_recall"]
            and reb_phase2["questions_with_zero_recall"]
            <= base_phase2["questions_with_zero_recall"],
            f"full {reb_phase2['questions_with_full_recall']} >= "
            f"{base_phase2['questions_with_full_recall']}, zero "
            f"{reb_phase2['questions_with_zero_recall']} <= "
            f"{base_phase2['questions_with_zero_recall']}",
        ),
        (
            "A5 no full-recall question regressed to zero",
            not regressions and not new_zero,
            f"regressions={regressions} new_zero={new_zero}",
        ),
        (
            "A6 price abstain over-claim",
            reb_phase2["abstain_over_claim_questions"] == 0,
            f"{reb_phase2['abstain_over_claim_questions']} of {reb_phase2['abstain_questions']}",
        ),
        (
            "A7 fact pairs and published lines preserved",
            pairs == FACT_PAIRS and len(published_lines) == PUBLISHED_LINES and not lost,
            f"pairs {pairs}/{FACT_PAIRS}, lines {len(published_lines) - len(lost)}/"
            f"{len(published_lines)}, lost {len(lost)}",
        ),
        (
            "A8 duplicate slots",
            reb_phase2["mean_duplicate_slots"] <= base_phase2["mean_duplicate_slots"],
            f"{reb_phase2['mean_duplicate_slots']:.2f} <= "
            f"{base_phase2['mean_duplicate_slots']:.2f}",
        ),
        (
            "A9 embedding run integrity",
            result.get("status") == "candidate_verified_unpublished"
            and result.get("points") == 1332
            and result.get("unique_inputs") == 1212
            and result.get("active_alias_changed") is False
            and verification.get("aliases_unchanged") is True
            and not count_mismatches
            and all(a.get("status_code") == 200 for a in attempts)
            and attempts,
            f"status={result.get('status')} points={result.get('points')} "
            f"unique={result.get('unique_inputs')} attempts={len(attempts)} "
            f"non_200={sum(1 for a in attempts if a.get('status_code') != 200)} "
            f"count_mismatch={len(count_mismatches)} "
            f"aliases_unchanged={verification.get('aliases_unchanged')}",
        ),
        (
            "A10 real retriever agrees with the replay",
            abs(reb_verify["macro_fact_recall"] - reb_phase2["macro_fact_recall"]) <= 1e-9
            and abs(base_verify["macro_fact_recall"] - base_phase2["macro_fact_recall"]) <= 1e-9,
            f"verify rebuilt {reb_verify['macro_fact_recall']:.4f} vs replay "
            f"{reb_phase2['macro_fact_recall']:.4f}; baseline verify "
            f"{base_verify['macro_fact_recall']:.4f} vs {base_phase2['macro_fact_recall']:.4f}",
        ),
    ]

    print("=" * 100)
    print("REBUILD ACCEPTANCE GATES")
    passed = 0
    for name, ok, detail in gates:
        status = "PASS" if ok else "FAIL"
        passed += bool(ok)
        print(f"  [{status}] {name}")
        print(f"         {detail}")
    print("=" * 100)
    print(f"  {passed} of {len(gates)} gates passed")
    verdict = "ACCEPTED" if passed == len(gates) else "REJECTED"
    print(f"  VERDICT: {verdict}")
    if verdict == "REJECTED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
