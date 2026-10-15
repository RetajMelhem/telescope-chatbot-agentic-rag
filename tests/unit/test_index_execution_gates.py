"""Offline execution barriers with synthetic sources and mock transports only."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.indexing import (
    EmbeddedChunk,
    EmbeddingConfiguration,
    configuration_hash,
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
from telescope_rag.ingestion.preparation import PREPARATION_VERSION
from telescope_rag.ingestion.qdrant_audit import QdrantCandidateAudit
from telescope_rag.ingestion.review import ReviewApproval, build_audit
from telescope_rag.ingestion.runner import ReviewedBundle, load_reviewed_bundle, plan_run
from telescope_rag.providers.contracts import EmbeddingFormat

# Fixture compatibility only; this format/counter is never supplied to production.
FORMAT = EmbeddingFormat(version="synthetic-gate-test", verified=True)
CONFIG = EmbeddingConfiguration(
    dimensions=32,
    format_version=FORMAT.version,
    format_hash=stable_id("embedding-format-v1", FORMAT.model_dump_json()),
    preparation_version=PREPARATION_VERSION,
    tokenizer_version="synthetic-gate-counter",
)


def settings():
    return Settings(
        _env_file=None,
        app_env="test",
        embedding_dimensions=32,
        provider_max_retries=0,
        qdrant_api_key=SecretStr("synthetic-admin"),
    )


def bundle(*, approved=False):
    documents = []
    for index in range(2):
        text = "Synthetic public fact only after assessment."
        source = SourceSpan(
            block_id=f"source-{index}",
            locator="main > p",
            original_text=text,
            end=len(text),
            source_line=2,
        )
        unit = ContentUnit(
            unit_id=f"unit-{index}",
            kind="doctor",
            doctor_id="literal-fixture-owner",
            doctor_name="Dr. Literal Fixture",
            canonical_doctor_id="authorized-fixture-alias",
            canonical_doctor_name="Fixture Display",
            source_issue_codes=("synthetic_scope_unverified",),
            segments=(Segment(text=text, source=source),),
            language="en",
        )
        page = RawPage(
            snapshot_id="synthetic-gate-snapshot",
            document_id=f"document-{index}",
            canonical_url=f"https://telescopecenter.com/synthetic-gate-{index}/",
            fetched_at=datetime(2026, 10, 14, tzinfo=UTC),
            content_hash=stable_id(text),
            html="<main><p>" + text + "</p></main>",
        )
        document = ExtractedDocument(page=page, title="Synthetic gate", units=(unit,))
        chunk = PreparedChunk(
            chunk_id=f"chunk-{index}",
            point_id=str(UUID(int=index + 1)),
            document_id=page.document_id,
            canonical_url=page.canonical_url,
            page_title=document.title,
            snapshot_id=page.snapshot_id,
            fetched_at=page.fetched_at,
            parent_block_id=unit.unit_id,
            block_type=unit.kind,
            language=unit.language,
            section_path=(),
            doctor_id=unit.doctor_id,
            doctor_name=unit.doctor_name,
            canonical_doctor_id=unit.canonical_doctor_id,
            canonical_doctor_name=unit.canonical_doctor_name,
            source_issue_codes=unit.source_issue_codes,
            source_spans=(source,),
            original_text=text,
            retrieval_text=text,
            content_hash=stable_id(text),
            token_count=7,
            tokenizer_version=CONFIG.tokenizer_version,
            embedding_format_version=FORMAT.version,
            embedding_format_hash=CONFIG.format_hash,
            embedding_ready=True,
        )
        documents.append(PreparedDocument(document=document, chunks=(chunk,), embedding_ready=True))
    documents = tuple(documents)
    audit = build_audit(
        documents,
        snapshot_id="synthetic-gate-snapshot",
        collection_digest="synthetic-collection",
        crawl_coverage_confirmed=True,
    )
    approval = ReviewApproval(
        snapshot_id=audit.snapshot_id,
        prepared_digest=audit.prepared_digest,
        collection_digest=audit.collection_digest,
        reviewer="Synthetic fixture reviewer",
        approved=approved,
        source_reviewed=True,
    )
    return ReviewedBundle(documents, audit, approval, CONFIG)


class ForbiddenCounter:
    def count(self, text):
        pytest.fail("Unapproved plan must reject before counting or dispatch")


def test_unapproved_bundle_loader_and_plan_stop_before_external_dependencies(tmp_path):
    value = bundle()
    (tmp_path / "metadata").mkdir()
    for index, document in enumerate(value.documents):
        (tmp_path / f"document-{index}.json").write_text(document.model_dump_json())
    (tmp_path / "audit.json").write_text(value.audit.model_dump_json())
    (tmp_path / "metadata/review-approved.json").write_text(value.approval.model_dump_json())
    (tmp_path / "metadata/embedding-configuration.json").write_text(CONFIG.model_dump_json())
    with pytest.raises(ValueError, match="^source_review_required$"):
        load_reviewed_bundle(tmp_path)
    with pytest.raises(ValueError, match="^source_review_required$"):
        plan_run(
            value, settings(), ForbiddenCounter(), FORMAT, max_requests=2, max_input_tokens=100
        )


class MemoryWriter:
    def __init__(self):
        self.calls = []

    async def create(self, name, dimensions):
        self.calls.append(("create", name, dimensions))

    async def upsert(self, name, points):
        self.calls.append(("upsert", name, points))


@pytest.mark.parametrize("damage", [None, "missing_occurrence", "zero_vector", "wrong_size"])
def test_candidate_payload_and_occurrence_barriers_before_first_write(damage):
    async def scenario():
        value = bundle(approved=True)
        embedded = tuple(
            EmbeddedChunk(
                chunk=document.chunks[0],
                vector=(1.0,) * 32,
                configuration_hash=configuration_hash(CONFIG),
            )
            for document in value.documents
        )
        if damage == "missing_occurrence":
            embedded = embedded[:1]
        elif damage:
            vector = (0.0,) * 32 if damage == "zero_vector" else (1.0,) * 31
            embedded = (embedded[0].model_copy(update={"vector": vector}), embedded[1])
        writer = MemoryWriter()
        if damage:
            code = (
                "candidate_chunk_mapping_mismatch"
                if damage == "missing_occurrence"
                else "candidate_vector_invalid"
            )
            with pytest.raises(ValueError, match=f"^{code}$"):
                await write_candidate(
                    value.documents,
                    value.audit,
                    value.approval,
                    embedded,
                    settings=settings(),
                    configuration=CONFIG,
                    writer=writer,
                )
            assert writer.calls == []
            return
        result = await write_candidate(
            value.documents,
            value.audit,
            value.approval,
            embedded,
            settings=settings(),
            configuration=CONFIG,
            writer=writer,
        )
        points = writer.calls[1][2]
        assert len(points) == 2 and len({p["id"] for p in points}) == 2
        assert result.status == "candidate_unpublished" and not result.active_alias_changed
        for point, item in zip(points, embedded, strict=True):
            assert point["payload"] == item.chunk.model_dump(mode="json")
            assert point["payload"]["source_issue_codes"] == ["synthetic_scope_unverified"]
            assert point["payload"]["doctor_id"] == "literal-fixture-owner"
            assert point["payload"]["canonical_doctor_id"] == "authorized-fixture-alias"
            assert point["payload"]["source_spans"][0]["locator"] == "main > p"

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [401, 403, 200, 400, 404, 422])
def test_preflight_uses_absent_update_probe_and_rejects_non_denials(status):
    async def scenario():
        calls = []
        candidate = "telescope_public_" + "a" * 24

        def handler(request):
            calls.append((request.method, request.url.path))
            assert request.method != "PUT"
            if request.method == "PATCH":
                assert request.content == b"{}"
                assert request.url.path != f"/collections/{candidate}"
                assert request.headers["api-key"] == "synthetic-reader"
                return httpx.Response(status, json={"status": "ok"})
            if request.url.path == "/":
                return httpx.Response(200, json={"version": "synthetic-version"})
            if request.url.path == "/collections" and "api-key" not in request.headers:
                return httpx.Response(401)
            if request.url.path == "/collections":
                return httpx.Response(200, json={"status": "ok", "result": {"collections": []}})
            if request.url.path == "/aliases":
                return httpx.Response(200, json={"status": "ok", "result": {"aliases": []}})
            return httpx.Response(404)

        audit = QdrantCandidateAudit(
            settings(), SecretStr("synthetic-reader"), transport=httpx.MockTransport(handler)
        )
        try:
            if status in {401, 403}:
                result = await audit.preflight(candidate, 32, expected_version="synthetic-version")
                assert result["read_only_update_status"] == status
                assert result["permission_probe_absent_before"]
                assert result["permission_probe_absent_after"]
            else:
                with pytest.raises(ValueError, match="^candidate_read_only_not_enforced$"):
                    await audit.preflight(candidate, 32, expected_version="synthetic-version")
            patch = next(i for i, item in enumerate(calls) if item[0] == "PATCH")
            path = calls[patch][1]
            assert calls[patch - 1 : patch + 2] == [("GET", path), ("PATCH", path), ("GET", path)]
        finally:
            await audit.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("exists_after", [False, True])
def test_probe_requires_absence_before_and_after_update(exists_after):
    async def scenario():
        calls = []

        def handler(request):
            calls.append(request.method)
            if request.method == "PATCH":
                return httpx.Response(403)
            absent = len(calls) == 1 and exists_after
            return httpx.Response(404 if absent else 200, json={"status": "ok"})

        audit = QdrantCandidateAudit(
            settings(), SecretStr("synthetic-reader"), transport=httpx.MockTransport(handler)
        )
        try:
            with pytest.raises(ValueError, match="^candidate_permission_probe_not_absent$"):
                await audit.probe_read_only_update()
            assert calls == (["GET", "PATCH", "GET"] if exists_after else ["GET"])
        finally:
            await audit.aclose()

    asyncio.run(scenario())


def test_verify_uses_separate_absent_probe_never_puts_candidate_points():
    async def scenario():
        value = bundle(approved=True)
        chunk = value.documents[0].chunks[0]
        embedded = (
            EmbeddedChunk(
                chunk=chunk,
                vector=(1.0,) + (0.0,) * 31,
                configuration_hash=configuration_hash(CONFIG),
            ),
        )
        candidate = "telescope_public_" + "a" * 24
        calls = []

        def handler(request):
            calls.append((request.method, request.url.path))
            assert request.method != "PUT"
            path = request.url.path
            if request.method == "PATCH":
                assert path != f"/collections/{candidate}"
                assert request.content == b"{}"
                return httpx.Response(403)
            if path.endswith("/points/count"):
                result = {"count": 1}
            elif path.endswith("/points/scroll"):
                result = {
                    "points": [
                        {
                            "id": chunk.point_id,
                            "payload": chunk.model_dump(mode="json"),
                            "vector": list(embedded[0].vector),
                        }
                    ],
                    "next_page_offset": None,
                }
            elif path == "/aliases":
                result = {"aliases": []}
            elif path == f"/collections/{candidate}":
                result = {
                    "config": {"params": {"vectors": {"size": 32, "distance": "Cosine"}}},
                    "status": "green",
                }
            else:
                return httpx.Response(404)
            return httpx.Response(200, json={"status": "ok", "result": result})

        audit = QdrantCandidateAudit(
            settings(), SecretStr("synthetic-reader"), transport=httpx.MockTransport(handler)
        )
        try:
            result = await audit.verify(candidate, embedded, [])
            assert result["points_verified"] == 1
            assert result["read_only_update_status"] == 403
            probe = "/collections/" + result["permission_probe_collection"]
            assert calls[-3:] == [("GET", probe), ("PATCH", probe), ("GET", probe)]
        finally:
            await audit.aclose()

    asyncio.run(scenario())
