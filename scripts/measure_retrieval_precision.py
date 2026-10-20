"""Measure retrieval precision against a fact-level gold over the approved questions.

Capture mode embeds the approved everyday questions once, reads the pinned local
candidate collection, and records the raw dense/lexical/context candidate lists.
Score mode replays those recorded lists under different retrieval policies and
reports fact recall, evidence diversity and duplicate slot waste.

Capture spends provider credit for query embeddings only. Score is fully offline.
Neither mode writes to the corpus, publishes an alias or changes the index.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telescope_rag.core.settings import Settings, load_settings
from telescope_rag.graph.contracts import RetrievalQuery
from telescope_rag.ingestion.deduplication import embedding_input_key
from telescope_rag.ingestion.indexing import (
    EmbeddingCache,
    EmbeddingConfiguration,
    configuration_hash,
)
from telescope_rag.ingestion.models import PreparedChunk, PreparedDocument
from telescope_rag.ingestion.runner import read_secret
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.providers.qwen_tokenizer import (
    QwenEmbeddingCounter,
    QwenPreparationCounter,
    hosted_qwen_format,
)
from telescope_rag.retrieval.assembly import EvidenceCatalog, SourceScope
from telescope_rag.retrieval.candidate import CandidateDenseReader
from telescope_rag.retrieval.duplicates import DuplicateIndex
from telescope_rag.retrieval.lexical import BM25Index
from telescope_rag.retrieval.request_dense import RequestDenseRetriever, query_cache_key
from telescope_rag.retrieval.section_context import section_context

DEFAULT_COLLECTION = "telescope_public_018817ac10ec05ecad92adb9"
DEFAULT_PREPARED_DIGEST = "a46be2d3fd18f11d46c79ff9bc992de22aab496836894a708bc57c1e8b48af88"
DEFAULT_BUNDLE = "m3-execution-approved-v6-v2"
TOKENIZER_REVISION = "1d8ad4ca9b3dd8059ad90a75d4983776a23d44af"
REQUESTS = Path("tests/fixtures/evaluation/natural_questions_50_v1/requests.jsonl")
FACTS = Path("tests/fixtures/evaluation/natural_questions_50_v1/facts-v1.json")
DENSE_CAPTURE_LIMIT = 20
LEXICAL_CAPTURE_LIMIT = 20


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Candidate(Record):
    chunk_id: str = Field(min_length=1)
    score: float


class QuestionRanking(Record):
    case_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    language: Literal["en", "ar"]
    dense: tuple[Candidate, ...]
    lexical: tuple[Candidate, ...]
    context: tuple[str, ...]

    @model_validator(mode="after")
    def distinct_candidates(self):
        if len({c.chunk_id for c in self.dense}) != len(self.dense):
            raise ValueError("duplicate_dense_candidate")
        if len({c.chunk_id for c in self.lexical}) != len(self.lexical):
            raise ValueError("duplicate_lexical_candidate")
        return self


class Capture(Record):
    schema_version: Literal["retrieval-precision-capture-v1"] = "retrieval-precision-capture-v1"
    prepared_digest: str
    collection: str
    questions: tuple[QuestionRanking, ...]

    @model_validator(mode="after")
    def complete_inventory(self):
        if len(self.questions) != 50:
            raise ValueError("question_inventory_incomplete")
        return self


class Policy(Record):
    """A retrieval policy replayed offline against a recorded capture."""

    name: str = Field(default="policy", min_length=1, max_length=64)
    dense_fetch: int = Field(default=5, ge=1, le=DENSE_CAPTURE_LIMIT)
    dense_keep: int = Field(default=5, ge=1, le=DENSE_CAPTURE_LIMIT)
    lexical_keep: int = Field(default=3, ge=0, le=LEXICAL_CAPTURE_LIMIT)
    context_keep: int = Field(default=2, ge=0, le=2)
    collapse_duplicates: bool = False
    scope_language: bool = False
    exclude_url_fragments: tuple[str, ...] = ()

    @model_validator(mode="after")
    def bounded_pool(self):
        if self.dense_keep > self.dense_fetch:
            raise ValueError("dense_keep_exceeds_fetch")
        return self


def load_bundle(
    root: Path, bundle: str = DEFAULT_BUNDLE
) -> tuple[tuple[PreparedDocument, ...], dict[str, PreparedChunk]]:
    directory = root / "data/processed" / bundle
    documents = tuple(
        PreparedDocument.model_validate_json(path.read_bytes())
        for path in sorted(directory.glob("*.json"))
        if len(path.stem) == 64
    )
    if not documents:
        raise ValueError("bundle_missing")
    chunks = {chunk.chunk_id: chunk for document in documents for chunk in document.chunks}
    return documents, chunks


def load_questions(root: Path) -> list[dict]:
    rows = [
        json.loads(line)
        for line in (root / REQUESTS).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 50:
        raise ValueError("question_inventory_changed")
    return rows


def load_facts(root: Path) -> tuple[dict[str, dict], str]:
    """The fact ground truth and the corpus digest it was authored against.

    The gold states clinic facts, not corpus bytes, so it applies to every
    corpus that publishes those facts. The recorded digest is returned so the
    report can state which corpus it was written against.
    """
    gold = json.loads((root / FACTS).read_text(encoding="utf-8"))
    return {intent["intent_id"]: intent for intent in gold["intents"]}, gold.get(
        "prepared_digest", ""
    )


def settings_for(
    root: Path,
    qdrant_url: str = "http://127.0.0.1:6333",
    read_key: Path = Path(".tools/qdrant-m3/read.key"),
) -> Settings:
    """The shipped local profile's retrieval settings, over the project dotenv."""
    source = load_settings(root / ".env")
    values = source.model_dump()
    values.update(
        qdrant_url=qdrant_url,
        qdrant_api_key=read_secret(root / read_key),
        provider_max_retries=0,
        request_timeout_seconds=150,
        provider_timeout_seconds=60,
        max_embedding_batch_size=16,
        retrieval_top_k_per_question=11,
    )
    return Settings(_env_file=None, **values)


async def capture(
    root: Path,
    output: Path,
    *,
    bundle: str = DEFAULT_BUNDLE,
    collection: str = DEFAULT_COLLECTION,
    prepared_digest: str = DEFAULT_PREPARED_DIGEST,
    qdrant_url: str = "http://127.0.0.1:6333",
    read_key: Path = Path(".tools/qdrant-m3/read.key"),
    reader_target: str = "loopback",
    query_cache: Path | None = None,
    batch_delay_seconds: float = 0.0,
) -> None:
    documents, chunks = load_bundle(root, bundle)
    catalog = EvidenceCatalog(documents, expected_digest=prepared_digest)
    questions = load_questions(root)
    settings = settings_for(root, qdrant_url, read_key)
    tokenizer = root / f".tools/qwen-tokenizer/{TOKENIZER_REVISION}/tokenizer.json"
    counter = QwenEmbeddingCounter(tokenizer)
    profile = hosted_qwen_format()
    configuration = EmbeddingConfiguration.model_validate_json(
        (root / f"data/processed/{bundle}/metadata/embedding-configuration.json").read_bytes()
    )
    config_hash = configuration_hash(configuration)
    cache = EmbeddingCache(query_cache) if query_cache else None
    reader = CandidateDenseReader(
        settings,
        settings.qdrant_api_key,
        collection=collection,
        chunks={chunk.point_id: chunk for chunk in catalog.chunks.values()},
        target=reader_target,
    )
    lexical = BM25Index(
        {identity: chunk.retrieval_text for identity, chunk in catalog.chunks.items()}
    )
    allowed = frozenset(catalog.chunks)
    providers = OpenRouterProviders(settings, token_counter=counter)
    rankings: list[QuestionRanking] = []
    dispatched = False
    try:
        batch_size = settings.max_embedding_batch_size
        for start in range(0, len(questions), batch_size):
            batch = questions[start : start + batch_size]
            keys = [query_cache_key(row["query"], config_hash) for row in batch]
            vectors: dict[str, tuple[float, ...]] = {}
            missing: list[int] = []
            for index, key in enumerate(keys):
                cached = cache.get(key, config_hash, configuration.dimensions) if cache else None
                if cached is None:
                    missing.append(index)
                else:
                    vectors[key] = cached
            if missing:
                if dispatched and batch_delay_seconds:
                    await asyncio.sleep(batch_delay_seconds)
                dispatched = True
                budget = ExecutionBudget(settings)
                result = await providers.embeddings.embed(
                    [batch[index]["query"] for index in missing],
                    role="query",
                    format=profile,
                    budget=budget,
                )
                for index, vector in zip(missing, result.vectors, strict=True):
                    vectors[keys[index]] = vector
                    if cache:
                        cache.put(keys[index], config_hash, vector)
            for row, key in zip(batch, keys, strict=True):
                vector = vectors[key]
                hits = await reader.search(vector, limit=DENSE_CAPTURE_LIMIT)
                lexical_hits = lexical.search(row["query"], limit=LEXICAL_CAPTURE_LIMIT)
                contexts = section_context(
                    catalog,
                    tuple(hit.chunk_id for hit in lexical_hits),
                    allowed=allowed,
                    limit=2,
                )
                rankings.append(
                    QuestionRanking(
                        case_id=row["case_id"],
                        query=row["query"],
                        language="en" if row["language"] == "en" else "ar",
                        dense=tuple(
                            Candidate(chunk_id=hit.chunk.chunk_id, score=hit.score) for hit in hits
                        ),
                        lexical=tuple(
                            Candidate(chunk_id=hit.chunk_id, score=hit.score)
                            for hit in lexical_hits
                        ),
                        context=contexts,
                    )
                )
            print(f"embedded {start + len(batch)}/{len(questions)} questions", flush=True)
    finally:
        await reader.aclose()
        await providers.aclose()
    capture_record = Capture(
        prepared_digest=prepared_digest,
        collection=collection,
        questions=tuple(rankings),
    )
    serialized = capture_record.model_dump_json(indent=2)
    await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(output.write_text, serialized, encoding="utf-8")
    print(f"wrote {output}")


def simulate(
    policy: Policy,
    ranking: QuestionRanking,
    chunks: dict[str, PreparedChunk],
) -> list[str]:
    """Replay one recorded ranking under a retrieval policy, in runtime order."""
    excluded = policy.exclude_url_fragments
    selected: list[str] = []
    seen_content: set[str] = set()
    dense_added = 0

    def admitted(identity: str) -> bool:
        chunk = chunks.get(identity)
        if chunk is None:
            return False
        if policy.scope_language and chunk.language != ranking.language:
            return False
        return not any(fragment in chunk.canonical_url for fragment in excluded)

    def take(identity: str) -> bool:
        if identity in selected or not admitted(identity):
            return False
        key = embedding_input_key(chunks[identity])
        if policy.collapse_duplicates and key in seen_content:
            return False
        selected.append(identity)
        seen_content.add(key)
        return True

    for candidate in ranking.dense[: policy.dense_fetch]:
        if dense_added >= policy.dense_keep:
            break
        if take(candidate.chunk_id):
            dense_added += 1
    lexical_added = 0
    for candidate in ranking.lexical:
        if lexical_added >= policy.lexical_keep:
            break
        if take(candidate.chunk_id):
            lexical_added += 1
    context_added = 0
    for identity in ranking.context:
        if context_added >= policy.context_keep:
            break
        if take(identity):
            context_added += 1
    return selected


def score_question(
    policy: Policy,
    ranking: QuestionRanking,
    chunks: dict[str, PreparedChunk],
    intent: dict,
) -> dict:
    selected = simulate(policy, ranking, chunks)
    texts = [chunks[identity].retrieval_text for identity in selected]
    details = []
    witnessed = 0
    supporting: set[str] = set()
    for fact in intent["facts"]:
        variants = fact["variants"].get(ranking.language, [])
        present = [v for v in variants if any(v in text for text in texts)]
        minimum = fact.get("minimum_variants", 1)
        ok = len(present) >= minimum
        witnessed += int(ok)
        if ok:
            for identity, text in zip(selected, texts, strict=True):
                if any(v in text for v in present):
                    supporting.add(identity)
        details.append(
            {
                "fact_id": fact["fact_id"],
                "witnessed": ok,
                "variants_present": len(present),
                "variants_required": minimum,
            }
        )
    total = len(intent["facts"])
    over_claim = False
    if intent["outcome"] == "abstain":
        patterns = [re.compile(p) for p in intent.get("abstain_patterns", [])]
        over_claim = any(pattern.search(text) for pattern in patterns for text in texts)
    content_keys = [embedding_input_key(chunks[identity]) for identity in selected]
    duplicate_slots = len(content_keys) - len(set(content_keys))
    return {
        "case_id": ranking.case_id,
        "intent_id": intent["intent_id"],
        "language": ranking.language,
        "outcome": intent["outcome"],
        "selected": len(selected),
        "distinct_evidence": len(set(content_keys)),
        "duplicate_slots": duplicate_slots,
        "fact_recall": (witnessed / total) if total else None,
        "evidence_precision": (len(supporting) / len(selected)) if selected else None,
        "supporting_chunks": len(supporting),
        "facts": details,
        "over_claim": over_claim,
        "selected_urls": sorted(
            {
                chunks[identity].canonical_url.replace("https://telescopecenter.com", "") or "/"
                for identity in selected
            }
        ),
    }


def score(
    root: Path,
    capture_path: Path,
    output: Path,
    policies: Sequence[Policy],
    *,
    bundle: str = DEFAULT_BUNDLE,
) -> None:
    documents, chunks = load_bundle(root, bundle)
    _ = documents
    capture_record = Capture.model_validate_json(capture_path.read_bytes())
    facts, gold_digest = load_facts(root)
    report: dict[str, Any] = {
        "schema_version": "retrieval-precision-report-v1",
        "prepared_digest": capture_record.prepared_digest,
        "collection": capture_record.collection,
        "gold_authored_against_digest": gold_digest,
        "question_count": len(capture_record.questions),
        "policies": [],
    }
    for policy in policies:
        rows = []
        for ranking in capture_record.questions:
            intent = facts[ranking.case_id.split("-")[0]]
            rows.append(score_question(policy, ranking, chunks, intent))
        scored = [row for row in rows if row["fact_recall"] is not None]
        recalls = [row["fact_recall"] for row in scored]
        precisions = [
            row["evidence_precision"] for row in scored if row["evidence_precision"] is not None
        ]
        abstains = [row for row in rows if row["outcome"] == "abstain"]
        by_language = {}
        for language in ("en", "ar"):
            subset = [row["fact_recall"] for row in scored if row["language"] == language]
            subset_p = [
                row["evidence_precision"]
                for row in scored
                if row["language"] == language and row["evidence_precision"] is not None
            ]
            by_language[language] = {
                "questions": len(subset),
                "macro_fact_recall": (sum(subset) / len(subset)) if subset else None,
                "macro_evidence_precision": ((sum(subset_p) / len(subset_p)) if subset_p else None),
            }
        report["policies"].append(
            {
                "policy": policy.model_dump(mode="json"),
                "macro_fact_recall": (sum(recalls) / len(recalls)) if recalls else None,
                "macro_evidence_precision": (
                    (sum(precisions) / len(precisions)) if precisions else None
                ),
                "questions_with_full_recall": sum(1 for r in recalls if r == 1.0),
                "questions_with_zero_recall": sum(1 for r in recalls if r == 0.0),
                "mean_distinct_evidence": (
                    sum(row["distinct_evidence"] for row in rows) / len(rows)
                ),
                "mean_duplicate_slots": sum(row["duplicate_slots"] for row in rows) / len(rows),
                "abstain_questions": len(abstains),
                "abstain_over_claim_questions": sum(1 for row in abstains if row["over_claim"]),
                "by_language": by_language,
                "rows": rows,
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for entry in report["policies"]:
        policy = entry["policy"]
        scored_count = len(scored)
        precision = entry["macro_evidence_precision"]
        print(
            f"dense_fetch={policy['dense_fetch']} dense_keep={policy['dense_keep']} "
            f"lex={policy['lexical_keep']} ctx={policy['context_keep']} "
            f"dedup={policy['collapse_duplicates']} lang_scope={policy['scope_language']} "
            f"-> macro_fact_recall={entry['macro_fact_recall']:.4f} "
            f"macro_evidence_precision={'n/a' if precision is None else f'{precision:.4f}'} "
            f"full={entry['questions_with_full_recall']}/{scored_count} "
            f"zero={entry['questions_with_zero_recall']} "
            f"distinct={entry['mean_distinct_evidence']:.2f} "
            f"dup_slots={entry['mean_duplicate_slots']:.2f}"
        )
    print(f"wrote {output}")


def verify(
    root: Path,
    output: Path,
    *,
    bundle: str = DEFAULT_BUNDLE,
    collection: str = DEFAULT_COLLECTION,
    prepared_digest: str = DEFAULT_PREPARED_DIGEST,
    qdrant_url: str = "http://127.0.0.1:6333",
    read_key: Path = Path(".tools/qdrant-m3/read.key"),
    reader_target: str = "loopback",
    query_cache: Path | None = None,
    batch_delay_seconds: float = 0.0,
) -> None:
    """Run the real request-scoped retriever over the approved questions.

    This exercises the shipped duplicate collapse, the answer-language scope and
    the real lexical/context additions. It is not a simulation of them.
    """
    import asyncio

    documents, chunks = load_bundle(root, bundle)
    catalog = EvidenceCatalog(documents, expected_digest=prepared_digest)
    questions = load_questions(root)
    facts, gold_digest = load_facts(root)
    settings = settings_for(root, qdrant_url, read_key)
    tokenizer = root / f".tools/qwen-tokenizer/{TOKENIZER_REVISION}/tokenizer.json"
    preparation_counter = QwenPreparationCounter(tokenizer)
    provider_counter = QwenEmbeddingCounter(tokenizer)
    reader = CandidateDenseReader(
        settings,
        settings.qdrant_api_key,
        collection=collection,
        chunks={chunk.point_id: chunk for chunk in catalog.chunks.values()},
        target=reader_target,
    )
    providers = OpenRouterProviders(settings, token_counter=provider_counter)
    duplicates = DuplicateIndex(catalog.chunks)
    retriever = RequestDenseRetriever(
        settings=settings,
        catalog=catalog,
        configuration=EmbeddingConfiguration.model_validate_json(
            (root / f"data/processed/{bundle}/metadata/embedding-configuration.json").read_bytes()
        ),
        counter=preparation_counter,
        embeddings=providers.embeddings,
        reader=reader,
        cache=EmbeddingCache(query_cache) if query_cache else None,
        lexical_rescue_limit=2,
        ancestor_context_limit=1,
        duplicate_index=duplicates,
        duplicate_margin=12,
    )
    rows: list[dict] = []

    async def run() -> None:
        try:
            for row in questions:
                language = "en" if row["language"] == "en" else "ar"
                query = RetrievalQuery(
                    part_id=row["case_id"],
                    text=row["query"],
                    scope=SourceScope(language=language),
                )
                budget = ExecutionBudget(settings)
                batch = await retriever.retrieve(
                    (query,),
                    snapshot_id=retriever._snapshot,
                    prepared_digest=catalog.prepared_digest,
                    budget=budget,
                )
                selected = list(batch.parts[0].chunk_ids)
                intent = facts[row["case_id"].split("-")[0]]
                text = [chunks[identity].retrieval_text for identity in selected]
                details, witnessed = [], 0
                for fact in intent["facts"]:
                    variants = fact["variants"].get(language, [])
                    present = [v for v in variants if any(v in t for t in text)]
                    ok = len(present) >= fact.get("minimum_variants", 1)
                    witnessed += int(ok)
                    details.append(
                        {
                            "fact_id": fact["fact_id"],
                            "witnessed": ok,
                            "variants_present": len(present),
                            "variants_required": fact.get("minimum_variants", 1),
                        }
                    )
                patterns = [re.compile(p) for p in intent.get("abstain_patterns", [])]
                keys = [duplicates.content_key(i) for i in selected]
                rows.append(
                    {
                        "case_id": row["case_id"],
                        "intent_id": intent["intent_id"],
                        "language": language,
                        "outcome": intent["outcome"],
                        "selected": len(selected),
                        "distinct_evidence": len(set(keys)),
                        "duplicate_slots": len(keys) - len(set(keys)),
                        "fact_recall": (
                            witnessed / len(intent["facts"]) if intent["facts"] else None
                        ),
                        "facts": details,
                        "over_claim": intent["outcome"] == "abstain"
                        and any(p.search(t) for p in patterns for t in text),
                        "selected_urls": sorted(
                            {
                                chunks[i].canonical_url.replace("https://telescopecenter.com", "")
                                or "/"
                                for i in selected
                            }
                        ),
                    }
                )
        finally:
            await reader.aclose()
            await providers.aclose()

    asyncio.run(run())
    scored = [r for r in rows if r["fact_recall"] is not None]
    abstains = [r for r in rows if r["outcome"] == "abstain"]
    report = {
        "schema_version": "retrieval-precision-verify-v1",
        "prepared_digest": prepared_digest,
        "collection": collection,
        "gold_authored_against_digest": gold_digest,
        "duplicate_groups": duplicates.group_count,
        "collapsed_occurrences": duplicates.collapsed_occurrence_count,
        "macro_fact_recall": sum(r["fact_recall"] for r in scored) / len(scored),
        "questions_with_full_recall": sum(1 for r in scored if r["fact_recall"] == 1.0),
        "questions_with_zero_recall": sum(1 for r in scored if r["fact_recall"] == 0.0),
        "scored_questions": len(scored),
        "mean_distinct_evidence": sum(r["distinct_evidence"] for r in rows) / len(rows),
        "mean_duplicate_slots": sum(r["duplicate_slots"] for r in rows) / len(rows),
        "abstain_questions": len(abstains),
        "abstain_over_claim_questions": sum(1 for r in abstains if r["over_claim"]),
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"real retriever: macro_fact_recall={report['macro_fact_recall']:.4f} "
        f"full={report['questions_with_full_recall']}/{report['scored_questions']} "
        f"zero={report['questions_with_zero_recall']} "
        f"distinct={report['mean_distinct_evidence']:.2f} "
        f"dup_slots={report['mean_duplicate_slots']:.2f} "
        f"abstain_over_claim={report['abstain_over_claim_questions']}/{report['abstain_questions']}"
    )
    print(f"wrote {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--root", type=Path, default=Path.cwd())
    capture_parser.add_argument("--output", type=Path, required=True)
    capture_parser.add_argument("--bundle", default=DEFAULT_BUNDLE)
    capture_parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    capture_parser.add_argument("--prepared-digest", default=DEFAULT_PREPARED_DIGEST)
    capture_parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    capture_parser.add_argument("--read-key", type=Path, default=Path(".tools/qdrant-m3/read.key"))
    capture_parser.add_argument("--reader-target", default="loopback")
    capture_parser.add_argument("--query-cache", type=Path)
    capture_parser.add_argument("--batch-delay-seconds", type=float, default=0.0)
    score_parser = commands.add_parser("score")
    score_parser.add_argument("--root", type=Path, default=Path.cwd())
    score_parser.add_argument("--capture", type=Path, required=True)
    score_parser.add_argument("--output", type=Path, required=True)
    score_parser.add_argument("--bundle", default=DEFAULT_BUNDLE)
    score_parser.add_argument(
        "--policies",
        type=Path,
        required=True,
        help="JSON file with a list of policy objects.",
    )
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--root", type=Path, default=Path.cwd())
    verify_parser.add_argument("--output", type=Path, required=True)
    verify_parser.add_argument("--bundle", default=DEFAULT_BUNDLE)
    verify_parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    verify_parser.add_argument("--prepared-digest", default=DEFAULT_PREPARED_DIGEST)
    verify_parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    verify_parser.add_argument("--read-key", type=Path, default=Path(".tools/qdrant-m3/read.key"))
    verify_parser.add_argument("--reader-target", default="loopback")
    verify_parser.add_argument("--query-cache", type=Path)
    args = parser.parse_args()
    if args.command == "capture":
        asyncio.run(
            capture(
                args.root,
                args.output,
                bundle=args.bundle,
                collection=args.collection,
                prepared_digest=args.prepared_digest,
                qdrant_url=args.qdrant_url,
                read_key=args.read_key,
                reader_target=args.reader_target,
                query_cache=args.query_cache,
                batch_delay_seconds=args.batch_delay_seconds,
            )
        )
    elif args.command == "verify":
        verify(
            args.root,
            args.output,
            bundle=args.bundle,
            collection=args.collection,
            prepared_digest=args.prepared_digest,
            qdrant_url=args.qdrant_url,
            read_key=args.read_key,
            reader_target=args.reader_target,
            query_cache=args.query_cache,
        )
    else:
        policies = [Policy.model_validate(item) for item in json.loads(args.policies.read_bytes())]
        score(args.root, args.capture, args.output, policies, bundle=args.bundle)


if __name__ == "__main__":
    main()
