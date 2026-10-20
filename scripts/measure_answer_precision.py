"""Measure answer-level precision and the evidence funnel for a running build.

For each approved question the scorer records the HTTP outcome, the answer
text and every citation, then reports three stages:

  corpus     the admitted corpus publishes a chunk carrying the required fact
  cited      the answer's own citations carry a chunk with that fact
  stated     the answer text itself carries the fact

A loss between corpus and cited is a selection loss: the evidence existed and
the answer did not use it. A loss between cited and stated is a writing loss:
the evidence was in front of the writer and the answer did not say it.

The scorer only reads a running service. It never writes to the corpus, the
collection or the installation.

Usage:
    python scripts/measure_answer_precision.py \
        --base-url http://127.0.0.1:8000 \
        --label v0.2.0 \
        --output artifacts/m7-precision-v2/answer-v0.2.0.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
REQUESTS = Path("tests/fixtures/evaluation/natural_questions_50_v1/requests.jsonl")
FACTS = Path("tests/fixtures/evaluation/natural_questions_50_v1/facts-v1.json")

# The reduced, budget-bounded cohort. It keeps both regressions, both roster
# weaknesses, the hours and contact paths, and the price abstention case.
DEFAULT_INTENTS = (
    "U01",
    "U08",
    "U11",
    "U12",
    "U14",
    "U15",
    "U16",
    "U18",
    "U19",
    "U25",
)


def load_questions(intents: tuple[str, ...]) -> list[dict]:
    rows = [
        json.loads(line)
        for line in (REPO / REQUESTS).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = [r for r in rows if r["case_id"].split("-")[0] in intents]
    if not selected:
        raise SystemExit("no questions selected")
    return selected


def load_facts() -> dict[str, dict]:
    gold = json.loads((REPO / FACTS).read_text(encoding="utf-8"))
    return {intent["intent_id"]: intent for intent in gold["intents"]}


def load_corpus(bundle: Path) -> dict[str, dict]:
    from telescope_rag.ingestion.models import PreparedDocument

    corpus: dict[str, dict] = {}
    for path in sorted(bundle.glob("*.json")):
        if len(path.stem) != 64:
            continue
        document = PreparedDocument.model_validate_json(path.read_bytes())
        for chunk in document.chunks:
            corpus[chunk.chunk_id] = {
                "canonical_url": chunk.canonical_url,
                "retrieval_text": chunk.retrieval_text,
                "language": chunk.language,
            }
    if not corpus:
        raise SystemExit("corpus bundle produced no chunks")
    return corpus


def ask(base_url: str, query: str, language: str) -> dict[str, Any]:
    payload = json.dumps({"query": query, "language": language, "history": []}).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/chat",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return {
                "status": response.status,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "body": json.load(response),
            }
    except urllib.error.HTTPError as error:
        return {
            "status": error.code,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "body": None,
        }
    except Exception as error:
        return {
            "status": None,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "body": None,
            "error": type(error).__name__,
        }


def fact_presence(variants: list[str], texts: list[str]) -> tuple[bool, list[str]]:
    """Whether a fact's literal wording appears in any of the texts.

    The comparison is case-insensitive. A published heading and the sentence a
    writer derives from it differ in capitalisation, and a fact that is present
    must not be reported as missing because of that.
    """
    lowered = [text.casefold() for text in texts]
    present = [v for v in variants if any(v.casefold() in text for text in lowered)]
    return bool(present), present


_FUNCTION_WORDS = {
    "the",
    "and",
    "for",
    "from",
    "with",
    "that",
    "this",
    "are",
    "was",
    "our",
    "you",
    "your",
    "not",
    "but",
    "can",
    "may",
    "most",
    "take",
    "takes",
    "between",
    "until",
    "every",
    "each",
    "about",
    "into",
    "than",
    "then",
    "they",
    "them",
    "open",
    "daily",
    "accept",
    "credit",
    "cards",
    "payments",
}


def _tokens(text: str) -> list[str]:
    """Word tokens. ``\\w`` is Unicode aware and already covers Arabic letters.

    An explicit Arabic code-point range would also capture Arabic punctuation
    such as the comma, which would make a number and its terminator one token.
    """
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).casefold(), flags=re.UNICODE)


# Arabic clitics that a writer may add to or drop from a word.
_ARABIC_CLITICS = ("و", "ب", "ف", "ك", "ل")


def _variants(token: str) -> set[str]:
    """The token and its clitic-stripped forms."""
    forms = {token}
    if len(token) > 4 and token[0] in _ARABIC_CLITICS:
        forms.add(token[1:])
    return forms


# Vocabulary the clinic uses in nearly every sentence, and the boilerplate the
# prompt itself introduces. Counting it would make every citation look precise.
BOILERPLATE_TERMS = {
    "telescope",
    "center",
    "centre",
    "clinic",
    "medical",
    "our",
    "we",
    "you",
    "patient",
    "patients",
    "doctor",
    "doctors",
    "information",
    "published",
    "website",
    "source",
    "sources",
    "according",
    "regarding",
    "about",
    "have",
    "has",
    "can",
    "will",
    "from",
    "with",
    "that",
    "this",
    "they",
    "them",
    "their",
    "there",
    "which",
    "when",
    "what",
    "where",
    "how",
    "why",
    "who",
    "بالمركز",
    "المركز",
    "معلوماتي",
    "المعلومات",
    "اللي",
    "عننا",
    "نقدّم",
    "department",
    "service",
    "services",
    "treatment",
    "treatments",
    "page",
    "pages",
    "contact",
    "booking",
    "consultation",
    "free",
}


def distinctive_terms(text: str) -> list[str]:
    """Terms that carry a specific claim rather than clinic vocabulary."""
    return [token for token in _tokens(text) if len(token) >= 5 and token not in BOILERPLATE_TERMS]


def numeric_tokens(text: str) -> list[str]:
    """Numbers as they are written, so a clock time stays one number."""
    return re.findall(r"\d+(?::\d+)?", unicodedata.normalize("NFC", text))


def citation_precision(
    answer: str, cited_texts: list[str], vocabulary: set[str] | None = None
) -> dict[str, Any]:
    """How much of the answer's own specific claims the cited evidence carries.

    An answer can be correct and still cite the wrong chunk: when a page
    publishes the same topic in several places, the writer may attach the
    sentence to a neighbouring chunk that does not contain the claim. This
    measures the share of the answer's terms and numbers that the cited
    evidence actually contains.

    Only terms the clinic itself publishes are scored. A connective such as
    "reach" or "offer" is the writer's own prose, not a claim, and counting it
    would make every citation look imprecise.
    """
    terms = distinctive_terms(answer)
    numbers = numeric_tokens(answer)
    if vocabulary is not None:
        terms = [term for term in terms if term in vocabulary]
    evidence = " ".join(cited_texts).casefold()
    evidence_tokens = set(_tokens(" ".join(cited_texts)))
    evidence_forms = set()
    for token in evidence_tokens:
        evidence_forms |= _variants(token)
    covered_terms = []
    for token in terms:
        forms = _variants(token)
        if forms & evidence_forms or any(
            candidate.startswith(form[: max(4, len(form) - 2)])
            for form in forms
            for candidate in evidence_tokens
        ):
            covered_terms.append(token)
    covered_numbers = [n for n in numbers if n in evidence]
    return {
        "answer_terms": len(terms),
        "answer_terms_covered": len(covered_terms),
        "term_coverage": (len(covered_terms) / len(terms)) if terms else None,
        "answer_numbers": len(numbers),
        "answer_numbers_covered": len(covered_numbers),
        "number_coverage": (len(covered_numbers) / len(numbers)) if numbers else None,
        "uncovered_terms": sorted(set(terms) - set(covered_terms))[:12],
        "uncovered_numbers": sorted(set(numbers) - set(covered_numbers))[:12],
    }


# A time written in words is the same time written in digits.
_TIME_WORDS = {"12:00": ("midnight", "noon"), "00:00": ("midnight", "noon")}


def _number_covered(number: str, answer: str) -> bool:
    if number in answer:
        return True
    for word in _TIME_WORDS.get(number, ()):
        if word in answer:
            return True
    return False


def loosely_stated(variant: str, answer: str) -> bool:
    """Whether a paraphrase of the fact is present in the answer.

    A paraphrase keeps the numbers and the distinctive words but not the exact
    wording, so a literal comparison understates what the answer delivered.
    """
    wanted = [t for t in _tokens(variant) if len(t) >= 4 and t not in _FUNCTION_WORDS]
    numbers = numeric_tokens(variant)
    if numbers and not all(_number_covered(n, answer) for n in numbers):
        return False
    if not wanted:
        return False
    answer_tokens = _tokens(answer)
    answer_forms = set()
    for token in answer_tokens:
        answer_forms |= _variants(token)
    hits = 0
    for token in wanted:
        forms = _variants(token)
        if forms & answer_forms or any(
            candidate.startswith(form[: max(4, len(form) - 2)])
            for form in forms
            for candidate in answer_tokens
        ):
            hits += 1
    return hits / len(wanted) >= 0.6


def _mean_of(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return statistics.mean(present) if present else None


def remaining_credit() -> float | None:
    """The remaining key allowance, read without spending anything."""
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            key = line.split("=", 1)[1].strip()
            break
    else:
        return None
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)["data"]
    except Exception:
        return None
    budget = data.get("effective_budget") or {}
    remaining = budget.get("remaining_usd")
    return float(remaining) if isinstance(remaining, (int, float)) else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--corpus", type=Path, default=REPO / "data/processed/m3-execution-approved-v6-v2"
    )
    parser.add_argument("--intents", default=",".join(DEFAULT_INTENTS))
    parser.add_argument(
        "--max-spend",
        type=float,
        default=0.05,
        help=(
            "Refuse to run when the remaining key allowance would not cover this "
            "sweep. The estimate is the number of questions times the measured "
            "cost of one request."
        ),
    )
    parser.add_argument(
        "--request-cost",
        type=float,
        default=0.0045,
        help="The measured cost of one chat request, used for the allowance check.",
    )
    parser.add_argument(
        "--allow-negative-credit",
        action="store_true",
        help="Run even when the key allowance is already exhausted.",
    )
    args = parser.parse_args()

    intents = tuple(i.strip() for i in args.intents.split(",") if i.strip())
    questions = load_questions(intents)
    estimated = len(questions) * args.request_cost
    remaining = remaining_credit()
    if remaining is not None and not args.allow_negative_credit:
        if remaining <= 0:
            raise SystemExit(
                f"key allowance is exhausted ({remaining:.6f} remaining); no request was sent"
            )
        if remaining < estimated:
            raise SystemExit(
                f"refusing to spend {estimated:.4f} with {remaining:.6f} remaining; "
                "no request was sent"
            )
    print(
        f"credit check: remaining={remaining} estimated_spend={estimated:.4f} "
        f"questions={len(questions)}"
    )

    facts = load_facts()
    corpus = load_corpus(args.corpus)
    vocabulary = {token for entry in corpus.values() for token in _tokens(entry["retrieval_text"])}
    rows: list[dict[str, Any]] = []
    for question in questions:
        case_id = question["case_id"]
        intent = facts[case_id.split("-")[0]]
        language = "en" if question["language"] == "en" else "ar"
        result = ask(args.base_url, question["query"], language)
        row: dict[str, Any] = {
            "case_id": case_id,
            "intent_id": intent["intent_id"],
            "language": language,
            "query": question["query"],
            "status": result["status"],
            "elapsed_seconds": result["elapsed_seconds"],
        }
        body = result["body"]
        if body is None:
            row.update({"failed": True, "error": result.get("error")})
            rows.append(row)
            print(f"  {case_id}: FAILED status={result['status']} {result.get('error', '')}")
            continue
        answer = body.get("answer") or ""
        citations = body.get("citations") or []
        row["failed"] = False
        row["answer_status"] = body.get("status")
        row["answer"] = answer
        row["citation_count"] = len(citations)
        row["citation_pages"] = sorted(
            {c.get("url", "").replace("https://telescopecenter.com", "") or "/" for c in citations}
        )
        invalid = [
            c.get("chunk_id")
            for c in citations
            if c.get("chunk_id") not in corpus
            or corpus.get(c.get("chunk_id"), {}).get("canonical_url") != c.get("url")
        ]
        row["invalid_citations"] = invalid
        cited_texts = [
            corpus[c["chunk_id"]]["retrieval_text"]
            for c in citations
            if c.get("chunk_id") in corpus
        ]
        facts_detail = []
        cited_ok = 0
        stated_ok = 0
        loose_ok = 0
        corpus_ok = 0
        total = 0
        for fact in intent["facts"]:
            variants = fact["variants"].get(language, [])
            minimum = fact.get("minimum_variants", 1)
            total += 1
            in_corpus, corpus_present = fact_presence(
                variants, [c["retrieval_text"] for c in corpus.values()]
            )
            in_cited, cited_present = fact_presence(variants, cited_texts)
            in_stated, stated_present = fact_presence(variants, [answer])
            in_loose = any(loosely_stated(v, answer) for v in variants)
            corpus_ok += int(in_corpus)
            cited_ok += int(in_cited)
            stated_ok += int(in_stated)
            loose_ok += int(in_loose)
            facts_detail.append(
                {
                    "fact_id": fact["fact_id"],
                    "minimum_variants": minimum,
                    "in_corpus": in_corpus,
                    "in_citations": in_cited,
                    "in_answer": in_stated,
                    "in_answer_paraphrase": in_loose,
                    "corpus_variants": len(corpus_present),
                    "cited_variants": len(cited_present),
                    "stated_variants": len(stated_present),
                }
            )
        if intent["outcome"] == "abstain":
            row["abstain_expected"] = True
            row["abstain_violation"] = bool(row["citation_count"]) or any(
                p in answer for p in ("$", "JOD", "JD", "دينار", "د.أ")
            )
        else:
            row["facts"] = facts_detail
            row["corpus_coverage"] = corpus_ok / total if total else None
            row["cited_coverage"] = cited_ok / total if total else None
            row["stated_coverage"] = stated_ok / total if total else None
            row["stated_paraphrase_coverage"] = loose_ok / total if total else None
            row["citation_precision"] = citation_precision(answer, cited_texts, vocabulary)
        rows.append(row)
        marker = (
            "FAIL"
            if row["failed"]
            else (f"cited={row.get('cited_coverage')} stated={row.get('stated_coverage')}")
        )
        print(f"  {case_id}: status={row['status']} {row['elapsed_seconds']}s {marker}")

    scored = [r for r in rows if not r["failed"]]
    supported = [r for r in scored if r.get("cited_coverage") is not None]
    summary = {
        "schema_version": "answer-precision-report-v1",
        "label": args.label,
        "base_url": args.base_url,
        "questions": len(rows),
        "failures": sum(1 for r in rows if r["failed"]),
        "failure_rate": sum(1 for r in rows if r["failed"]) / len(rows) if rows else None,
        "status_counts": {
            str(status): sum(1 for r in rows if r["status"] == status)
            for status in sorted({r["status"] for r in rows}, key=str)
        },
        "latency_seconds": {
            "p50": statistics.median([r["elapsed_seconds"] for r in rows]) if rows else None,
            "max": max((r["elapsed_seconds"] for r in rows), default=None),
        },
        "invalid_citations": sum(len(r.get("invalid_citations", [])) for r in rows),
        "abstain_violations": sum(1 for r in rows if r.get("abstain_violation")),
        "macro_corpus_coverage": (
            statistics.mean([r["corpus_coverage"] for r in supported]) if supported else None
        ),
        "macro_cited_coverage": (
            statistics.mean([r["cited_coverage"] for r in supported]) if supported else None
        ),
        "macro_stated_coverage": (
            statistics.mean([r["stated_coverage"] for r in supported]) if supported else None
        ),
        "macro_stated_paraphrase_coverage": (
            statistics.mean([r["stated_paraphrase_coverage"] for r in supported])
            if supported
            else None
        ),
        "macro_citation_term_coverage": _mean_of(
            [r["citation_precision"]["term_coverage"] for r in supported]
        ),
        "macro_citation_number_coverage": _mean_of(
            [r["citation_precision"]["number_coverage"] for r in supported]
        ),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(
        json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2)
    )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
