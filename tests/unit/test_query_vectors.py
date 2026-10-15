"""Synthetic counters/providers only; no real tokenizer, credential or socket is used."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.indexing import EmbeddingCache
from telescope_rag.providers.contracts import AttemptReceipt, EmbeddingResult, UsageReport
from telescope_rag.providers.qwen_tokenizer import hosted_qwen_format
from telescope_rag.retrieval.query_vectors import QueryText, embed_queries, plan_queries

CONFIG = "a" * 64
COUNTER = SimpleNamespace(verified=True, count=lambda text: len(text.split()))


class FakeProvider:
    def __init__(self, bad=False):
        self.calls = []
        self.bad = bad

    async def embed(self, texts, *, role, format, budget):
        self.calls.append((tuple(texts), role, format))
        count = sum(COUNTER.count(format.format(text, role)) for text in texts)
        attempt = AttemptReceipt(
            operation=1,
            kind="embedding",
            attempt=1,
            requested_model="qwen/qwen3-embedding-8b",
            reported_model="Qwen/Qwen3-Embedding-8B",
            provider="DeepInfra",
            status_code=200,
            outcome="success",
            input_reserved=count,
            output_reserved=0,
            count_profile="synthetic-counter",
            count_basis="exact",
            usage=UsageReport(input_tokens=count, total_tokens=count),
        )
        budget.record(attempt)
        return EmbeddingResult(
            vectors=tuple((0.0 if self.bad else 1.0,) * 4096 for _ in texts),
            requested_model="qwen/qwen3-embedding-8b",
            dimensions=4096,
            format_version=format.version,
            receipts=budget.receipts,
        )


def settings():
    return Settings(
        _env_file=None,
        openrouter_api_key="",
        qdrant_api_key="",
        provider_max_retries=0,
        max_embedding_batch_size=16,
    )


def test_plan_counts_complete_prefix_and_keeps_ids_for_exact_query_reuse():
    queries = (QueryText("ar", "من الطبيب؟"), QueryText("again", "من الطبيب؟"))
    plan = plan_queries(queries, COUNTER, CONFIG)
    assert plan["unique_inputs"] == 1
    assert len(plan["queries"]) == 2
    assert plan["total_input_tokens"] == COUNTER.count(
        hosted_qwen_format().format(queries[0].text, "query")
    )
    assert plan["batches"][0][0]["query_ids"] == ["ar", "again"]
    changed = plan_queries(queries, COUNTER, "b" * 64)
    assert changed["queries"][0]["key"] != plan["queries"][0]["key"]


@pytest.mark.parametrize(
    "queries,options",
    [
        ([], {}),
        ([QueryText("x", "")], {}),
        ([QueryText("x", "hello"), QueryText("x", "world")], {}),
        ([QueryText("x", "a" * 4001)], {}),
        ([QueryText("x", "hello")], {"batch_size": True}),
        ([QueryText("x", "hello")], {"batch_size": 17}),
        ([QueryText("x", "hello")], {"max_input_tokens": 1}),
        ([QueryText(str(i), str(i)) for i in range(17)], {"max_requests": 1}),
    ],
)
def test_invalid_or_understated_plan_stops(queries, options):
    with pytest.raises(ValueError):
        plan_queries(queries, COUNTER, CONFIG, **options)


def test_query_role_literal_language_cache_and_second_run_zero_calls(tmp_path):
    queries = (QueryText("ar", "بدي أعرف ساعات الطبيب؟"), QueryText("en", "Not available?"))
    provider, receipts = FakeProvider(), []
    cache = EmbeddingCache(tmp_path)

    async def scenario():
        first, summary = await embed_queries(
            queries,
            provider=provider,
            settings=settings(),
            counter=COUNTER,
            configuration_hash=CONFIG,
            cache=cache,
            receipt=receipts.append,
        )
        assert len(provider.calls) == 1 and summary["embedding_calls"] == 1
        assert provider.calls[0][0] == tuple(q.text for q in queries)
        assert provider.calls[0][1] == "query"
        assert set(first) == {"ar", "en"}
        second, summary = await embed_queries(
            queries,
            provider=provider,
            settings=settings(),
            counter=COUNTER,
            configuration_hash=CONFIG,
            cache=cache,
            receipt=receipts.append,
        )
        assert first == second and summary["embedding_calls"] == 0
        assert len(provider.calls) == 1 and len(receipts) == 1

    asyncio.run(scenario())


def test_corruption_in_later_batch_stops_before_any_provider_call(tmp_path):
    queries = [QueryText(str(i), f"unique {i}") for i in range(17)]
    plan = plan_queries(queries, COUNTER, CONFIG)
    key = plan["queries"][-1]["key"]
    (tmp_path / f"{key}.json").write_text(json.dumps({"vector": []}), encoding="utf-8")
    provider = FakeProvider()

    async def scenario():
        with pytest.raises(ValueError, match="invalid_embedding_cache"):
            await embed_queries(
                queries,
                provider=provider,
                settings=settings(),
                counter=COUNTER,
                configuration_hash=CONFIG,
                cache=EmbeddingCache(tmp_path),
                receipt=lambda _: None,
            )
        assert not provider.calls

    asyncio.run(scenario())


def test_invalid_whole_batch_writes_no_partial_cache_and_records_failure(tmp_path):
    provider, receipts = FakeProvider(bad=True), []

    async def scenario():
        with pytest.raises(ValueError, match="query_embedding_vector_invalid"):
            await embed_queries(
                [QueryText("en", "Where is the clinic?")],
                provider=provider,
                settings=settings(),
                counter=COUNTER,
                configuration_hash=CONFIG,
                cache=EmbeddingCache(tmp_path),
                receipt=receipts.append,
            )
        assert len(provider.calls) == 1 and receipts[0]["outcome"] == "failed"
        assert not list(tmp_path.glob("*.json"))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "Other"},
        {"reported_model": None},
        {"reported_model": "different-model"},
        {"attempt": 2},
        {"status_code": 201},
        {"input_reserved": 1},
        {"usage": UsageReport(input_tokens=1, total_tokens=1)},
    ],
)
def test_unverified_provider_or_usage_receipt_never_enters_cache(tmp_path, change):
    class ChangedReceiptProvider(FakeProvider):
        async def embed(self, texts, *, role, format, budget):
            result = await super().embed(texts, role=role, format=format, budget=budget)
            modified = replace(result.receipts[0], **change)
            budget._receipts[:] = [modified]
            return replace(result, receipts=(modified,))

    provider, receipts = ChangedReceiptProvider(), []

    async def scenario():
        with pytest.raises(ValueError, match="query_embedding_receipt_invalid"):
            await embed_queries(
                [QueryText("en", "Who is the doctor?")],
                provider=provider,
                settings=settings(),
                counter=COUNTER,
                configuration_hash=CONFIG,
                cache=EmbeddingCache(tmp_path),
                receipt=receipts.append,
            )
        assert len(provider.calls) == 1
        assert receipts[0]["outcome"] == "failed"
        assert not list(tmp_path.glob("*.json"))

    asyncio.run(scenario())
