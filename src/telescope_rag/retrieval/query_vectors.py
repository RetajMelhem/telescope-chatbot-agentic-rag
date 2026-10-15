"""Explicit query-only embedding/cache stage; independent of corpus indexing and API startup."""

import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.indexing import EmbeddingCache
from telescope_rag.ingestion.models import stable_id
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import EmbeddingProvider
from telescope_rag.providers.qwen_tokenizer import QwenPreparationCounter, hosted_qwen_format


@dataclass(frozen=True)
class QueryText:
    query_id: str
    text: str


def plan_queries(
    queries: Sequence[QueryText],
    counter: QwenPreparationCounter,
    configuration_hash: str,
    *,
    batch_size: int = 16,
    max_requests: int = 6,
    max_input_tokens: int = 4758,
) -> dict:
    """Count complete query formatting; reject understating budgets before any dispatch."""
    if (
        not 0 < len(queries) <= 1000
        or type(batch_size) is not int
        or not 1 <= batch_size <= 16
        or type(max_requests) is not int
        or not 1 <= max_requests <= 100
        or type(max_input_tokens) is not int
        or not 1 <= max_input_tokens <= 100000
        or len(configuration_hash) != 64
        or any(c not in "0123456789abcdef" for c in configuration_hash)
        or not counter.verified
    ):
        raise ValueError("query_embedding_plan_invalid")
    profile = hosted_qwen_format()
    ids, groups, rows = set(), {}, []
    for query in queries:
        if (
            not isinstance(query, QueryText)
            or not isinstance(query.query_id, str)
            or not query.query_id.strip()
            or len(query.query_id) > 128
            or query.query_id in ids
            or not isinstance(query.text, str)
            or not query.text.strip()
            or len(query.text) > 4000
        ):
            raise ValueError("query_embedding_input_invalid")
        ids.add(query.query_id)
        formatted = profile.format(query.text, "query")
        count = counter.count(formatted)
        if type(count) is not int or not 1 <= count <= 16000:
            raise ValueError("query_embedding_count_invalid")
        key = stable_id(
            "retrieval-query-v1", configuration_hash, profile.model_dump_json(), formatted
        )
        groups.setdefault(key, {"key": key, "tokens": count, "query_ids": []})
        groups[key]["query_ids"].append(query.query_id)
        rows.append({"query_id": query.query_id, "key": key, "tokens": count})
    unique = list(groups.values())
    batches = [unique[i : i + batch_size] for i in range(0, len(unique), batch_size)]
    total = sum(row["tokens"] for row in unique)
    if (
        total > max_input_tokens
        or len(batches) > max_requests
        or any(sum(row["tokens"] for row in batch) > 16000 for batch in batches)
    ):
        raise ValueError("query_embedding_budget_exceeded")
    return {
        "role": "query",
        "configuration_hash": configuration_hash,
        "format_version": profile.version,
        "queries": rows,
        "unique_inputs": len(unique),
        "total_input_tokens": total,
        "batch_size": batch_size,
        "max_requests": max_requests,
        "max_input_tokens": max_input_tokens,
        "batches": batches,
        "retries": 0,
        "provider_only": ["deepinfra/us"],
        "allow_fallbacks": False,
    }


async def embed_queries(
    queries: Sequence[QueryText],
    *,
    provider: EmbeddingProvider,
    settings: Settings,
    counter: QwenPreparationCounter,
    configuration_hash: str,
    cache: EmbeddingCache,
    receipt: Callable[[dict], None],
    max_requests: int = 6,
    max_input_tokens: int = 4758,
) -> tuple[dict[str, tuple[float, ...]], dict]:
    if settings.provider_max_retries != 0 or settings.embedding_dimensions != 4096:
        raise ValueError("query_embedding_profile_invalid")
    plan = plan_queries(
        queries,
        counter,
        configuration_hash,
        batch_size=settings.max_embedding_batch_size,
        max_requests=max_requests,
        max_input_tokens=max_input_tokens,
    )
    vectors, representatives = {}, {}
    texts = {query.query_id: query.text for query in queries}
    # Validate every existing relevant cache file before the first provider call.
    for row in plan["queries"]:
        representatives.setdefault(row["key"], texts[row["query_id"]])
    for key in representatives:
        found = cache.get(key, configuration_hash, 4096)
        if found is not None:
            vectors[key] = found
    before = len(vectors)
    calls = tokens = 0
    profile = hosted_qwen_format()
    for batch in plan["batches"]:
        missing = [row for row in batch if row["key"] not in vectors]
        if not missing:
            continue
        reserved = sum(row["tokens"] for row in missing)
        if calls + 1 > max_requests or tokens + reserved > max_input_tokens:
            raise ValueError("query_embedding_budget_exceeded")
        calls += 1
        tokens += reserved
        budget = ExecutionBudget(settings)
        outcome = "failed"
        try:
            result = await provider.embed(
                [representatives[row["key"]] for row in missing],
                role="query",
                format=profile,
                budget=budget,
            )
            if (
                result.requested_model != settings.openrouter_embedding_model
                or result.dimensions != 4096
                or result.format_version != profile.version
                or len(result.vectors) != len(missing)
            ):
                raise ValueError("query_embedding_result_invalid")
            if len(result.receipts) != 1 or result.receipts != budget.receipts:
                raise ValueError("query_embedding_receipt_invalid")
            attempt = result.receipts[0]
            if (
                attempt.kind != "embedding"
                or attempt.operation != 1
                or attempt.attempt != 1
                or attempt.status_code != 200
                or attempt.outcome != "success"
                or attempt.requested_model != settings.openrouter_embedding_model
                or attempt.reported_model
                not in {settings.openrouter_embedding_model, profile.reported_model}
                or attempt.provider != "DeepInfra"
                or attempt.input_reserved != reserved
                or attempt.output_reserved != 0
                or attempt.count_basis != "exact"
                or attempt.usage.input_tokens != reserved
                or attempt.usage.total_tokens != reserved
            ):
                raise ValueError("query_embedding_receipt_invalid")
            # Validate the whole batch before persisting any of it.
            for vector in result.vectors:
                if (
                    len(vector) != 4096
                    or any(type(v) not in {int, float} or not math.isfinite(v) for v in vector)
                    or not any(vector)
                ):
                    raise ValueError("query_embedding_vector_invalid")
            for row, vector in zip(missing, result.vectors, strict=True):
                cache.put(row["key"], configuration_hash, vector)
                vectors[row["key"]] = vector
            outcome = "success"
        finally:
            receipt(
                {
                    "batch": calls,
                    "inputs": len(missing),
                    "input_reserved": reserved,
                    "cumulative_reserved": tokens,
                    "outcome": outcome,
                    "attempts": [
                        {**asdict(a), "usage": a.usage.model_dump(mode="json")}
                        for a in budget.receipts
                    ],
                }
            )
    return (
        {row["query_id"]: vectors[row["key"]] for row in plan["queries"]},
        {
            "queries": len(queries),
            "unique_inputs": plan["unique_inputs"],
            "cached_inputs_before": before,
            "embedding_calls": calls,
            "input_reserved": tokens,
        },
    )
