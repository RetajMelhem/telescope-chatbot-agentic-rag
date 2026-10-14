"""Synthetic preparation review and candidate write gates; no provider/database connections."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import httpx2 as httpx
import pytest

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.indexing import (
    EmbeddedChunk,
    EmbeddingCache,
    EmbeddingConfiguration,
    QdrantCandidateWriter,
    configuration_hash,
    embed_reviewed,
    write_candidate,
)
from telescope_rag.ingestion.models import (
    ContentUnit,
    ExtractedDocument,
    PreparedChunk,
    PreparedDocument,
    RawPage,
    Segment,
    SourceSpan,
    stable_id,
)
from telescope_rag.ingestion.review import (
    ReviewApproval,
    build_audit,
    prepared_digest,
    validate_approval,
    write_bundle,
)
from telescope_rag.providers.contracts import EmbeddingFormat, EmbeddingResult

FORMAT = EmbeddingFormat(version="synthetic-test-v1", verified=True, document_prefix="Test: ")
CONFIG = EmbeddingConfiguration(
    dimensions=32,
    format_version=FORMAT.version,
    format_hash=stable_id("embedding-format-v1", FORMAT.model_dump_json()),
    preparation_version="structure-nfc-v1",
    tokenizer_version="synthetic-counter-v1",
)


def documents(*, ready=True):
    result = []
    for number in range(2):
        text = "What are your working hours? Friday 2 PM–12 AM."
        source = SourceSpan(
            block_id=f"b{number}",
            locator="main > details:nth-of-type(1)",
            original_text=text,
            end=len(text),
        )
        unit = ContentUnit(
            unit_id=f"u{number}",
            kind="faq",
            segments=(Segment(text=text, source=source),),
            language="en",
        )
        page = RawPage(
            snapshot_id="synthetic-snapshot",
            document_id=f"d{number}",
            canonical_url=f"https://telescopecenter.com/faq-{number}/",
            fetched_at=datetime(2026, 10, 14, tzinfo=UTC),
            content_hash="fixture",
            html="",
        )
        doc = ExtractedDocument(page=page, title="Synthetic FAQ", units=(unit,))
        chunk = PreparedChunk(
            chunk_id=f"c{number}",
            point_id=str(uuid.UUID(int=number + 1)),
            document_id=page.document_id,
            canonical_url=page.canonical_url,
            page_title=doc.title,
            snapshot_id=page.snapshot_id,
            fetched_at=page.fetched_at,
            parent_block_id=unit.unit_id,
            block_type="faq",
            language="en",
            section_path=(),
            source_spans=(source,),
            original_text=text,
            retrieval_text=text,
            content_hash=stable_id(text),
            token_count=20 if ready else None,
            tokenizer_version=CONFIG.tokenizer_version if ready else None,
            embedding_format_version=FORMAT.version if ready else None,
            embedding_format_hash=CONFIG.format_hash if ready else None,
            embedding_ready=ready,
        )
        result.append(PreparedDocument(document=doc, chunks=(chunk,), embedding_ready=ready))
    return tuple(result)


def approved_bundle(*, ready=True, gaps=()):
    docs = documents(ready=ready)
    audit = build_audit(
        docs,
        snapshot_id="synthetic-snapshot",
        collection_digest="collection-hash",
        crawl_coverage_confirmed=True,
        crawl_gap_codes=gaps,
    )
    approval = ReviewApproval(
        snapshot_id=audit.snapshot_id,
        prepared_digest=audit.prepared_digest,
        collection_digest=audit.collection_digest,
        reviewer="Synthetic reviewer",
        approved=True,
        source_reviewed=True,
        accepted_gap_codes=gaps,
    )
    return docs, audit, approval


def test_default_audit_never_establishes_collection_or_directory_completeness():
    audit = build_audit(documents(), snapshot_id="synthetic-snapshot")
    assert not audit.crawl_coverage_complete and not audit.approved
    assert audit.directory_coverage_status == "requires_source_review"
    assert "collection_coverage_unverified" in audit.gap_codes
    assert len(audit.hours) == 2  # hours inside FAQ remain visible, raw and unresolved
    assert all(item.interpretation_status == "unresolved" for item in audit.hours)


@pytest.mark.parametrize(
    "case,code",
    [
        ("unapproved", "source_review_required"),
        ("unreviewed", "source_review_required"),
        ("digest", "review_digest_mismatch"),
        ("collection", "collection_review_binding_required"),
        ("gaps", "unreviewed_coverage_gaps"),
        ("draft", "preparation_not_embedding_ready"),
    ],
)
def test_review_gate_cases(case, code):
    docs, audit, approval = approved_bundle(ready=case != "draft", gaps=("fetch_failed",))
    changes = {
        "unapproved": {"approved": False},
        "unreviewed": {"source_reviewed": False},
        "digest": {"prepared_digest": "changed"},
        "collection": {"collection_digest": "other"},
        "gaps": {"accepted_gap_codes": ()},
    }
    approval = approval.model_copy(update=changes.get(case, {}))
    with pytest.raises(ValueError, match=f"^{code}$"):
        validate_approval(docs, audit, approval)


def test_review_bundle_is_immutable_and_template_unapproved(tmp_path):
    docs, audit, _ = approved_bundle()
    path = tmp_path / "bundle"
    write_bundle(path, docs, audit)
    assert json.loads((path / "review-template.json").read_text())["approved"] is False
    with pytest.raises(FileExistsError):
        write_bundle(path, docs, audit)
    changed = docs[0].model_copy(update={"chunks": ()})
    assert prepared_digest((changed, docs[1])) != audit.prepared_digest


class SyntheticEmbedding:
    def __init__(self):
        self.calls = []

    async def embed(self, texts, *, role, format, budget):
        self.calls.append((texts, role, format.version))
        return EmbeddingResult(
            tuple((1.0,) * 32 for _ in texts), CONFIG.model, 32, format.version, ()
        )


class MemoryWriter:
    def __init__(self):
        self.calls = []

    async def create(self, name, dimensions):
        self.calls.append(("create", name, dimensions))

    async def upsert(self, name, points):
        self.calls.append(("upsert", name, points))


def settings():
    return Settings(_env_file=None, app_env="test", embedding_dimensions=32)


def test_exact_cache_reuse_preserves_both_occurrences_and_candidate_has_no_alias(tmp_path):
    async def scenario():
        docs, audit, approval = approved_bundle()
        provider, cache, writer = (
            SyntheticEmbedding(),
            EmbeddingCache(tmp_path / "cache"),
            MemoryWriter(),
        )
        embedded = await embed_reviewed(
            docs,
            audit,
            approval,
            provider=provider,
            settings=settings(),
            format=FORMAT,
            configuration=CONFIG,
            cache=cache,
        )
        assert len(provider.calls) == 1 and len(provider.calls[0][0]) == 1
        assert len(embedded) == 2 and embedded[0].chunk.point_id != embedded[1].chunk.point_id
        cached = await embed_reviewed(
            docs,
            audit,
            approval,
            provider=provider,
            settings=settings(),
            format=FORMAT,
            configuration=CONFIG,
            cache=cache,
        )
        assert cached == embedded and len(provider.calls) == 1
        result = await write_candidate(
            docs,
            audit,
            approval,
            embedded,
            settings=settings(),
            configuration=CONFIG,
            writer=writer,
        )
        assert result.status == "candidate_unpublished" and not result.active_alias_changed
        assert len(writer.calls) == 2 and len(writer.calls[1][2]) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case,code",
    [
        ("point", "candidate_chunk_mapping_mismatch"),
        ("config", "candidate_payload_mismatch"),
        ("vector", "candidate_vector_invalid"),
        ("payload", "candidate_payload_mismatch"),
        ("format", "preparation_format_mismatch"),
        ("review", "source_review_required"),
    ],
)
def test_every_candidate_validation_precedes_first_write(case, code):
    async def scenario():
        docs, audit, approval = approved_bundle()
        embedded = tuple(
            EmbeddedChunk(
                chunk=d.chunks[0], vector=(1.0,) * 32, configuration_hash=configuration_hash(CONFIG)
            )
            for d in docs
        )
        config, writer = CONFIG, MemoryWriter()
        if case == "point":
            embedded = embedded[:1]
        elif case == "config":
            embedded = (embedded[0].model_copy(update={"configuration_hash": "bad"}), embedded[1])
        elif case == "vector":
            embedded = (embedded[0].model_copy(update={"vector": (0.0,) * 32}), embedded[1])
        elif case == "payload":
            altered = embedded[0].chunk.model_copy(update={"retrieval_text": "invented"})
            embedded = (embedded[0].model_copy(update={"chunk": altered}), embedded[1])
        elif case == "format":
            config = CONFIG.model_copy(update={"format_hash": "wrong"})
        else:
            approval = approval.model_copy(update={"approved": False})
        with pytest.raises(ValueError, match=f"^{code}$"):
            await write_candidate(
                docs,
                audit,
                approval,
                embedded,
                settings=settings(),
                configuration=config,
                writer=writer,
            )
        assert not writer.calls

    asyncio.run(scenario())


def test_unapproved_snapshot_dispatches_no_embedding():
    async def scenario():
        docs, audit, approval = approved_bundle()
        provider = SyntheticEmbedding()
        with pytest.raises(ValueError, match="^source_review_required$"):
            await embed_reviewed(
                docs,
                audit,
                approval.model_copy(update={"approved": False}),
                provider=provider,
                settings=settings(),
                format=FORMAT,
                configuration=CONFIG,
            )
        assert not provider.calls

    asyncio.run(scenario())


def test_cache_corruption_does_not_trigger_paid_fallback(tmp_path):
    cache = EmbeddingCache(tmp_path)
    key = "a" * 64
    cache.put(key, "config", (1.0,) * 32)
    path = tmp_path / f"{key}.json"
    data = json.loads(path.read_text())
    data["vector"][0] = 2.0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="^invalid_embedding_cache$"):
        cache.get(key, "config", 32)


def test_qdrant_candidate_protocol_never_sends_alias_or_delete():
    async def scenario():
        calls = []

        def handler(request):
            calls.append(request)
            assert request.method == "PUT" and "aliases" not in request.url.path
            payload = json.loads(request.read())
            if request.url.path.endswith("/points"):
                assert request.url.query == b"wait=true" and payload["points"]
                return httpx2_response({"result": {"status": "completed"}, "status": "ok"})
            assert payload["vectors"] == {"size": 32, "distance": "Cosine"}
            return httpx2_response({"result": True, "status": "ok"})

        writer = QdrantCandidateWriter(settings(), transport=httpx.MockTransport(handler))
        name = "telescope_public_" + "a" * 24
        try:
            await writer.create(name, 32)
            await writer.upsert(name, [{"id": str(uuid.UUID(int=1)), "vector": [1.0] * 32}])
        finally:
            await writer.aclose()
        assert len(calls) == 2

    asyncio.run(scenario())


def httpx2_response(body):
    return httpx.Response(200, json=body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("doctor_id", "sibling-doctor"),
        ("parent_block_id", "other-unit"),
        ("canonical_url", "https://telescopecenter.com/another/"),
    ],
)
def test_review_cannot_reassign_chunk_source_ownership(field, value):
    docs, _, _ = approved_bundle()
    altered = docs[0].chunks[0].model_copy(update={field: value})
    docs = (docs[0].model_copy(update={"chunks": (altered,)}), docs[1])
    audit = build_audit(docs, snapshot_id="synthetic-snapshot", collection_digest="hash")
    approval = ReviewApproval(
        snapshot_id=audit.snapshot_id,
        prepared_digest=audit.prepared_digest,
        collection_digest="hash",
        reviewer="Synthetic reviewer",
        approved=True,
        source_reviewed=True,
    )
    with pytest.raises(ValueError, match="^chunk_source_ownership_mismatch$"):
        validate_approval(docs, audit, approval)


def test_review_cannot_replace_original_source_text():
    docs, _, _ = approved_bundle()
    source = docs[0].chunks[0].source_spans[0].model_copy(update={"original_text": "invented" * 10})
    chunk = docs[0].chunks[0].model_copy(update={"source_spans": (source,)})
    docs = (docs[0].model_copy(update={"chunks": (chunk,)}), docs[1])
    audit = build_audit(docs, snapshot_id="synthetic-snapshot", collection_digest="hash")
    approval = ReviewApproval(
        snapshot_id=audit.snapshot_id,
        prepared_digest=audit.prepared_digest,
        collection_digest="hash",
        reviewer="Synthetic reviewer",
        approved=True,
        source_reviewed=True,
    )
    with pytest.raises(ValueError, match="^chunk_source_mapping_mismatch$"):
        validate_approval(docs, audit, approval)


def test_candidate_payload_limit_is_checked_before_collection_creation(monkeypatch):
    async def scenario():
        docs, audit, approval = approved_bundle()
        embedded = tuple(
            EmbeddedChunk(
                chunk=d.chunks[0], vector=(1.0,) * 32, configuration_hash=configuration_hash(CONFIG)
            )
            for d in docs
        )
        writer = MemoryWriter()
        monkeypatch.setattr("telescope_rag.ingestion.indexing.MAX_CANDIDATE_REQUEST_BYTES", 50)
        with pytest.raises(ValueError, match="^candidate_point_too_large$"):
            await write_candidate(
                docs,
                audit,
                approval,
                embedded,
                settings=settings(),
                configuration=CONFIG,
                writer=writer,
            )
        assert not writer.calls

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status,body",
    [
        (409, {"status": "error", "result": False}),
        (302, {"status": "ok", "result": True}),
        (200, {"status": "ok", "result": None}),
        (200, {"status": "ok", "result": {"status": "acknowledged"}}),
    ],
)
def test_candidate_write_failure_does_not_retry_or_follow_redirects(status, body):
    async def scenario():
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(status, json=body, headers={"location": "https://example.com"})

        writer = QdrantCandidateWriter(settings(), transport=httpx.MockTransport(handler))
        try:
            with pytest.raises(ValueError, match="^candidate_write_failed$"):
                await writer.create("telescope_public_" + "a" * 24, 32)
        finally:
            await writer.aclose()
        assert len(calls) == 1

    asyncio.run(scenario())
