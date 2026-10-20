"""Explicit bounded corpus ingestion; separate from API startup and publication."""

import asyncio
import json
import math
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from pydantic import SecretStr

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.deduplication import embedding_input_key
from telescope_rag.ingestion.indexing import (
    EmbeddingCache,
    EmbeddingConfiguration,
    QdrantCandidateWriter,
    configuration_hash,
    embed_reviewed,
    validate_chunks,
    write_candidate,
)
from telescope_rag.ingestion.models import PreparedDocument, stable_id
from telescope_rag.ingestion.qdrant_audit import QdrantCandidateAudit
from telescope_rag.ingestion.review import (
    PreparationAudit,
    ReviewApproval,
    all_chunks,
    validate_approval,
)
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import EmbeddingFormat, EmbeddingProvider, EmbeddingResult
from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.providers.qwen_tokenizer import (
    QwenEmbeddingCounter,
    QwenPreparationCounter,
    hosted_qwen_format,
)


@dataclass(frozen=True)
class ReviewedBundle:
    documents: tuple[PreparedDocument, ...]
    audit: PreparationAudit
    approval: ReviewApproval
    configuration: EmbeddingConfiguration


def _read(path: Path, maximum: int = 20_000_000) -> bytes:
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("index_input_missing_or_oversized")
    return path.read_bytes()


def read_secret(path: Path) -> SecretStr:
    try:
        value = _read(path, 1024).decode("ascii").strip()
        if not value or any(ord(c) <= 32 or ord(c) == 127 for c in value):
            raise ValueError
        return SecretStr(value)
    except Exception:
        raise ValueError("index_secret_file_invalid") from None


def load_reviewed_bundle(path: Path) -> ReviewedBundle:
    files = sorted(
        p
        for p in path.glob("*.json")
        if p.name not in {"audit.json", "summary.json", "review-template.json"}
    )
    if not 0 < len(files) <= 250:
        raise ValueError("index_bundle_invalid")
    documents = tuple(PreparedDocument.model_validate_json(_read(p, 12_000_000)) for p in files)
    result = ReviewedBundle(
        documents,
        PreparationAudit.model_validate_json(_read(path / "audit.json")),
        ReviewApproval.model_validate_json(_read(path / "metadata/review-approved.json")),
        EmbeddingConfiguration.model_validate_json(
            _read(path / "metadata/embedding-configuration.json")
        ),
    )
    if result.audit.document_count != len(documents) or result.audit.chunk_count != len(
        all_chunks(documents)
    ):
        raise ValueError("index_bundle_inventory_mismatch")
    validate_approval(result.documents, result.audit, result.approval)
    return result


def plan_run(
    bundle: ReviewedBundle,
    settings: Settings,
    counter: QwenPreparationCounter,
    format: EmbeddingFormat,
    *,
    max_requests: int,
    max_input_tokens: int,
) -> dict:
    if (
        type(max_requests) is not int
        or not 1 <= max_requests <= 1000
        or type(max_input_tokens) is not int
        or not 1 <= max_input_tokens <= 1_000_000
        or settings.provider_max_retries != 0
    ):
        raise ValueError("index_run_limits_invalid")
    validate_approval(bundle.documents, bundle.audit, bundle.approval)
    chunks = all_chunks(bundle.documents)
    validate_chunks(chunks, settings, bundle.configuration)
    if (
        format != hosted_qwen_format()
        or bundle.configuration.format_hash
        != stable_id("embedding-format-v1", format.model_dump_json())
        or bundle.configuration.tokenizer_version != counter.version
    ):
        raise ValueError("index_verified_profile_required")
    groups = {}
    config_hash = configuration_hash(bundle.configuration)
    for chunk in chunks:
        if counter.count(format.format(chunk.retrieval_text, "document")) != chunk.token_count:
            raise ValueError("index_token_count_mismatch")
        groups.setdefault(embedding_input_key(chunk, config_hash), chunk)
    counts = [c.token_count for c in groups.values()]
    batches = []
    for start in range(0, len(counts), settings.max_embedding_batch_size):
        current: list[int] = []
        for count in counts[start : start + settings.max_embedding_batch_size]:
            if sum(current) + count > settings.max_embedding_input_tokens:
                batches.append({"inputs": len(current), "tokens": sum(current)})
                current = []
            current.append(count)
        if current:
            batches.append({"inputs": len(current), "tokens": sum(current)})
    total = sum(counts)
    if len(batches) > max_requests or total > max_input_tokens:
        raise ValueError("index_run_budget_exceeded")
    return {
        "prepared_digest": bundle.audit.prepared_digest,
        "collection_digest": bundle.audit.collection_digest,
        "configuration_hash": config_hash,
        "candidate": "telescope_public_"
        + stable_id(bundle.audit.snapshot_id, bundle.audit.prepared_digest, config_hash)[:24],
        "chunks": len(chunks),
        "unique_inputs": len(groups),
        "total_input_tokens": total,
        "full_run_requests": len(batches),
        "max_requests": max_requests,
        "max_input_tokens": max_input_tokens,
        "batch_size": settings.max_embedding_batch_size,
        "batches": batches,
        "retries": 0,
        "active_alias_changed": False,
    }


class ReceiptEmbeddingRun:
    """Bound the whole run, preserve failed-attempt receipts, and forbid unexpected inputs."""

    def __init__(
        self,
        provider: EmbeddingProvider,
        bundle: ReviewedBundle,
        plan: dict,
        counter: QwenPreparationCounter,
        format: EmbeddingFormat,
        output: Path,
        progress: Callable[[dict], None],
    ):
        self.provider, self.plan, self.counter, self.format = provider, plan, counter, format
        self.output, self.progress = output, progress
        groups = {}
        for chunk in all_chunks(bundle.documents):
            groups.setdefault(embedding_input_key(chunk, plan["configuration_hash"]), chunk)
        self.remaining = Counter(c.retrieval_text for c in groups.values())
        self.calls = self.tokens = 0

    async def embed(
        self,
        texts: Sequence[str],
        *,
        role: Literal["query", "document"],
        format: EmbeddingFormat,
        budget: ExecutionBudget,
    ) -> EmbeddingResult:
        if role != "document" or format != self.format or not texts:
            raise ValueError("index_unexpected_embedding_request")
        requested = Counter(texts)
        if any(self.remaining[text] < n for text, n in requested.items()):
            raise ValueError("index_unexpected_embedding_input")
        tokens = sum(self.counter.count(format.format(text, role)) for text in texts)
        if (
            self.calls + 1 > self.plan["max_requests"]
            or self.tokens + tokens > self.plan["max_input_tokens"]
        ):
            raise ValueError("index_run_budget_exceeded")
        self.calls += 1
        self.tokens += tokens
        self.remaining.subtract(requested)
        outcome = "failed"
        try:
            result = await self.provider.embed(texts, role=role, format=format, budget=budget)
            outcome = "success"
            return result
        except ProviderError as error:
            outcome = error.code
            raise
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            receipt = {
                "batch": self.calls,
                "inputs": len(texts),
                "input_reserved": tokens,
                "cumulative_reserved": self.tokens,
                "outcome": outcome,
                "attempts": [
                    {**asdict(r), "usage": r.usage.model_dump(mode="json")} for r in budget.receipts
                ],
            }
            _write(self.output / f"batch-{self.calls:04}.json", receipt)
            self.progress({k: v for k, v in receipt.items() if k != "attempts"})


def _write(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, allow_nan=False, indent=2)


async def run_candidate(
    bundle_path: Path,
    tokenizer_path: Path,
    cache_path: Path,
    output: Path,
    settings: Settings,
    read_key: SecretStr,
    *,
    max_requests: int = 128,
    max_input_tokens: int = 100000,
    deadline_seconds: float = 600,
    server_version: str = "1.19.2",
    batch_delay_seconds: float = 0.0,
    progress: Callable[[dict], None] = lambda _: None,
) -> dict:
    if not 0 < deadline_seconds <= 3600:
        raise ValueError("index_deadline_invalid")
    if not math.isfinite(batch_delay_seconds) or not 0.0 <= batch_delay_seconds <= 60.0:
        raise ValueError("index_batch_delay_invalid")
    if (
        settings.qdrant_url.host not in {"127.0.0.1", "localhost", "::1"}
        or settings.qdrant_url.path not in {None, "", "/"}
        or settings.qdrant_url.query
        or settings.qdrant_url.fragment
    ):
        raise ValueError("index_local_target_required")
    bundle = load_reviewed_bundle(bundle_path)
    counter = QwenPreparationCounter(tokenizer_path)
    format = hosted_qwen_format()
    plan = plan_run(
        bundle,
        settings,
        counter,
        format,
        max_requests=max_requests,
        max_input_tokens=max_input_tokens,
    )
    cache = EmbeddingCache(cache_path)
    # Check every relevant existing cache record before any paid call, including
    # records belonging to a later batch. Corruption never causes a paid fallback.
    groups = {}
    for chunk in all_chunks(bundle.documents):
        groups.setdefault(embedding_input_key(chunk, plan["configuration_hash"]), chunk)
    cached = sum(
        cache.get(key, plan["configuration_hash"], bundle.configuration.dimensions) is not None
        for key in groups
    )
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False)
    _write(
        output / "plan.json",
        {**plan, "cached_unique_inputs": cached, "deadline_seconds": deadline_seconds},
    )
    lock = cache_path / ".candidate-run.lock"
    lock_file = lock.open("x", encoding="ascii")
    lock_file.write(plan["prepared_digest"])
    lock_file.close()
    audit = QdrantCandidateAudit(settings, read_key)
    writer = QdrantCandidateWriter(settings)
    started = time.monotonic()
    wrapped = None
    try:
        async with asyncio.timeout(deadline_seconds):
            preflight = await audit.preflight(
                plan["candidate"], bundle.configuration.dimensions, expected_version=server_version
            )
            _write(output / "qdrant-preflight.json", preflight)
            async with OpenRouterProviders(
                settings, token_counter=QwenEmbeddingCounter(tokenizer_path)
            ) as providers:
                wrapped = ReceiptEmbeddingRun(
                    providers.embeddings, bundle, plan, counter, format, output, progress
                )
                embedded = await embed_reviewed(
                    bundle.documents,
                    bundle.audit,
                    bundle.approval,
                    provider=wrapped,
                    settings=settings,
                    format=format,
                    configuration=bundle.configuration,
                    cache=cache,
                    batch_delay_seconds=batch_delay_seconds,
                )
            candidate = await write_candidate(
                bundle.documents,
                bundle.audit,
                bundle.approval,
                embedded,
                settings=settings,
                configuration=bundle.configuration,
                writer=writer,
            )
            _write(output / "candidate.json", candidate.model_dump(mode="json"))
            verification = await audit.verify(
                candidate.collection, embedded, preflight["aliases_before"]
            )
            _write(output / "verification.json", verification)
            result = {
                "status": "candidate_verified_unpublished",
                "collection": candidate.collection,
                "points": candidate.points,
                "unique_inputs": plan["unique_inputs"],
                "embedding_http_calls": wrapped.calls,
                "input_reserved": wrapped.tokens,
                "cached_inputs_before": cached,
                "active_alias_changed": False,
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            _write(output / "result.json", result)
            return result
    except BaseException as error:
        _write(
            output / "failure.json",
            {
                "status": "failed_unpublished",
                "error": error.code if isinstance(error, ProviderError) else type(error).__name__,
                "embedding_calls_started": wrapped.calls if wrapped else 0,
                "input_reserved": wrapped.tokens if wrapped else 0,
                "active_alias_changed": False,
            },
        )
        raise
    finally:
        try:
            await writer.aclose()
        finally:
            try:
                await audit.aclose()
            finally:
                lock.unlink()
