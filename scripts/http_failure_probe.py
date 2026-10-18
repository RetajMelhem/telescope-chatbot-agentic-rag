"""Isolated, explicitly mounted diagnostic factory; never installed in the product.

Only the supplied public evaluation payloads are admitted, for at most 30 logical
requests. The original application source, settings, provider attempts and result
are unchanged. Credentials, headers and embedding vectors are never exported.
"""

import asyncio
import json
from pathlib import Path

import httpx2 as httpx

from telescope_rag.api.local import create_local_app
from telescope_rag.core.errors import ApplicationError
from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.validation import load_json


class _ChatStream(httpx.AsyncByteStream):
    """Observe completed bodies without replacing bytes, headers, or failures."""

    def __init__(self, inner, row):
        self.inner, self.row = inner, row

    async def __aiter__(self):
        raw = bytearray()
        oversized = False
        async for chunk in self.inner:
            if len(raw) + len(chunk) > 2_000_000:
                oversized = True
                raw.clear()
            if not oversized:
                raw.extend(chunk)
            yield chunk
        if oversized:
            self.row["capture_status"] = "response_exceeds_capture_limit"
            return
        try:
            body = load_json(bytes(raw))
        except ProviderError:
            self.row["capture_status"] = "invalid_json"
        else:
            self.row.update(
                capture_status="complete",
                response={
                    key: body[key]
                    for key in ("id", "model", "provider", "usage", "choices")
                    if key in body
                },
            )

    async def aclose(self):
        await self.inner.aclose()


class ChatAudit(httpx.AsyncBaseTransport):
    def __init__(self):
        self.inner = httpx.AsyncHTTPTransport(retries=0)
        self.rows: list[dict] = []

    async def handle_async_request(self, request):
        if request.url.host != "openrouter.ai" or request.method != "POST":
            raise ValueError("diagnostic_provider_target_invalid")
        response = await self.inner.handle_async_request(request)
        if request.url.path != "/api/v1/chat/completions":
            return response
        row = {"status_code": response.status_code, "capture_status": "incomplete"}
        self.rows.append(row)
        response.stream = _ChatStream(response.stream, row)
        return response

    async def aclose(self):
        await self.inner.aclose()


def create_probe_app():
    # Both files are explicit diagnostic mounts, separate from product data.
    config = json.loads(Path("/diagnostic-config/requests.json").read_bytes())
    if not 1 <= len(config) <= 3 or any(
        set(row) != {"query", "language", "history"} or row["history"] != [] for row in config
    ):
        raise ValueError("diagnostic_payloads_invalid")
    output = Path("/diagnostic-output")
    if not output.is_dir() or any(output.glob("*.json")):
        raise ValueError("diagnostic_output_must_be_empty")
    # The observer module is copied explicitly into this diagnostic image only.
    from evaluation_trace import install_capture

    audit = ChatAudit()
    app = create_local_app(Path("/runtime"), runtime="container", provider_transport=audit)
    capture = install_capture(app)
    original = app.state.offline_chat_service._run
    lock = asyncio.Lock()
    attempted = 0

    async def captured_run(payload, *, request_id):
        nonlocal attempted
        supplied = payload.model_dump(mode="json")
        if supplied not in config:
            raise ApplicationError(422, "diagnostic_payload_rejected", "Unapproved probe request.")
        async with lock:
            if attempted >= 30:
                raise ApplicationError(429, "diagnostic_limit_reached", "Probe limit reached.")
            attempted += 1
            capture.reset(request_id.hex)
            audit.rows = []
            try:
                return await original(payload, request_id=request_id)
            finally:
                # Public benchmark content is caller-authorized local audit data,
                # not a default application log or an API debug response.
                row = {
                    "request_id": request_id.hex,
                    "ordinal": attempted,
                    "request_payload": supplied,
                    "trace": capture.snapshot(),
                    "provider_chat_responses": audit.rows,
                }
                with (output / f"{request_id.hex}.json").open("x", encoding="utf-8") as stream:
                    json.dump(row, stream, ensure_ascii=False, allow_nan=False)

    app.state.offline_chat_service._run = captured_run
    return app
