"""Compare two prepared corpora: duplicate occurrences, evidence, and fact coverage.

Usage:
    python scripts/compare_corpus_versions.py \
        --baseline data/processed/m3-execution-approved-v6-v2 \
        --rebuilt data/processed/m7-admitted-v1

The comparison answers, with counts rather than claims: whether site
boilerplate duplicates actually fell, whether every published line survived the
rebuild, and whether both corpora can still support the fact-level gold.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys
import unicodedata

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from telescope_rag.ingestion.deduplication import embedding_input_key  # noqa: E402
from telescope_rag.ingestion.models import PreparedDocument  # noqa: E402

BOILERPLATE = {
    "footer contact block": re.compile(
        r"info@telescopecenter\.com.*?\+962 6 552 3333.*?228 Zahran St\.", re.S
    ),
    "booking call to action": re.compile(
        "Ready to Schedule Your Visit|Book Appointment|Schedule a Free Consultation"
        "|هل أنت مستعد لبدء رحلتك|احجز موعدك الآن|ابدأ باستشارة مجانية",
        re.I,
    ),
    "copyright notice": re.compile(r"all rights reserved", re.I),
    "site tagline": re.compile(
        "Clear Vision\\. Confident Skin\\.|رؤية أوضح \.\. وبشرة أكثر إشراقاً",
        re.I,
    ),
}


def load(directory: pathlib.Path):
    out: dict[str, list[PreparedDocument]] = {}
    for path in sorted(directory.glob("*.json")):
        if len(path.stem) == 64:
            d = PreparedDocument.model_validate_json(path.read_bytes())
            out.setdefault(d.document.page.canonical_url, []).append(d)
    return out


def chunks_of(bundle):
    return [c for docs in bundle.values() for d in docs for c in d.chunks]


def words(text: str):
    t = unicodedata.normalize("NFC", text).casefold()
    t = re.sub(r"[^\w\u0600-\u06ff]+", " ", t, flags=re.UNICODE)
    return collections.Counter(x for x in t.split() if len(x) > 1)


def boilerplate_class(text: str):
    for label, pattern in BOILERPLATE.items():
        if pattern.search(text):
            return label
    return None


def analyse(label: str, directory: pathlib.Path):
    bundle = load(directory)
    chunks = chunks_of(bundle)
    groups: dict[str, list] = collections.defaultdict(list)
    for c in chunks:
        groups[embedding_input_key(c)].append(c)

    duplicated = {k: v for k, v in groups.items() if len(v) > 1}
    duplicate_occurrences = sum(len(v) - 1 for v in duplicated.values())
    boiler_groups: dict[str, list] = {}
    for members in duplicated.values():
        kind = boilerplate_class(members[0].retrieval_text)
        if kind:
            boiler_groups.setdefault(kind, []).append(members)
    boiler_occurrences = sum(
        len(members) - 1 for groups_ in boiler_groups.values() for members in groups_
    )
    all_words = words(" ".join(c.retrieval_text for c in chunks))
    print("=" * 100)
    print(f"{label}   ({directory.name})")
    print(f"  documents                     {len(bundle)}")
    print(f"  chunks                        {len(chunks)}")
    print(f"  distinct evidence groups      {len(groups)}")
    print(f"  duplicated groups             {len(duplicated)}")
    print(f"  duplicate occurrences         {duplicate_occurrences}")
    print(f"    of which site boilerplate   {boiler_occurrences}")
    for kind, members in sorted(boiler_groups.items()):
        occurrences = sum(len(v) - 1 for v in members)
        print(f"      {kind:24s} groups={len(members):3d} occurrences={occurrences:4d}")
    print(f"    of which other repeats      {duplicate_occurrences - boiler_occurrences}")
    print(f"  distinct published words      {len(all_words)}")
    print(
        f"  chunk types                   {dict(collections.Counter(c.block_type for c in chunks))}"
    )
    print(
        f"  languages                     {dict(collections.Counter(c.language for c in chunks))}"
    )
    tokens = [c.token_count for c in chunks if c.token_count]
    if tokens:
        s = sorted(tokens)
        print(f"  tokens                        p50={s[len(s) // 2]} p90={s[int(len(s) * 0.9)]}")
    return {
        "chunks": chunks,
        "words": all_words,
        "bundle": bundle,
        "duplicate_occurrences": duplicate_occurrences,
        "boilerplate_occurrences": boiler_occurrences,
    }


def published_lines(bundle):
    lines = set()
    for documents in bundle.values():
        for document in documents:
            for chunk in document.chunks:
                for raw in chunk.original_text.split("\n"):
                    line = re.sub(r"\s+", " ", raw).strip()
                    if len(line) >= 12:
                        lines.add(line)
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=pathlib.Path, required=True)
    parser.add_argument("--rebuilt", type=pathlib.Path, required=True)
    args = parser.parse_args()

    base = analyse("PUBLISHED CORPUS", args.baseline)
    new = analyse("REBUILT CORPUS", args.rebuilt)

    print("=" * 100)
    print("PUBLISHED LINES PRESERVED")
    base_lines = published_lines(base["bundle"])
    new_text = re.sub(
        r"\s+",
        " ",
        " ".join(c.retrieval_text for c in new["chunks"])
        + " "
        + " ".join(c.original_text for c in new["chunks"]),
    )
    lost = [line for line in base_lines if line not in new_text]
    print(f"  published lines (>=12 chars)   {len(base_lines)}")
    print(f"  still present after rebuild    {len(base_lines) - len(lost)}")
    print(f"  not present                    {len(lost)}")
    for reason, count in collections.Counter(
        boilerplate_class(line) or "other" for line in lost
    ).most_common():
        print(f"      {count:4d}  {reason}")
    for line in sorted(lost):
        if not boilerplate_class(line):
            print(f"      lost: {line[:190]!r}")

    print("=" * 100)
    print("DISTINCT PUBLISHED CONTENT")
    lost_words = base["words"] - new["words"]
    gained_words = new["words"] - base["words"]
    print(f"  words in published only       {sum(lost_words.values())}")
    print(f"  words in rebuild only         {sum(gained_words.values())}")

    print("=" * 100)
    print("FACT-LEVEL GOLD COVERAGE (corpus level, exact literal)")
    gold = json.loads(
        (REPO / "tests/fixtures/evaluation/natural_questions_50_v1/facts-v1.json").read_text(
            encoding="utf-8"
        )
    )
    for label, result in (("published", base), ("rebuilt", new)):
        texts: dict[str, list[str]] = {"en": [], "ar": []}
        for c in result["chunks"]:
            texts[c.language].append(c.retrieval_text)
        supported = 0
        total = 0
        unsupported = []
        for intent in gold["intents"]:
            for fact in intent["facts"]:
                for language in ("en", "ar"):
                    total += 1
                    variants = fact["variants"].get(language, [])
                    if any(v in t for v in variants for t in texts[language]):
                        supported += 1
                    else:
                        unsupported.append((intent["intent_id"], fact["fact_id"], language))
        print(f"  {label:10s} fact/language pairs supported: {supported}/{total}")
        for entry in unsupported:
            print(f"      unsupported: {entry}")


if __name__ == "__main__":
    main()
