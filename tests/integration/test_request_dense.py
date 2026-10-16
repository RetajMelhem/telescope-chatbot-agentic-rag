"""Actual embedding/reader bridge mechanics with a synthetic tokenizer and mock transports."""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from test_dependency_context import owned_fixture
from test_offline_workflow import catalog as make_catalog
from tokenizers import Tokenizer, models, pre_tokenizers, processors

from telescope_rag.core.settings import Settings
from telescope_rag.graph.contracts import RetrievalQuery
from telescope_rag.ingestion.indexing import (
    EmbeddingCache,
    EmbeddingConfiguration,
    configuration_hash,
)
from telescope_rag.ingestion.models import stable_id
from telescope_rag.providers import qwen_tokenizer as qwen
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.retrieval.assembly import SourceScope
from telescope_rag.retrieval.candidate import CandidateDenseReader
from telescope_rag.retrieval.query_vectors import QueryText, plan_queries
from telescope_rag.retrieval.request_dense import RequestDenseRetriever, query_cache_key

COLLECTION = "telescope_public_" + "b" * 24
VECTOR = (1.0,) + (0.0,) * 4095


@pytest.fixture
def fixture_tokenizer(tmp_path, monkeypatch):
    # Tiny tokenizer verifies plumbing only. It is not the real Qwen artifact;
    # the production hash guard is replaced only within these guarded tests.
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "[END]": 1}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="$A [END]", special_tokens=[("[END]", 1)]
    )
    raw = tokenizer.to_str().encode()
    path = tmp_path / "synthetic-tokenizer.json"
    path.write_bytes(raw)
    monkeypatch.setattr(qwen, "TOKENIZER_SHA256", hashlib.sha256(raw).hexdigest())
    return path


@asynccontextmanager
async def environment(path, *, mode="normal", cache=None, settings=None, chat_handler=None):
    settings = settings or Settings(
        _env_file=None,
        app_env="test",
        openrouter_api_key="synthetic-only",
        provider_max_retries=0,
        max_embedding_batch_size=16,
        retrieval_top_k_per_question=2,
    )
    main, other, profile, _, _ = owned_fixture()
    format = qwen.hosted_qwen_format()
    values = tuple(
        c.model_copy(
            update={
                "tokenizer_version": qwen.COUNT_PROFILE,
                "embedding_format_version": format.version,
                "embedding_format_hash": stable_id("embedding-format-v1", format.model_dump_json()),
                "canonical_doctor_id": "canonical-" + c.doctor_id,
                "canonical_doctor_name": "Synthetic canonical " + c.doctor_id,
            }
        )
        for c in (main, other, profile)
    )
    evidence = make_catalog(*values)
    config = EmbeddingConfiguration(
        model=settings.openrouter_embedding_model,
        dimensions=4096,
        format_version=format.version,
        format_hash=stable_id("embedding-format-v1", format.model_dump_json()),
        preparation_version=values[0].preparation_version,
        tokenizer_version=qwen.COUNT_PROFILE,
    )
    counter = qwen.QwenPreparationCounter(path)
    embedding_calls = []
    read_calls = []
    inventory = {c.point_id: c for c in values}

    def embedding_handler(request):
        if request.url.path == "/api/v1/chat/completions":
            assert chat_handler is not None
            return chat_handler(request)
        body = json.loads(request.read())
        embedding_calls.append(body)
        assert request.url.path == "/api/v1/embeddings"
        assert body["provider"] == {
            "only": ["deepinfra/us"],
            "require_parameters": True,
            "allow_fallbacks": False,
        }
        total = sum(counter.count(t) for t in body["input"])
        vectors = [{"index": i, "embedding": list(VECTOR)} for i in range(len(body["input"]))]
        if mode == "bad_vector":
            vectors[-1]["embedding"] = [0.0] * 4096
        if mode == "bad_dimension":
            vectors[-1]["embedding"] = [1.0] * 32
        result = {
            "model": "Elsewhere/model" if mode == "bad_model" else "Qwen/Qwen3-Embedding-8B",
            "provider": "Elsewhere" if mode == "bad_provider" else "DeepInfra",
            "data": vectors[::-1],
            "usage": {"prompt_tokens": total, "total_tokens": total},
        }
        if mode == "missing_metadata":
            for key in ("model", "provider", "usage"):
                result.pop(key)
        elif mode == "bad_usage":
            result["usage"] = {"prompt_tokens": total - 1, "total_tokens": total - 1}
        return httpx.Response(200, json=result)

    def reader_handler(request):
        body = json.loads(request.read())
        read_calls.append(body)
        assert (
            request.method == "POST"
            and request.url.path == f"/collections/{COLLECTION}/points/query"
        )
        assert request.headers["api-key"] == "synthetic-reader"
        assert body["params"] == {"exact": True}
        assert body["with_payload"] is True and body["with_vector"] is False
        ids = body["filter"]["must"][0]["has_id"]
        if mode == "foreign_point":
            ids = [values[1].point_id]
        hits = [
            {"id": i, "score": 1.0 - index / 10, "payload": inventory[i].model_dump(mode="json")}
            for index, i in enumerate(ids[: body["limit"]])
        ]
        if mode == "bad_payload":
            hits[0]["payload"]["original_text"] = "Altered source."
        elif mode == "empty_results":
            hits = []
        return httpx.Response(200, json={"status": "ok", "result": {"points": hits}})

    async with OpenRouterProviders(
        settings,
        token_counter=qwen.QwenEmbeddingCounter(path),
        transport=httpx.MockTransport(embedding_handler),
    ) as providers:
        reader = CandidateDenseReader(
            settings,
            SecretStr("synthetic-reader"),
            collection=COLLECTION,
            chunks=inventory,
            transport=httpx.MockTransport(reader_handler),
        )
        try:
            bridge = RequestDenseRetriever(
                settings=settings,
                catalog=evidence,
                configuration=config,
                counter=counter,
                embeddings=providers.embeddings,
                reader=reader,
                cache=cache,
            )
            yield SimpleNamespace(
                settings=settings,
                catalog=evidence,
                configuration=config,
                counter=counter,
                providers=providers,
                reader=reader,
                bridge=bridge,
                values=values,
                embeddings=embedding_calls,
                reads=read_calls,
            )
        finally:
            await reader.aclose()


def query(part="p1", text="Report the published role; do not infer training.", **scope):
    return RetrievalQuery(part_id=part, text=text, scope=SourceScope(**scope))


async def retrieve(env, queries, *, budget=None, **changes):
    return await env.bridge.retrieve(
        queries,
        snapshot_id=changes.get("snapshot_id", env.values[0].snapshot_id),
        prepared_digest=changes.get("prepared_digest", env.catalog.prepared_digest),
        budget=budget or ExecutionBudget(env.settings),
    )


@pytest.mark.parametrize(
    "text",
    ["What role, not training?", "ما دوره المنشور وليس مؤهلاته؟", "شو دوره المكتوب، مش مؤهلاته؟"],
)
def test_literal_queries_use_exact_hosted_prefix_one_batch_and_scoped_points(
    fixture_tokenizer, text
):
    async def run():
        async with environment(fixture_tokenizer) as env:
            budget = ExecutionBudget(env.settings)
            result = await retrieve(
                env,
                [
                    query(
                        text=text,
                        document_ids=("main",),
                        owner_id="a",
                        block_types=("doctor",),
                        language="en",
                    )
                ],
                budget=budget,
            )
            assert env.embeddings[0]["input"] == [qwen.QUERY_PREFIX + text]
            assert len(env.embeddings) == len(env.reads) == 1
            assert env.reads[0]["filter"] == {"must": [{"has_id": [env.values[0].point_id]}]}
            assert result.parts[0].chunk_ids == (env.values[0].chunk_id,)
            assert (
                result.snapshot_id == env.values[0].snapshot_id
                and result.prepared_digest == env.catalog.prepared_digest
            )
            assert budget.operations["embedding"] == 1 and budget.attempts["embedding"] == 1
            assert budget.receipts[0].requested_model == "qwen/qwen3-embedding-8b"
            assert budget.receipts[0].reported_model == "Qwen/Qwen3-Embedding-8B"

    asyncio.run(run())


@pytest.mark.parametrize(
    "owner_kind,owners", [("literal", ("a", "b")), ("canonical", ("canonical-a", "canonical-b"))]
)
def test_same_query_vector_dedup_keeps_two_owners_and_part_ids(
    fixture_tokenizer, owner_kind, owners
):
    async def run():
        async with environment(fixture_tokenizer) as env:
            rows = [
                query(
                    part=f"p{i}",
                    text="Which published specialty?",
                    document_ids=("main",),
                    owner_id=owner,
                    owner_kind=owner_kind,
                )
                for i, owner in enumerate(owners)
            ]
            result = await retrieve(env, rows)
            assert (
                len(env.embeddings) == 1
                and len(env.embeddings[0]["input"]) == 1
                and len(env.reads) == 2
            )
            assert [r.part_id for r in result.parts] == ["p0", "p1"]
            assert [r.chunk_ids for r in result.parts] == [
                (env.values[0].chunk_id,),
                (env.values[1].chunk_id,),
            ]
            assert {tuple(r["filter"]["must"][0]["has_id"]) for r in env.reads} == {
                (env.values[0].point_id,),
                (env.values[1].point_id,),
            }

    asyncio.run(run())


def test_cache_identity_matches_historical_recipe_and_preserves_language_punctuation():
    config = "a" * 64
    counter = SimpleNamespace(verified=True, count=lambda text: 1)
    for text in ("Role?", "Role!", "دور؟", qwen.QUERY_PREFIX + "literal user text"):
        plan = plan_queries([QueryText("p", text)], counter, config)
        assert query_cache_key(text, config) == plan["queries"][0]["key"]
    assert query_cache_key("Role?", config) != query_cache_key("Role!", config)
    assert query_cache_key("Role?", config) != query_cache_key("Role?", "b" * 64)


@pytest.mark.parametrize("cached", [0, 1, 2])
def test_cache_hits_and_misses_are_exact_read_only_and_not_persisted(
    fixture_tokenizer, tmp_path, cached
):
    async def run():
        cache = EmbeddingCache(tmp_path / "query-cache")
        async with environment(fixture_tokenizer, cache=cache) as env:
            rows = [
                query(part=f"p{i}", text=t, document_ids=("main",), owner_id="a")
                for i, t in enumerate(("Role?", "Training?"))
            ]
            cfg = configuration_hash(env.configuration)
            for row in rows[:cached]:
                cache.put(query_cache_key(row.text, cfg), cfg, VECTOR)
            before = {p.name: p.read_bytes() for p in cache.directory.iterdir()}
            budget = ExecutionBudget(env.settings)
            result = await retrieve(env, rows, budget=budget)
            assert len(result.parts) == 2 and len(env.reads) == 2
            assert len(env.embeddings) == (0 if cached == 2 else 1)
            if cached < 2:
                assert len(env.embeddings[0]["input"]) == 2 - cached
            assert budget.operations["embedding"] == (0 if cached == 2 else 1)
            assert {p.name: p.read_bytes() for p in cache.directory.iterdir()} == before

    asyncio.run(run())


def test_corrupt_relevant_cache_fails_before_any_embedding_or_database_read(
    fixture_tokenizer, tmp_path
):
    async def run():
        cache = EmbeddingCache(tmp_path / "query-cache")
        async with environment(fixture_tokenizer, cache=cache) as env:
            cfg = configuration_hash(env.configuration)
            (cache.directory / (query_cache_key("Corrupt?", cfg) + ".json")).write_text("{}")
            with pytest.raises(ValueError, match="invalid_embedding_cache"):
                await retrieve(env, [query(text="Missing?"), query(part="p2", text="Corrupt?")])
            assert not env.embeddings and not env.reads

    asyncio.run(run())


@pytest.mark.parametrize(
    "case",
    ["empty", "too_many", "duplicate", "snapshot", "digest", "document", "complete", "blank"],
)
def test_invalid_requests_stop_before_paid_dispatch(fixture_tokenizer, case):
    async def run():
        async with environment(fixture_tokenizer) as env:
            rows = [query()]
            changes = {}
            if case == "empty":
                rows = []
            elif case == "too_many":
                rows = [query(part=f"p{i}") for i in range(5)]
            elif case == "duplicate":
                rows = [query(), query()]
            elif case == "snapshot":
                changes = {"snapshot_id": "other"}
            elif case == "digest":
                changes = {"prepared_digest": "other"}
            elif case == "document":
                rows = [query(document_ids=("unknown",))]
            elif case == "complete":
                rows = [query(document_ids=("main",), complete=True)]
            elif case == "blank":
                rows = [query(text=" ")]
            with pytest.raises(ValueError):
                await retrieve(env, rows, **changes)
            assert not env.embeddings and not env.reads

    asyncio.run(run())


def test_empty_known_source_intersection_does_not_embed_or_fall_back(fixture_tokenizer):
    async def run():
        async with environment(fixture_tokenizer) as env:
            result = await retrieve(env, [query(document_ids=("main",), language="ar")])
            assert result.parts[0].chunk_ids == () and not env.embeddings and not env.reads

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode", ["bad_vector", "bad_dimension", "bad_model", "bad_provider", "bad_usage"]
)
def test_invalid_embedding_result_blocks_all_reads_without_retry(fixture_tokenizer, mode):
    async def run():
        async with environment(fixture_tokenizer, mode=mode) as env:
            with pytest.raises((ProviderError, ValueError)):
                await retrieve(env, [query()])
            assert len(env.embeddings) == 1 and not env.reads

    asyncio.run(run())


def test_missing_optional_embedding_metadata_stays_unknown_with_counted_reservation(
    fixture_tokenizer,
):
    async def run():
        async with environment(fixture_tokenizer, mode="missing_metadata") as env:
            budget = ExecutionBudget(env.settings)
            result = await retrieve(env, [query()], budget=budget)
            assert result.parts[0].chunk_ids and budget.receipts[0].usage.input_tokens is None
            assert budget.receipts[0].reported_model is None and budget.receipts[0].provider is None
            assert budget.input_charged["embedding"] == budget.receipts[0].input_reserved

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["foreign_point", "bad_payload"])
def test_outside_scope_or_altered_source_payload_fails_the_entire_read(fixture_tokenizer, mode):
    async def run():
        async with environment(fixture_tokenizer, mode=mode) as env:
            with pytest.raises(ValueError, match="request_dense_read_failed"):
                await retrieve(env, [query(document_ids=("main",), owner_id="a")])
            assert len(env.embeddings) == len(env.reads) == 1

    asyncio.run(run())


def test_expired_shared_budget_blocks_before_dispatch(fixture_tokenizer):
    async def run():
        async with environment(fixture_tokenizer) as env:
            clock = [0.0]
            budget = ExecutionBudget(env.settings, clock=lambda: clock[0])
            clock[0] = 1000.0
            with pytest.raises(ProviderError, match="execution_budget_exhausted"):
                await retrieve(env, [query()], budget=budget)
            assert not env.embeddings and not env.reads

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("format_hash", "incorrect"),
        ("format_version", "unverified"),
        ("tokenizer_version", "different"),
    ],
)
def test_constructor_rejects_configuration_drift_before_dispatch(fixture_tokenizer, field, value):
    async def run():
        async with environment(fixture_tokenizer) as env:
            changed = env.configuration.model_copy(update={field: value})
            with pytest.raises(ValueError):
                RequestDenseRetriever(
                    settings=env.settings,
                    catalog=env.catalog,
                    configuration=changed,
                    counter=env.counter,
                    embeddings=env.providers.embeddings,
                    reader=env.reader,
                )
            assert not env.embeddings and not env.reads

    asyncio.run(run())


@pytest.mark.parametrize(
    "case", ["production", "retries", "limit", "counter", "model", "dimensions", "reader_settings"]
)
def test_constructor_rejects_unverified_or_mismatched_dependencies(fixture_tokenizer, case):
    async def run():
        async with environment(fixture_tokenizer) as env:
            options = {
                "settings": env.settings,
                "catalog": env.catalog,
                "configuration": env.configuration,
                "counter": env.counter,
                "embeddings": env.providers.embeddings,
                "reader": env.reader,
            }
            if case == "production":
                options["settings"] = env.settings.model_copy(update={"app_env": "production"})
            elif case == "retries":
                options["settings"] = env.settings.model_copy(update={"provider_max_retries": 1})
            elif case == "limit":
                options["settings"] = env.settings.model_copy(
                    update={"retrieval_top_k_per_question": 21}
                )
            elif case == "counter":
                options["counter"] = SimpleNamespace(
                    verified=True, version=qwen.COUNT_PROFILE, model=qwen.QWEN_MODEL
                )
            elif case == "model":
                options["configuration"] = env.configuration.model_copy(
                    update={"model": "other-model"}
                )
            elif case == "dimensions":
                options["configuration"] = env.configuration.model_copy(update={"dimensions": 32})
            elif case == "reader_settings":
                options["settings"] = env.settings.model_copy(update={"retrieval_concurrency": 1})
            with pytest.raises(ValueError):
                RequestDenseRetriever(**options)
            assert not env.embeddings and not env.reads

    asyncio.run(run())


def test_concurrent_requests_keep_separate_budgets_without_private_vector_warmup(fixture_tokenizer):
    async def run():
        async with environment(fixture_tokenizer) as env:
            budgets = [ExecutionBudget(env.settings), ExecutionBudget(env.settings)]
            results = await asyncio.gather(
                *(
                    retrieve(
                        env,
                        [
                            query(
                                part=f"request-{i}",
                                text="Same exact wording?",
                                document_ids=("main",),
                                owner_id=owner,
                            )
                        ],
                        budget=budget,
                    )
                    for i, (owner, budget) in enumerate(zip(("a", "b"), budgets, strict=True))
                )
            )
            assert len(env.embeddings) == 2 and len(env.reads) == 2
            for i, (result, budget) in enumerate(zip(results, budgets, strict=True)):
                assert result.parts[0].part_id == f"request-{i}"
                assert result.parts[0].chunk_ids == (env.values[i].chunk_id,)
                assert budget.operations["embedding"] == budget.attempts["embedding"] == 1
            assert budgets[0] is not budgets[1]

    asyncio.run(run())


def test_cancelling_request_cancels_all_parallel_database_reads(fixture_tokenizer):
    async def run():
        async with environment(fixture_tokenizer) as env:
            entered = asyncio.Event()
            waiting = []
            cancelled = []

            async def slow_reader(request):
                body = json.loads(request.read())
                waiting.append(body)
                if len(waiting) == 2:
                    entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(1)

            client = CandidateDenseReader(
                env.settings,
                SecretStr("synthetic-reader"),
                collection=COLLECTION,
                chunks={c.point_id: c for c in env.values},
                transport=httpx.MockTransport(slow_reader),
            )
            try:
                bridge = RequestDenseRetriever(
                    settings=env.settings,
                    catalog=env.catalog,
                    configuration=env.configuration,
                    counter=env.counter,
                    embeddings=env.providers.embeddings,
                    reader=client,
                )
                task = asyncio.create_task(
                    bridge.retrieve(
                        [query(part="p1", owner_id="a"), query(part="p2", owner_id="b")],
                        snapshot_id=env.values[0].snapshot_id,
                        prepared_digest=env.catalog.prepared_digest,
                        budget=ExecutionBudget(env.settings),
                    )
                )
                try:
                    await asyncio.wait_for(entered.wait(), timeout=5)
                finally:
                    task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert len(waiting) == len(cancelled) == 2 and len(env.embeddings) == 1
            finally:
                await client.aclose()

    asyncio.run(run())


def test_real_ingestion_generated_format_metadata_binds_without_rewriting(fixture_tokenizer):
    # Regression for an omitted hash namespace: use the real ingestion producer,
    # rather than manually constructing a matching format hash in the fixture.
    from datetime import UTC, datetime

    from telescope_rag.ingestion.extraction import extract_page
    from telescope_rag.ingestion.models import RawPage
    from telescope_rag.ingestion.preparation import prepare_document
    from telescope_rag.ingestion.review import prepared_digest
    from telescope_rag.retrieval.assembly import EvidenceCatalog

    async def run():
        counter = qwen.QwenPreparationCounter(fixture_tokenizer)
        page = RawPage(
            snapshot_id="synthetic-ingestion",
            document_id="synthetic-document",
            canonical_url="https://telescopecenter.com/synthetic-ingestion/",
            fetched_at=datetime(2026, 10, 16, tzinfo=UTC),
            content_hash="synthetic-html",
            html=(
                "<html><head><title>Synthetic source</title></head><body><main>"
                "<h1>Synthetic source</h1><p>Example public information for a test only.</p>"
                "</main></body></html>"
            ),
        )
        prepared = prepare_document(
            extract_page(page), counter=counter, embedding_format=qwen.hosted_qwen_format()
        )
        assert prepared.chunks and all(c.embedding_ready for c in prepared.chunks)
        first = prepared.chunks[0]
        evidence = EvidenceCatalog((prepared,), expected_digest=prepared_digest((prepared,)))
        config = EmbeddingConfiguration(
            format_version=first.embedding_format_version,
            format_hash=first.embedding_format_hash,
            preparation_version=first.preparation_version,
            tokenizer_version=first.tokenizer_version,
        )
        settings = Settings(_env_file=None, app_env="test", provider_max_retries=0)
        client = CandidateDenseReader(
            settings,
            SecretStr("synthetic-reader"),
            collection=COLLECTION,
            chunks={c.point_id: c for c in prepared.chunks},
            transport=httpx.MockTransport(
                lambda request: pytest.fail("Construction must not dispatch")
            ),
        )
        try:
            RequestDenseRetriever(
                settings=settings,
                catalog=evidence,
                configuration=config,
                counter=counter,
                embeddings=SimpleNamespace(embed=None),
                reader=client,
            )
            assert (
                evidence.chunks[first.chunk_id].embedding_format_hash == first.embedding_format_hash
            )
        finally:
            await client.aclose()

    asyncio.run(run())
