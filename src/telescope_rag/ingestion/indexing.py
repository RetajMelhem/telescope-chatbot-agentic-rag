"""Review-gated embedding and candidate writes. No active-alias or deletion API."""

import asyncio
import json
import math
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import httpx2 as httpx
from pydantic import Field

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.collection import CollectionError, canonical_url
from telescope_rag.ingestion.models import PreparedChunk, PreparedDocument, Record, stable_id
from telescope_rag.ingestion.review import (
    PreparationAudit,
    ReviewApproval,
    all_chunks,
    validate_approval,
)
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import EmbeddingFormat, EmbeddingProvider

MAX_CANDIDATE_REQUEST_BYTES = 8_000_000


class EmbeddingCache:
    """Immutable vectors addressed by content/configuration; retain every occurrence separately."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("invalid_embedding_cache_key")
        return self.directory / f"{key}.json"

    def get(self, key: str, config_hash: str, dimensions: int) -> tuple[float, ...] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            if path.stat().st_size > 2_000_000:
                raise ValueError
            data = json.loads(path.read_bytes())
            vector = data["vector"]
            if data["key"] != key or data["configuration_hash"] != config_hash:
                raise ValueError
            if not isinstance(vector, list) or len(vector) != dimensions:
                raise ValueError
            if any(type(value) not in (int, float) for value in vector):
                raise ValueError
            values = tuple(float(value) for value in vector)
            if not all(math.isfinite(value) for value in values) or not any(values):
                raise ValueError
            if data["vector_hash"] != stable_id(json.dumps(vector)):
                raise ValueError
            return values
        except Exception:
            raise ValueError("invalid_embedding_cache") from None

    def put(self, key: str, config_hash: str, vector: tuple[float, ...]) -> None:
        path = self._path(key)
        data = {
            "key": key,
            "configuration_hash": config_hash,
            "vector": list(vector),
            "vector_hash": stable_id(json.dumps(list(vector))),
        }
        text = json.dumps(data, allow_nan=False)
        with path.open("x", encoding="utf-8") as output:
            output.write(text)


class EmbeddingConfiguration(Record):
    model: str = "qwen/qwen3-embedding-8b"
    dimensions: int = Field(default=4096, ge=32, le=4096)
    format_version: str = Field(min_length=1)
    format_hash: str = Field(min_length=1)
    preparation_version: str = Field(min_length=1)
    tokenizer_version: str = Field(min_length=1)


class EmbeddedChunk(Record):
    chunk: PreparedChunk
    vector: tuple[float, ...] = Field(repr=False)
    configuration_hash: str


class CandidateManifest(Record):
    snapshot_id: str
    prepared_digest: str
    collection: str
    points: int
    configuration: EmbeddingConfiguration
    approved_source_reviewer: str
    status: str = "candidate_unpublished"
    active_alias_changed: bool = False


class CandidateWriter(Protocol):
    async def create(self, name: str, dimensions: int) -> None: ...
    async def upsert(self, name: str, points: Sequence[dict[str, Any]]) -> None: ...


def configuration_hash(configuration: EmbeddingConfiguration) -> str:
    return stable_id("embedding-config-v1", configuration.model_dump_json())


def validate_chunks(
    chunks: tuple[PreparedChunk, ...], settings: Settings, configuration: EmbeddingConfiguration
) -> None:
    if not chunks or len(chunks) > 10000:
        raise ValueError("candidate_size_invalid")
    if (
        configuration.model != settings.openrouter_embedding_model
        or configuration.dimensions != settings.embedding_dimensions
    ):
        raise ValueError("embedding_configuration_mismatch")
    ids = set()
    chunk_ids = set()
    for chunk in chunks:
        if chunk.point_id in ids or chunk.chunk_id in chunk_ids:
            raise ValueError("duplicate_candidate_point")
        ids.add(chunk.point_id)
        chunk_ids.add(chunk.chunk_id)
        uuid.UUID(chunk.point_id)
        try:
            canonical = canonical_url(chunk.canonical_url)
        except (CollectionError, ValueError):
            raise ValueError("invalid_candidate_source") from None
        if canonical != chunk.canonical_url:
            raise ValueError("invalid_candidate_source")
        if (
            not chunk.embedding_ready
            or chunk.token_count is None
            or chunk.token_count
            > min(settings.chunk_max_tokens, settings.max_embedding_input_tokens)
        ):
            raise ValueError("chunk_not_embedding_ready")
        if (
            not chunk.source_spans
            or not chunk.retrieval_text.strip()
            or not chunk.original_text.strip()
        ):
            raise ValueError("missing_chunk_provenance")
        if (
            chunk.tokenizer_version != configuration.tokenizer_version
            or chunk.preparation_version != configuration.preparation_version
        ):
            raise ValueError("preparation_configuration_mismatch")
        if (
            chunk.embedding_format_version != configuration.format_version
            or chunk.embedding_format_hash != configuration.format_hash
        ):
            raise ValueError("preparation_format_mismatch")
        if chunk.block_type == "doctor" and (not chunk.doctor_id or not chunk.doctor_name):
            raise ValueError("doctor_owner_missing")


async def embed_reviewed(
    documents: tuple[PreparedDocument, ...],
    audit: PreparationAudit,
    approval: ReviewApproval,
    *,
    provider: EmbeddingProvider,
    settings: Settings,
    format: EmbeddingFormat,
    configuration: EmbeddingConfiguration,
    cache: "EmbeddingCache | None" = None,
) -> tuple[EmbeddedChunk, ...]:
    validate_approval(documents, audit, approval)
    chunks = all_chunks(documents)
    validate_chunks(chunks, settings, configuration)
    if (
        not format.verified
        or format.version != configuration.format_version
        or stable_id("embedding-format-v1", format.model_dump_json()) != configuration.format_hash
    ):
        raise ValueError("embedding_format_mismatch")
    # Reuse exact inputs within owner/language/configuration; retain every occurrence as a point.
    config_hash = configuration_hash(configuration)
    groups: dict[str, list[PreparedChunk]] = {}
    for chunk in chunks:
        key = stable_id(config_hash, chunk.language, chunk.doctor_id or "", chunk.retrieval_text)
        groups.setdefault(key, []).append(chunk)
    keys = list(groups)
    vectors: dict[str, tuple[float, ...]] = {}
    for start in range(0, len(keys), settings.max_embedding_batch_size):
        batch = keys[start : start + settings.max_embedding_batch_size]
        # Bound per-input counts before the provider's independent whole-batch reservation.
        subbatches: list[list[str]] = [[]]
        tokens = 0
        for key in batch:
            count = groups[key][0].token_count
            if count > settings.max_embedding_input_tokens:
                raise ValueError("embedding_input_budget_exhausted")
            if tokens + count > settings.max_embedding_input_tokens:
                subbatches.append([])
                tokens = 0
            subbatches[-1].append(key)
            tokens += count
        for subbatch in subbatches:
            missing = []
            for key in subbatch:
                cached = cache.get(key, config_hash, configuration.dimensions) if cache else None
                if cached is None:
                    missing.append(key)
                else:
                    vectors[key] = cached
            if not missing:
                continue
            result = await provider.embed(
                [groups[key][0].retrieval_text for key in missing],
                role="document",
                format=format,
                budget=ExecutionBudget(settings),
            )
            if (
                result.requested_model != configuration.model
                or result.dimensions != configuration.dimensions
                or result.format_version != format.version
                or len(result.vectors) != len(missing)
            ):
                raise ValueError("embedding_result_configuration_mismatch")
            for key, vector in zip(missing, result.vectors, strict=True):
                if (
                    len(vector) != configuration.dimensions
                    or not all(math.isfinite(v) for v in vector)
                    or not any(vector)
                ):
                    raise ValueError("embedding_vector_invalid")
                vectors[key] = vector
                if cache:
                    cache.put(key, config_hash, vector)
    return tuple(
        EmbeddedChunk(chunk=chunk, vector=vectors[key], configuration_hash=config_hash)
        for key, occurrences in groups.items()
        for chunk in occurrences
    )


async def write_candidate(
    documents: tuple[PreparedDocument, ...],
    audit: PreparationAudit,
    approval: ReviewApproval,
    embedded: tuple[EmbeddedChunk, ...],
    *,
    settings: Settings,
    configuration: EmbeddingConfiguration,
    writer: CandidateWriter,
) -> CandidateManifest:
    validate_approval(documents, audit, approval)
    chunks = all_chunks(documents)
    validate_chunks(chunks, settings, configuration)
    expected = {chunk.chunk_id: chunk for chunk in chunks}
    if len(embedded) != len(expected) or len({item.chunk.chunk_id for item in embedded}) != len(
        expected
    ):
        raise ValueError("candidate_chunk_mapping_mismatch")
    config_hash = configuration_hash(configuration)
    points = []
    for item in embedded:
        if (
            expected.get(item.chunk.chunk_id) != item.chunk
            or item.configuration_hash != config_hash
        ):
            raise ValueError("candidate_payload_mismatch")
        if (
            len(item.vector) != configuration.dimensions
            or not all(math.isfinite(value) for value in item.vector)
            or not any(item.vector)
        ):
            raise ValueError("candidate_vector_invalid")
        points.append(
            {
                "id": item.chunk.point_id,
                "vector": list(item.vector),
                "payload": item.chunk.model_dump(mode="json"),
            }
        )
    name = (
        "telescope_public_" + stable_id(audit.snapshot_id, audit.prepared_digest, config_hash)[:24]
    )
    batches: list[list[dict[str, Any]]] = [[]]
    size = len(json.dumps({"points": []}).encode())
    for point in points:
        point_size = len(json.dumps(point, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        overhead = len(json.dumps({"points": []}).encode())
        if point_size + overhead > MAX_CANDIDATE_REQUEST_BYTES:
            raise ValueError("candidate_point_too_large")
        if len(batches[-1]) == 32 or size + point_size + 2 > MAX_CANDIDATE_REQUEST_BYTES:
            batches.append([])
            size = overhead
        size += point_size + (2 if batches[-1] else 0)
        batches[-1].append(point)
    # Validate before the first write. An upload failure leaves an unpublished candidate.
    await writer.create(name, configuration.dimensions)
    for batch in batches:
        await writer.upsert(name, batch)
    return CandidateManifest(
        snapshot_id=audit.snapshot_id,
        prepared_digest=audit.prepared_digest,
        collection=name,
        points=len(points),
        configuration=configuration,
        approved_source_reviewer=approval.reviewer,
    )


class QdrantCandidateWriter:
    """Explicit ingestion-only writer; cannot switch aliases or overwrite collections."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._http = httpx.AsyncClient(
            base_url=str(settings.qdrant_url).rstrip("/") + "/",
            transport=transport or httpx.AsyncHTTPTransport(retries=0),
            trust_env=False,
            follow_redirects=False,
            timeout=settings.provider_timeout_seconds,
        )

    async def _put(self, path: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_CANDIDATE_REQUEST_BYTES:
            raise ValueError("candidate_request_too_large")
        key = self._settings.qdrant_api_key.get_secret_value()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["api-key"] = key
        try:
            async with (
                asyncio.timeout(self._settings.provider_timeout_seconds),
                self._http.stream("PUT", path, content=encoded, headers=headers) as response,
            ):
                body = bytearray()
                async for part in response.aiter_bytes():
                    if len(body) + len(part) > self._settings.provider_max_response_bytes:
                        raise ValueError("candidate_response_too_large")
                    body.extend(part)
                if response.status_code != 200:
                    raise ValueError("candidate_write_failed")
                result = json.loads(body)
                if not isinstance(result, dict) or result.get("status") != "ok":
                    raise ValueError("candidate_write_failed")
                operation = result.get("result")
                if operation is not True and (
                    not isinstance(operation, dict) or operation.get("status") != "completed"
                ):
                    raise ValueError("candidate_write_failed")
        except Exception:
            raise ValueError("candidate_write_failed") from None

    @staticmethod
    def _name(name: str) -> str:
        prefix = "telescope_public_"
        suffix = name.removeprefix(prefix)
        if (
            not name.startswith(prefix)
            or len(suffix) != 24
            or any(c not in "0123456789abcdef" for c in suffix)
        ):
            raise ValueError("invalid_candidate_name")
        return name

    async def create(self, name: str, dimensions: int) -> None:
        await self._put(
            f"collections/{self._name(name)}",
            {"vectors": {"size": dimensions, "distance": "Cosine"}},
        )

    async def upsert(self, name: str, points: Sequence[dict[str, Any]]) -> None:
        await self._put(
            f"collections/{self._name(name)}/points?wait=true", {"points": list(points)}
        )

    async def aclose(self) -> None:
        try:
            async with asyncio.timeout(self._settings.shutdown_timeout_seconds):
                await self._http.aclose()
        except Exception:
            raise ValueError("candidate_cleanup_failed") from None
