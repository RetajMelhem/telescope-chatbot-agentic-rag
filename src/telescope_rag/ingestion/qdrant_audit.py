"""Bounded candidate-only verification; no alias mutation or destructive operations."""

import asyncio
import json
import math
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import httpx2 as httpx
from pydantic import SecretStr

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.indexing import (
    MAX_CANDIDATE_REQUEST_BYTES,
    EmbeddedChunk,
    QdrantCandidateWriter,
)
from telescope_rag.ingestion.models import stable_id
from telescope_rag.providers.validation import load_json


class QdrantCandidateAudit:
    """Use an independent read key and prove denied writes before paying for embeddings."""

    def __init__(
        self,
        settings: Settings,
        read_key: SecretStr,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.settings = settings
        self.read_key = read_key
        self.http = httpx.AsyncClient(
            base_url=str(settings.qdrant_url).rstrip("/") + "/",
            transport=transport or httpx.AsyncHTTPTransport(retries=0),
            timeout=settings.provider_timeout_seconds,
            trust_env=False,
            follow_redirects=False,
        )

    async def _request(
        self, method: str, path: str, body: dict | None = None, *, authenticated: bool = True
    ) -> tuple[int, dict[str, Any]]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if authenticated:
            headers["api-key"] = self.read_key.get_secret_value()
        encoded = json.dumps(body, allow_nan=False).encode() if body is not None else None
        if encoded is not None and len(encoded) > MAX_CANDIDATE_REQUEST_BYTES:
            raise ValueError("candidate_audit_request_too_large")
        try:
            async with (
                asyncio.timeout(self.settings.provider_timeout_seconds),
                self.http.stream(method, path, content=encoded, headers=headers) as response,
            ):
                raw = bytearray()
                async for part in response.aiter_bytes(chunk_size=65536):
                    if len(raw) + len(part) > MAX_CANDIDATE_REQUEST_BYTES:
                        raise ValueError("candidate_audit_response_too_large")
                    raw.extend(part)
                # Errors are classified by status without exposing upstream body.
                if response.status_code != 200:
                    return response.status_code, {}
                media = response.headers.get("content-type", "").split(";", 1)[0]
                if media != "application/json":
                    raise ValueError("candidate_audit_invalid_response")
                return response.status_code, load_json(bytes(raw))
        except Exception:
            raise ValueError("candidate_audit_request_failed") from None

    async def _ok(self, method: str, path: str, body: dict | None = None) -> Any:
        status, data = await self._request(method, path, body)
        if status != 200 or data.get("status") != "ok" or "result" not in data:
            raise ValueError("candidate_audit_request_failed")
        return data["result"]

    async def aliases(self) -> list:
        result = await self._ok("GET", "aliases")
        aliases = result.get("aliases") if isinstance(result, dict) else None
        if not isinstance(aliases, list) or len(aliases) > 1000:
            raise ValueError("candidate_audit_invalid_aliases")
        return aliases

    async def probe_read_only_update(self) -> dict:
        """Test update denial on a fresh absent name; never create or touch candidate data."""
        name = QdrantCandidateWriter._name("telescope_public_" + uuid4().hex[:24])
        path = f"collections/{name}"
        before, _ = await self._request("GET", path)
        if before != 404:
            raise ValueError("candidate_permission_probe_not_absent")
        denied, _ = await self._request("PATCH", path, {})
        after, _ = await self._request("GET", path)
        if after != 404:
            raise ValueError("candidate_permission_probe_not_absent")
        if denied not in {401, 403}:
            raise ValueError("candidate_read_only_not_enforced")
        return {
            "permission_probe_collection": name,
            "permission_probe_absent_before": True,
            "permission_probe_absent_after": True,
            "read_only_update_status": denied,
        }

    async def preflight(self, name: str, dimensions: int, *, expected_version: str) -> dict:
        name = QdrantCandidateWriter._name(name)
        admin = self.settings.qdrant_api_key.get_secret_value()
        reader = self.read_key.get_secret_value()
        if not admin or not reader or admin == reader:
            raise ValueError("candidate_role_credentials_required")
        status, root = await self._request("GET", "")
        if status != 200 or root.get("version") != expected_version:
            raise ValueError("candidate_server_version_mismatch")
        collections = await self._ok("GET", "collections")
        if not isinstance(collections, dict) or not isinstance(
            collections.get("collections"), list
        ):
            raise ValueError("candidate_audit_invalid_response")
        # This first-run runner deliberately targets a dedicated empty local DB.
        if collections["collections"]:
            raise ValueError("candidate_target_not_empty")
        status, _ = await self._request("GET", f"collections/{name}")
        if status != 404:
            raise ValueError("candidate_collection_already_exists")
        unauthenticated, _ = await self._request("GET", "collections", authenticated=False)
        if unauthenticated not in {401, 403}:
            raise ValueError("candidate_authentication_not_enforced")
        permission_probe = await self.probe_read_only_update()
        return {
            "server_version": root["version"],
            "empty_dedicated_target": True,
            "candidate_absent": True,
            "unauthenticated_status": unauthenticated,
            **permission_probe,
            "aliases_before": await self.aliases(),
        }

    async def verify(
        self, name: str, embedded: Sequence[EmbeddedChunk], aliases_before: list
    ) -> dict:
        name = QdrantCandidateWriter._name(name)
        expected = {item.chunk.point_id: item for item in embedded}
        if not expected or len(expected) != len(embedded) or len(expected) > 10000:
            raise ValueError("candidate_audit_expected_mapping_invalid")
        info = await self._ok("GET", f"collections/{name}")
        vectors = info.get("config", {}).get("params", {}).get("vectors", {})
        dimensions = len(embedded[0].vector)
        if vectors.get("size") != dimensions or vectors.get("distance") != "Cosine":
            raise ValueError("candidate_audit_vector_configuration_mismatch")
        if info.get("status") not in {"green", "yellow"}:
            raise ValueError("candidate_audit_collection_unhealthy")
        count = await self._ok("POST", f"collections/{name}/points/count", {"exact": True})
        if count.get("count") != len(expected):
            raise ValueError("candidate_audit_count_mismatch")
        seen: set[str] = set()
        offset = None
        pages = 0
        while True:
            body = {"limit": 8, "with_payload": True, "with_vector": True}
            if offset is not None:
                body["offset"] = offset
            result = await self._ok("POST", f"collections/{name}/points/scroll", body)
            points = result.get("points") if isinstance(result, dict) else None
            pages += 1
            if not isinstance(points, list) or len(points) > 8 or pages > len(expected) + 1:
                raise ValueError("candidate_audit_invalid_page")
            for point in points:
                point_id = point.get("id") if isinstance(point, dict) else None
                item = expected.get(point_id) if isinstance(point_id, str) else None
                if item is None or point_id in seen:
                    raise ValueError("candidate_audit_point_mapping_mismatch")
                if point.get("payload") != item.chunk.model_dump(mode="json"):
                    raise ValueError("candidate_audit_payload_mismatch")
                vector = point.get("vector")
                if (
                    not isinstance(vector, list)
                    or len(vector) != dimensions
                    or any(type(v) not in {float, int} or not math.isfinite(v) for v in vector)
                ):
                    raise ValueError("candidate_audit_invalid_vector")
                norm = math.hypot(*item.vector)
                if not math.isfinite(norm) or norm <= 0:
                    raise ValueError("candidate_audit_invalid_vector")
                # Qdrant normalizes Cosine vectors and stores float32: compare
                # normalized values rather than demand unchanged JSON floats.
                if any(
                    abs(a / norm - b) > 0.00001 for a, b in zip(item.vector, vector, strict=True)
                ):
                    raise ValueError("candidate_audit_vector_mismatch")
                if abs(math.hypot(*vector) - 1) > 0.00001:
                    raise ValueError("candidate_audit_invalid_vector")
                seen.add(point_id)
            next_offset = result.get("next_page_offset")
            if next_offset is None:
                break
            if not points or next_offset == offset or next_offset not in expected:
                raise ValueError("candidate_audit_invalid_offset")
            offset = next_offset
        if seen != set(expected):
            raise ValueError("candidate_audit_incomplete")
        if await self.aliases() != aliases_before:
            raise ValueError("candidate_audit_aliases_changed")
        permission_probe = await self.probe_read_only_update()
        return {
            "points_verified": len(seen),
            "scroll_pages": pages,
            "exact_payloads_verified": True,
            "normalized_vectors_verified": True,
            "point_inventory_hash": stable_id(*sorted(seen)),
            **permission_probe,
            "aliases_unchanged": True,
            "collection_status": info["status"],
            "status": "candidate_verified_unpublished",
        }

    async def aclose(self) -> None:
        async with asyncio.timeout(self.settings.shutdown_timeout_seconds):
            await self.http.aclose()
