"""Request-scoped embedding and filtered candidate reads; opt-in, never an index writer."""

import asyncio
import math
from collections.abc import Sequence
from typing import Protocol

from telescope_rag.core.settings import Settings
from telescope_rag.graph.contracts import RetrievalBatch, RetrievalQuery, RetrievedPart
from telescope_rag.ingestion.indexing import (
    EmbeddingConfiguration,
    configuration_hash,
    validate_chunks,
)
from telescope_rag.ingestion.models import stable_id
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import EmbeddingProvider, EmbeddingResult
from telescope_rag.providers.qwen_tokenizer import QwenPreparationCounter, hosted_qwen_format
from telescope_rag.retrieval.assembly import EvidenceCatalog
from telescope_rag.retrieval.candidate import CandidateDenseReader


class ReadOnlyQueryCache(Protocol):
    def get(self, key: str, config_hash: str, dimensions: int) -> tuple[float, ...] | None: ...


def query_cache_key(text: str, config_hash: str) -> str:
    """Same exact identity as the frozen query-cache preparation, without text heuristics."""
    if (
        type(text) is not str
        or not text.strip()
        or len(text) > 4000
        or type(config_hash) is not str
        or len(config_hash) != 64
        or any(c not in "0123456789abcdef" for c in config_hash)
    ):
        raise ValueError("request_dense_cache_input_invalid")
    profile = hosted_qwen_format()
    return stable_id(
        "retrieval-query-v1", config_hash, profile.model_dump_json(), profile.format(text, "query")
    )


def _vector(value: Sequence[float]) -> tuple[float, ...]:
    try:
        if (
            not isinstance(value, (tuple, list))
            or len(value) != 4096
            or any(type(v) not in {float, int} or not math.isfinite(v) for v in value)
            or not 0 < math.hypot(*value) < math.inf
        ):
            raise ValueError
        return tuple(float(v) for v in value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("request_dense_invalid_vector") from None


class RequestDenseRetriever:
    """One bounded search round on a pinned unpublished candidate.

    Dependencies/resources are caller-owned. No new budget, cache writes,
    corpus embedding, source interpretation, approval or production wiring.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        catalog: EvidenceCatalog,
        configuration: EmbeddingConfiguration,
        counter: QwenPreparationCounter,
        embeddings: EmbeddingProvider,
        reader: CandidateDenseReader,
        cache: ReadOnlyQueryCache | None = None,
    ) -> None:
        profile = hosted_qwen_format()
        configuration = EmbeddingConfiguration.model_validate_json(configuration.model_dump_json())
        if (
            settings.app_env == "production"
            or settings.provider_max_retries != 0
            or not 1 <= settings.retrieval_top_k_per_question <= 20
            or type(counter) is not QwenPreparationCounter
            or type(reader) is not CandidateDenseReader
            or counter.verified is not True
            or counter.model != settings.openrouter_embedding_model
            or counter.version != configuration.tokenizer_version
            or configuration.format_version != profile.version
            or configuration.format_hash
            != stable_id("embedding-format-v1", profile.model_dump_json())
        ):
            raise ValueError("request_dense_configuration_invalid")
        validate_chunks(tuple(catalog.chunks.values()), settings, configuration)
        reader.check_inventory({c.point_id: c for c in catalog.chunks.values()}, settings=settings)
        self._settings, self._catalog, self._counter = settings, catalog, counter
        self._embeddings, self._reader, self._cache = embeddings, reader, cache
        self._configuration_hash = configuration_hash(configuration)
        self._snapshot = next(iter(catalog.chunks.values())).snapshot_id

    async def retrieve(
        self,
        queries: Sequence[RetrievalQuery],
        *,
        snapshot_id: str,
        prepared_digest: str,
        budget: ExecutionBudget,
    ) -> RetrievalBatch:
        if (
            snapshot_id != self._snapshot
            or prepared_digest != self._catalog.prepared_digest
            or not isinstance(queries, (tuple, list))
            or not 1 <= len(queries) <= self._settings.max_subquestions
            or type(budget) is not ExecutionBudget
        ):
            raise ValueError("request_dense_request_invalid")
        budget.remaining_seconds()
        copied = tuple(RetrievalQuery.model_validate_json(q.model_dump_json()) for q in queries)
        if len({q.part_id for q in copied}) != len(copied) or any(
            not q.part_id or len(q.part_id) > 128 or q.scope.complete for q in copied
        ):
            raise ValueError("request_dense_query_inventory_invalid")
        # Validate every scope and cache entry before the first possible paid request.
        points = [
            tuple(self._catalog.chunks[i].point_id for i in self._catalog.scope_members(q.scope))
            for q in copied
        ]
        keys = [query_cache_key(q.text, self._configuration_hash) for q in copied]
        texts = {key: q.text for key, q, ids in zip(keys, copied, points, strict=True) if ids}
        vectors = {}
        for key in texts:
            found = (
                self._cache.get(key, self._configuration_hash, 4096)
                if self._cache is not None
                else None
            )
            if found is not None:
                vectors[key] = _vector(found)
        missing = [key for key in texts if key not in vectors]
        if len(missing) > self._settings.max_embedding_batch_size:
            raise ValueError("request_dense_single_batch_exceeded")
        if missing:
            profile = hosted_qwen_format()
            expected = sum(self._counter.count(profile.format(texts[k], "query")) for k in missing)
            if expected > self._settings.max_embedding_input_tokens:
                raise ValueError("request_dense_embedding_input_exceeded")
            start = len(budget.receipts)
            budget.remaining_seconds()
            result = await self._embeddings.embed(
                [texts[k] for k in missing], role="query", format=profile, budget=budget
            )
            receipts = budget.receipts[start:]
            if (
                type(result) is not EmbeddingResult
                or result.requested_model != self._settings.openrouter_embedding_model
                or result.dimensions != 4096
                or result.format_version != profile.version
                or len(result.vectors) != len(missing)
                or len(receipts) != 1
                or result.receipts != receipts
            ):
                raise ValueError("request_dense_embedding_result_invalid")
            attempt = receipts[0]
            if (
                attempt.kind != "embedding"
                or attempt.operation != 1
                or attempt.attempt != 1
                or attempt.status_code != 200
                or attempt.outcome != "success"
                or attempt.requested_model != self._settings.openrouter_embedding_model
                or attempt.reported_model
                not in {None, self._settings.openrouter_embedding_model, profile.reported_model}
                or attempt.provider not in {None, "DeepInfra"}
                or attempt.input_reserved != expected
                or attempt.output_reserved != 0
                or attempt.count_basis != "exact"
                or attempt.count_profile != self._counter.version + ":deepinfra-us-v1"
                or attempt.usage.input_tokens not in {None, expected}
                or attempt.usage.total_tokens not in {None, expected}
            ):
                raise ValueError("request_dense_embedding_receipt_invalid")
            # Request-local only. Never persist user queries or new vectors here.
            vectors.update(zip(missing, (_vector(v) for v in result.vectors), strict=True))
        budget.remaining_seconds()
        rows = [RetrievedPart(part_id=q.part_id, chunk_ids=()) for q in copied]
        semaphore = asyncio.Semaphore(min(self._settings.retrieval_concurrency, len(copied)))

        async def read(index: int) -> None:
            if not points[index]:
                return
            async with semaphore, asyncio.timeout(budget.remaining_seconds()):
                hits = await self._reader.search(
                    vectors[keys[index]],
                    limit=self._settings.retrieval_top_k_per_question,
                    point_ids=points[index],
                )
                rows[index] = RetrievedPart(
                    part_id=copied[index].part_id, chunk_ids=tuple(h.chunk.chunk_id for h in hits)
                )

        try:
            async with asyncio.TaskGroup() as group:
                for index in range(len(copied)):
                    group.create_task(read(index))
        except Exception:
            raise ValueError("request_dense_read_failed") from None
        return RetrievalBatch(
            snapshot_id=self._snapshot,
            prepared_digest=self._catalog.prepared_digest,
            parts=tuple(rows),
        )
