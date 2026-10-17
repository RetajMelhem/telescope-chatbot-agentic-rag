"""Explicit local audit transport for approved development screens, never default logs.

The caller owns dispatch authorization and supplies a transport. Headers are never
recorded. Request slots are allocated before I/O so concurrent reads cannot collide.
"""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx2 as httpx


class ScreenTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        delegate: httpx.AsyncBaseTransport,
        directory: Path,
        *,
        kind: Literal["provider", "qdrant"],
        allowed_paths: frozenset[str],
        max_attempts: int,
    ) -> None:
        if kind not in {"provider", "qdrant"} or not 1 <= max_attempts <= 12 or not allowed_paths:
            raise ValueError("screen_transport_configuration_invalid")
        if not directory.is_dir():
            raise ValueError("screen_transport_directory_required")
        self._delegate, self._directory, self._kind = delegate, directory, kind
        self._allowed_paths, self._max_attempts = allowed_paths, max_attempts
        self._reserved = 0
        self.rows: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.method != "POST"
            or str(request.url) not in self._allowed_paths
            or self._reserved >= self._max_attempts
            or len(request.content) > 262144
        ):
            raise ValueError("screen_transport_request_not_allowed")
        payload = json.loads(request.content)
        # There is no await between reserving the slot and opening its file.
        self._reserved += 1
        path = self._directory / f"{self._kind}-http-{self._reserved:02}.json"
        with path.open("x", encoding="utf-8") as stream:
            row: dict = {
                "method": request.method,
                "url": str(request.url),
                "at_utc": datetime.now(UTC).isoformat(),
                "payload": payload,
                "status_code": None,
                "error_type": None,
            }
            if self._kind == "qdrant":
                row["payload"] = {k: v for k, v in payload.items() if k != "query"}
                row["query_dimensions"] = len(payload.get("query", []))
                row["query_vector_sha256"] = hashlib.sha256(
                    json.dumps(payload.get("query")).encode()
                ).hexdigest()
            started = time.monotonic()
            response = None
            try:
                response = await self._delegate.handle_async_request(request)
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 2_000_000:
                        raise ValueError("screen_transport_response_too_large")
                    raw.extend(chunk)
                row["status_code"] = response.status_code
                try:
                    body = json.loads(raw)
                    if self._kind == "provider":
                        row["response"] = {
                            k: body[k]
                            for k in ("id", "request_id", "model", "provider", "usage", "choices")
                            if k in body
                        }
                        if "data" in body:
                            # Explicit local audit only; these public development
                            # vectors never enter the persistent query cache.
                            row["response"]["data"] = body["data"]
                    else:
                        row["response"] = body
                except (ValueError, TypeError):
                    row["response_sha256"] = hashlib.sha256(raw).hexdigest()
                return httpx.Response(
                    response.status_code,
                    headers={"content-type": response.headers.get("content-type", "")},
                    content=bytes(raw),
                )
            except BaseException as error:
                row["error_type"] = type(error).__name__
                raise
            finally:
                if response is not None:
                    await response.aclose()
                row["elapsed_seconds"] = time.monotonic() - started
                self.rows.append(row)
                json.dump(row, stream, ensure_ascii=False, allow_nan=False, indent=2)

    async def aclose(self) -> None:
        await self._delegate.aclose()
