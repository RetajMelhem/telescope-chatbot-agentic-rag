"""Read-only exact dense queries against an explicitly supplied local candidate.

This evaluation adapter does not publish a snapshot, approve evidence, interpret
queries or connect the public API to an unpublished collection.
"""

import asyncio
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal
from uuid import UUID

import httpx2 as httpx
from pydantic import SecretStr

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.indexing import MAX_CANDIDATE_REQUEST_BYTES
from telescope_rag.ingestion.models import PreparedChunk
from telescope_rag.providers.validation import load_json

_LOCAL_TARGET = "http://127.0.0.1:6333/"
_STAGING_TARGET = "http://127.0.0.1:6334/"
_CONTAINER_TARGET = "http://telescope-m3-qdrant:6333/"
_TARGETS = {
    "loopback": _LOCAL_TARGET,
    "staging_loopback": _STAGING_TARGET,
    "local_container": _CONTAINER_TARGET,
}
_CANDIDATE_NAME = re.compile(r"telescope_public_[0-9a-f]{24}")
_DIMENSIONS = 4096
MAX_DENSE_HITS = 20
_MAX_HITS = MAX_DENSE_HITS
_MAX_EXPECTED_POINTS = 10000


@dataclass(frozen=True)
class DenseHit:
    chunk: PreparedChunk
    score: float


def _canonical_payload(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


class CandidateDenseReader:
    """Bounded evaluation reader; the caller supplies the complete pinned inventory."""

    def __init__(
        self,
        settings: Settings,
        read_key: SecretStr,
        *,
        collection: str,
        chunks: Mapping[str, PreparedChunk],
        transport: httpx.AsyncBaseTransport | None = None,
        target: Literal["loopback", "staging_loopback", "local_container"] = "loopback",
    ):
        # Each target maps to exactly one address. The reader never follows a
        # configured host: it reads a local candidate or a separate local
        # staging database, never a remote one.
        if target not in _TARGETS:
            raise ValueError("candidate_reader_local_target_required")
        address = _TARGETS[target]
        if str(settings.qdrant_url) != address:
            raise ValueError("candidate_reader_local_target_required")
        if not isinstance(collection, str) or _CANDIDATE_NAME.fullmatch(collection) is None:
            raise ValueError("candidate_reader_invalid_collection")
        if settings.embedding_dimensions != _DIMENSIONS:
            raise ValueError("candidate_reader_dimensions_mismatch")
        if not isinstance(read_key, SecretStr) or not read_key.get_secret_value().strip():
            raise ValueError("candidate_reader_read_key_required")
        expected = dict(chunks)
        if not expected or len(expected) > _MAX_EXPECTED_POINTS:
            raise ValueError("candidate_reader_invalid_inventory")
        chunk_ids: set[str] = set()
        configurations: set[tuple] = set()
        payloads: dict[str, str] = {}
        for point_id, chunk in expected.items():
            if (
                not isinstance(chunk, PreparedChunk)
                or not isinstance(point_id, str)
                or point_id != chunk.point_id
                or not chunk.chunk_id
                or chunk.chunk_id in chunk_ids
                or not chunk.snapshot_id
                or not chunk.embedding_ready
            ):
                raise ValueError("candidate_reader_invalid_inventory")
            try:
                if str(UUID(point_id)) != point_id:
                    raise ValueError("noncanonical_point_id")
                payload = chunk.model_dump(mode="json")
                # Revalidate copied Pydantic instances as well as ordinary instances.
                PreparedChunk.model_validate(payload)
                payloads[point_id] = _canonical_payload(payload)
            except (ValueError, TypeError, OverflowError):
                raise ValueError("candidate_reader_invalid_inventory") from None
            chunk_ids.add(chunk.chunk_id)
            configurations.add(
                (
                    chunk.snapshot_id,
                    chunk.preparation_version,
                    chunk.tokenizer_version,
                    chunk.embedding_format_version,
                    chunk.embedding_format_hash,
                    chunk.admission_policy_hash,
                )
            )
        if len(configurations) != 1:
            raise ValueError("candidate_reader_mixed_snapshot_or_configuration")
        self._chunks = MappingProxyType(expected)
        self._payloads = MappingProxyType(payloads)
        self._collection = collection
        self._read_key = read_key
        self._settings = settings
        self._http = httpx.AsyncClient(
            base_url=address,
            transport=transport or httpx.AsyncHTTPTransport(retries=0),
            timeout=settings.provider_timeout_seconds,
            trust_env=False,
            follow_redirects=False,
        )

    async def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        allowed = {
            ("GET", f"collections/{self._collection}"),
            ("GET", "aliases"),
            ("POST", f"collections/{self._collection}/points/query"),
        }
        if (method, path) not in allowed or (method == "GET" and body is not None):
            raise ValueError("candidate_reader_route_not_allowed")
        encoded = (
            json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if body is not None
            else None
        )
        if encoded is not None and len(encoded) > MAX_CANDIDATE_REQUEST_BYTES:
            raise ValueError("candidate_reader_request_too_large")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "api-key": self._read_key.get_secret_value(),
        }
        try:
            async with (
                asyncio.timeout(self._settings.provider_timeout_seconds),
                self._http.stream(method, path, content=encoded, headers=headers) as response,
            ):
                if response.status_code != 200:
                    raise ValueError("unexpected_status")
                media = response.headers.get("content-type", "").split(";", 1)[0].strip()
                if media != "application/json":
                    raise ValueError("unexpected_media_type")
                raw = bytearray()
                async for part in response.aiter_bytes(chunk_size=65536):
                    if len(raw) + len(part) > MAX_CANDIDATE_REQUEST_BYTES:
                        raise ValueError("oversized_response")
                    raw.extend(part)
                data = load_json(bytes(raw))
                if data.get("status") != "ok" or "result" not in data:
                    raise ValueError("invalid_envelope")
                return data["result"]
        except Exception:
            # Upstream exceptions/bodies can contain headers, credentials or text.
            raise ValueError("candidate_reader_request_failed") from None

    async def info(self) -> dict:
        result = await self._request("GET", f"collections/{self._collection}")
        if not isinstance(result, dict):
            raise ValueError("candidate_reader_invalid_info")
        return result

    async def aliases(self) -> list:
        result = await self._request("GET", "aliases")
        aliases = result.get("aliases") if isinstance(result, dict) else None
        if not isinstance(aliases, list) or len(aliases) > 1000:
            raise ValueError("candidate_reader_invalid_aliases")
        return aliases

    def check_inventory(
        self, chunks: Mapping[str, PreparedChunk], *, settings: Settings | None = None
    ) -> None:
        """Pure preflight: bind the caller's complete catalog before embedding dispatch."""
        if settings is not None and settings != self._settings:
            raise ValueError("candidate_reader_configuration_mismatch")
        try:
            if set(chunks) != set(self._chunks) or any(
                _canonical_payload(chunk.model_dump(mode="json")) != self._payloads[point_id]
                for point_id, chunk in chunks.items()
            ):
                raise ValueError
        except Exception:
            raise ValueError("candidate_reader_inventory_mismatch") from None

    async def search(
        self,
        vector: Sequence[float],
        *,
        limit: int = _MAX_HITS,
        point_ids: Sequence[str] | None = None,
    ) -> tuple[DenseHit, ...]:
        if type(limit) is not int or not 1 <= limit <= _MAX_HITS:
            raise ValueError("candidate_reader_invalid_limit")
        try:
            if (
                not isinstance(vector, Sequence)
                or len(vector) != _DIMENSIONS
                or any(type(v) not in {int, float} or not math.isfinite(v) for v in vector)
                or not 0 < math.hypot(*vector) < math.inf
            ):
                raise ValueError("invalid_vector")
        except (ValueError, TypeError, OverflowError):
            raise ValueError("candidate_reader_invalid_vector") from None
        allowed_points = None
        if point_ids is not None:
            if (
                not isinstance(point_ids, (tuple, list))
                or len(point_ids) > _MAX_EXPECTED_POINTS
                or any(type(p) is not str or p not in self._chunks for p in point_ids)
                or len(set(point_ids)) != len(point_ids)
            ):
                raise ValueError("candidate_reader_invalid_point_scope")
            allowed_points = frozenset(point_ids)
            if not allowed_points:
                return ()
        body = {
            "query": list(vector),
            "params": {"exact": True},
            "with_payload": True,
            "with_vector": False,
            "limit": limit,
        }
        if allowed_points is not None:
            body["filter"] = {"must": [{"has_id": sorted(allowed_points)}]}
        result = await self._request("POST", f"collections/{self._collection}/points/query", body)
        points = result.get("points") if isinstance(result, dict) else None
        if not isinstance(points, list) or len(points) > limit:
            raise ValueError("candidate_reader_invalid_points")
        hits: list[DenseHit] = []
        seen: set[str] = set()
        previous_score = math.inf
        for point in points:
            point_id = point.get("id") if isinstance(point, dict) else None
            if not isinstance(point_id, str) or point_id not in self._chunks or point_id in seen:
                raise ValueError("candidate_reader_point_mapping_mismatch")
            if allowed_points is not None and point_id not in allowed_points:
                raise ValueError("candidate_reader_point_outside_scope")
            score = point.get("score")
            try:
                if type(score) not in {int, float} or not math.isfinite(score):
                    raise ValueError("invalid_score")
                score = float(score)
                if score > previous_score + 0.0000001:
                    raise ValueError("out_of_order_score")
            except (ValueError, TypeError, OverflowError):
                raise ValueError("candidate_reader_invalid_score") from None
            if (
                not isinstance(point.get("payload"), dict)
                or _canonical_payload(point["payload"]) != self._payloads[point_id]
            ):
                raise ValueError("candidate_reader_payload_mismatch")
            seen.add(point_id)
            hits.append(DenseHit(chunk=self._chunks[point_id], score=score))
            previous_score = score
        return tuple(hits)

    async def aclose(self) -> None:
        async with asyncio.timeout(self._settings.shutdown_timeout_seconds):
            await self._http.aclose()
