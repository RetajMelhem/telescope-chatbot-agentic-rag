"""Synthetic, socket-free tests for the unpublished candidate evaluation reader."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.models import PreparedChunk, SourceSpan
from telescope_rag.retrieval.candidate import CandidateDenseReader

COLLECTION = "telescope_public_" + "a" * 24
VECTOR = (1.0,) * 4096


def chunk(index=1):
    text = "Synthetic public source." if index == 1 else "نص مصدر تجريبي فقط."
    source = SourceSpan(
        block_id=f"source-{index}", locator="main > p", original_text=text, end=len(text)
    )
    return PreparedChunk(
        chunk_id=f"chunk-{index}",
        point_id=str(UUID(int=index)),
        document_id=f"document-{index}",
        canonical_url=f"https://telescopecenter.com/synthetic-{index}/",
        page_title="Synthetic owner",
        snapshot_id="synthetic-reader-snapshot",
        fetched_at=datetime(2026, 10, 15, tzinfo=UTC),
        parent_block_id=f"owner-{index}",
        block_type="doctor",
        language="en" if index == 1 else "ar",
        section_path=("Synthetic specialty",),
        doctor_id=f"literal-owner-{index}",
        doctor_name=f"Literal owner {index}",
        canonical_doctor_id=f"authorized-alias-{index}",
        canonical_doctor_name=f"Authorized display {index}",
        source_issue_codes=("synthetic_scope_unverified",),
        admission_policy_hash="synthetic-admission",
        source_spans=(source,),
        context_spans=(source,),
        original_text=text,
        retrieval_text=text,
        content_hash=f"synthetic-content-{index}",
        token_count=1,
        tokenizer_version="synthetic-reader-counter",
        embedding_format_version="synthetic-reader-format",
        embedding_format_hash="synthetic-format-hash",
        embedding_ready=True,
    )


def reader(handler, *, chunks=None, **settings_overrides):
    values = tuple(chunks) if chunks is not None else (chunk(), chunk(2))
    return CandidateDenseReader(
        Settings(_env_file=None, app_env="test", **settings_overrides),
        SecretStr("synthetic-reader-key"),
        collection=COLLECTION,
        chunks={item.point_id: item for item in values},
        transport=httpx.MockTransport(handler),
    )


def point(item=None, *, score=0.75):
    item = item or chunk()
    return {"id": item.point_id, "score": score, "payload": item.model_dump(mode="json")}


def response(points):
    return httpx.Response(200, json={"status": "ok", "result": {"points": points}})


def test_exact_query_body_read_key_and_complete_bilingual_payloads():
    async def scenario():
        calls = []

        def handler(request):
            calls.append((request.method, str(request.url)))
            assert request.method == "POST"
            assert (
                str(request.url) == f"http://127.0.0.1:6333/collections/{COLLECTION}/points/query"
            )
            assert request.headers["api-key"] == "synthetic-reader-key"
            assert json.loads(request.content) == {
                "query": list(VECTOR),
                "params": {"exact": True},
                "with_payload": True,
                "with_vector": False,
                "limit": 2,
            }
            return response([point(), point(chunk(2), score=0.6)])

        client = reader(handler)
        try:
            hits = await client.search(VECTOR, limit=2)
            assert len(calls) == 1
            assert [hit.score for hit in hits] == [0.75, 0.6]
            for hit, expected in zip(hits, (chunk(), chunk(2)), strict=True):
                assert hit.chunk == expected
                assert hit.chunk.source_issue_codes == ("synthetic_scope_unverified",)
                assert hit.chunk.context_spans == expected.context_spans
                assert hit.chunk.doctor_id == expected.doctor_id
                assert hit.chunk.canonical_doctor_id == expected.canonical_doctor_id
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_info_aliases_and_empty_results_are_read_only():
    async def scenario():
        calls = []
        info = {"config": {"params": {"vectors": {"size": 4096, "distance": "Cosine"}}}}

        def handler(request):
            calls.append((request.method, request.url.path))
            if request.url.path.endswith("/points/query"):
                return response([])
            result = {"aliases": []} if request.url.path == "/aliases" else info
            return httpx.Response(200, json={"status": "ok", "result": result})

        client = reader(handler)
        try:
            assert await client.info() == info
            assert await client.aliases() == []
            assert await client.search(VECTOR) == ()
            assert calls == [
                ("GET", f"/collections/{COLLECTION}"),
                ("GET", "/aliases"),
                ("POST", f"/collections/{COLLECTION}/points/query"),
            ]
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:6333/",
        "http://localhost:6333/",
        "https://127.0.0.1:6333/",
        "http://127.0.0.1:6334/",
        "http://127.0.0.1:6333/collections/",
        "http://user:synthetic@127.0.0.1:6333/",
        "http://127.0.0.1:6333/?a=b",
        "http://127.0.0.1:6333/#fragment",
    ],
)
def test_rejects_nonpinned_urls_before_transport(url):
    with pytest.raises(ValueError):
        reader(lambda request: pytest.fail("must not dispatch"), qdrant_url=url)


@pytest.mark.parametrize(
    "name",
    [
        "telescope_public_active",
        "telescope_public_" + "a" * 23,
        "telescope_public_" + "A" * 24,
        COLLECTION + "/points/query",
        "//example.com/" + COLLECTION,
        COLLECTION + "?query=1",
    ],
)
def test_rejects_aliases_and_collection_path_injection(name):
    with pytest.raises(ValueError, match="invalid_collection"):
        CandidateDenseReader(
            Settings(_env_file=None),
            SecretStr("synthetic"),
            collection=name,
            chunks={chunk().point_id: chunk()},
        )


@pytest.mark.parametrize("damage", ["empty", "key", "chunk_id", "snapshot", "config", "ready"])
def test_rejects_invalid_inventory_without_network(damage):
    values = {item.point_id: item for item in (chunk(), chunk(2))}
    if damage == "empty":
        values = {}
    elif damage == "key":
        values = {"wrong-key": chunk()}
    elif damage == "chunk_id":
        values[chunk(2).point_id] = chunk(2).model_copy(update={"chunk_id": chunk().chunk_id})
    elif damage == "snapshot":
        values[chunk(2).point_id] = chunk(2).model_copy(update={"snapshot_id": "different"})
    elif damage == "config":
        values[chunk(2).point_id] = chunk(2).model_copy(update={"embedding_format_hash": "other"})
    else:
        values[chunk(2).point_id] = chunk(2).model_copy(update={"embedding_ready": False})
    with pytest.raises(ValueError, match="inventory|mixed_snapshot"):
        CandidateDenseReader(
            Settings(_env_file=None), SecretStr("synthetic"), collection=COLLECTION, chunks=values
        )


def test_rejects_empty_read_key_and_wrong_dimensions():
    for key, dimensions in [("", 4096), ("synthetic", 32)]:
        with pytest.raises(ValueError, match="read_key_required|dimensions_mismatch"):
            CandidateDenseReader(
                Settings(_env_file=None, embedding_dimensions=dimensions),
                SecretStr(key),
                collection=COLLECTION,
                chunks={chunk().point_id: chunk()},
            )


@pytest.mark.parametrize("limit", [0, 21, True, 1.0, "2", None])
def test_invalid_limits_reject_before_dispatch(limit):
    async def scenario():
        client = reader(lambda request: pytest.fail("invalid limit must not dispatch"))
        try:
            with pytest.raises(ValueError, match="invalid_limit"):
                await client.search(VECTOR, limit=limit)
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "vector",
    [
        (),
        (1.0,) * 4095,
        (1.0,) * 4097,
        (0.0,) * 4096,
        (True,) + VECTOR[1:],
        ("1.0",) + VECTOR[1:],
        (float("nan"),) + VECTOR[1:],
        (float("inf"),) + VECTOR[1:],
        (10**1000,) + VECTOR[1:],
        (1e308,) * 4096,
    ],
)
def test_invalid_vectors_reject_before_dispatch(vector):
    async def scenario():
        client = reader(lambda request: pytest.fail("invalid vector must not dispatch"))
        try:
            with pytest.raises(ValueError, match="invalid_vector"):
                await client.search(vector)
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field,value",
    [
        ("doctor_id", "other-owner"),
        ("doctor_name", "Other doctor"),
        ("canonical_doctor_id", "other-alias"),
        ("source_issue_codes", []),
        ("source_spans", []),
        ("context_spans", []),
        ("canonical_url", "https://telescopecenter.com/other/"),
        ("snapshot_id", "other-snapshot"),
        ("retrieval_text", "A fabricated claim"),
        ("original_text", "A different qualifier"),
        ("token_count", True),
        ("token_count", 1.0),
        ("unexpected", "extra"),
    ],
)
def test_rejects_any_payload_change_including_bool_integer_equality(field, value):
    async def scenario():
        hit = point()
        hit["payload"][field] = value
        client = reader(lambda request: response([hit]))
        try:
            with pytest.raises(ValueError, match="payload_mismatch"):
                await client.search(VECTOR)
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "damage", ["duplicate", "foreign_id", "wrong_id_type", "owner_swap", "cap"]
)
def test_rejects_bad_point_identity_and_count(damage):
    async def scenario():
        points = [point()]
        if damage == "duplicate":
            points.append(point())
        elif damage == "foreign_id":
            points[0]["id"] = str(UUID(int=3))
        elif damage == "wrong_id_type":
            points[0]["id"] = 1
        elif damage == "owner_swap":
            points[0]["payload"] = chunk(2).model_dump(mode="json")
        else:
            points.append(point(chunk(2), score=0.5))
        client = reader(lambda request: response(points))
        try:
            with pytest.raises(
                ValueError, match="mapping_mismatch|payload_mismatch|invalid_points"
            ):
                await client.search(VECTOR, limit=1 if damage == "cap" else 20)
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("score", [True, None, "0.75", {}, [], 10**1000])
def test_rejects_invalid_score_types(score):
    async def scenario():
        client = reader(lambda request: response([point(score=score)]))
        try:
            with pytest.raises(ValueError, match="invalid_score"):
                await client.search(VECTOR)
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_rejects_genuinely_reversed_scores_and_preserves_close_ties():
    async def scenario():
        for second, rejected in [(0.9, True), (0.75000001, False)]:
            client = reader(
                lambda request, score=second: response([point(), point(chunk(2), score=score)])
            )
            try:
                if rejected:
                    with pytest.raises(ValueError, match="invalid_score"):
                        await client.search(VECTOR)
                else:
                    assert len(await client.search(VECTOR)) == 2
            finally:
                await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "raw,media",
    [
        (b'{"status":"ok","status":"ok","result":{"points":[]}}', "application/json"),
        (b'{"status":"ok","result":{"points":[],"x":NaN}}', "application/json"),
        (b'{"status":"ok","result":{"points":[],"x":1e999}}', "application/json"),
        (b"[]", "application/json"),
        (b"\xff", "application/json"),
        (b'{"status":"ok","result":{"points":[]}}', "text/html"),
        (b'{"status":"error","result":{"points":[]}}', "application/json"),
        (b'{"status":"ok"}', "application/json"),
    ],
)
def test_strict_json_envelope_media_and_nonfinite_rejection(raw, media):
    async def scenario():
        client = reader(
            lambda request: httpx.Response(200, content=raw, headers={"content-type": media})
        )
        try:
            with pytest.raises(ValueError, match="^candidate_reader_request_failed$"):
                await client.search(VECTOR)
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [301, 307, 401, 403, 429, 500, 503])
def test_redirects_and_http_errors_never_retry_or_leak_body(status):
    async def scenario():
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(
                status,
                text="synthetic-sensitive-upstream",
                headers={"location": "https://evil.test"},
            )

        client = reader(handler)
        try:
            with pytest.raises(ValueError, match="^candidate_reader_request_failed$") as caught:
                await client.search(VECTOR)
            assert "synthetic-sensitive" not in str(caught.value)
            assert len(calls) == 1
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_request_size_cap_precedes_dispatch(monkeypatch):
    monkeypatch.setattr("telescope_rag.retrieval.candidate.MAX_CANDIDATE_REQUEST_BYTES", 100)

    async def scenario():
        client = reader(lambda request: pytest.fail("oversized request must not dispatch"))
        try:
            with pytest.raises(ValueError, match="request_too_large"):
                await client.search(VECTOR)
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_response_size_cap(monkeypatch):
    monkeypatch.setattr("telescope_rag.retrieval.candidate.MAX_CANDIDATE_REQUEST_BYTES", 20000)

    async def scenario():
        client = reader(
            lambda request: httpx.Response(
                200, content=b" " * 20001, headers={"content-type": "application/json"}
            )
        )
        try:
            with pytest.raises(ValueError, match="^candidate_reader_request_failed$"):
                await client.search(VECTOR)
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_timeout_and_transport_failure_do_not_retry_or_expose_details():
    async def scenario():
        for failure in ["timeout", "transport"]:
            calls = []

            async def handler(request, attempts=calls, mode=failure):
                attempts.append(request)
                if mode == "timeout":
                    await asyncio.sleep(0.05)
                    return response([])
                raise httpx.ReadError("synthetic-secret-in-transport", request=request)

            client = reader(handler, provider_timeout_seconds=0.01)
            try:
                with pytest.raises(ValueError, match="^candidate_reader_request_failed$") as caught:
                    await client.search(VECTOR)
                assert caught.value.__suppress_context__
                assert len(calls) == 1
            finally:
                await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "method,path",
    [
        ("PUT", f"collections/{COLLECTION}"),
        ("DELETE", f"collections/{COLLECTION}"),
        ("PATCH", f"collections/{COLLECTION}"),
        ("POST", "collections/aliases"),
        ("POST", f"collections/{COLLECTION}/points"),
        ("GET", "http://example.com/collections"),
        ("GET", "//example.com/collections"),
        ("GET", f"collections/{COLLECTION}?x=1"),
    ],
)
def test_request_guard_rejects_every_mutation_and_arbitrary_route(method, path):
    async def scenario():
        client = reader(lambda request: pytest.fail("forbidden route must not dispatch"))
        try:
            with pytest.raises(ValueError, match="route_not_allowed"):
                await client._request(method, path)
        finally:
            await client.aclose()

    asyncio.run(scenario())
