"""A diagnostic must not expand paid scope, hide failures, or export secrets."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx2 as httpx
import pytest

from scripts import http_failure_probe as probe
from telescope_rag.core.errors import ApplicationError

PAYLOAD = {"query": "Synthetic public question", "language": "en", "history": []}
SECRET = "synthetic-private-header"


def fixture(monkeypatch, tmp_path, *, failure=None):
    config = tmp_path / "requests.json"
    config.write_text(json.dumps([PAYLOAD]), encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    paths = {"/diagnostic-config/requests.json": config, "/diagnostic-output": output}
    monkeypatch.setattr(probe, "Path", lambda value: paths.get(value, Path(value)))
    calls = []
    capture = SimpleNamespace(reset=lambda _: None, snapshot=lambda: {"synthetic": True})
    monkeypatch.setitem(
        sys.modules, "evaluation_trace", SimpleNamespace(install_capture=lambda _: capture)
    )

    async def original(payload, *, request_id):
        calls.append(request_id)
        if failure is not None:
            raise failure
        return "original-result"

    app = SimpleNamespace(
        state=SimpleNamespace(offline_chat_service=SimpleNamespace(_run=original))
    )
    monkeypatch.setattr(probe, "create_local_app", lambda *args, **kwargs: app)
    monkeypatch.setattr(probe, "ChatAudit", lambda: SimpleNamespace(rows=[]))
    probe.create_probe_app()
    return app.state.offline_chat_service._run, calls, output


def payload(value=PAYLOAD):
    return SimpleNamespace(model_dump=lambda **_: value)


def test_only_approved_payloads_can_reach_the_original_run(monkeypatch, tmp_path):
    run, calls, output = fixture(monkeypatch, tmp_path)
    with pytest.raises(ApplicationError, match="^diagnostic_payload_rejected$"):
        asyncio.run(run(payload({**PAYLOAD, "query": "Different question"}), request_id=uuid4()))
    assert calls == []
    assert list(output.iterdir()) == []


def test_thirty_request_limit_is_enforced_before_dispatch(monkeypatch, tmp_path):
    run, calls, output = fixture(monkeypatch, tmp_path)

    async def attempt():
        for _ in range(30):
            assert await run(payload(), request_id=uuid4()) == "original-result"
        with pytest.raises(ApplicationError, match="^diagnostic_limit_reached$"):
            await run(payload(), request_id=uuid4())

    asyncio.run(attempt())
    assert len(calls) == len(list(output.glob("*.json"))) == 30


def test_failure_is_preserved_and_captured_without_exception_text(monkeypatch, tmp_path):
    error = ValueError(SECRET)
    run, calls, output = fixture(monkeypatch, tmp_path, failure=error)
    request_id = uuid4()
    with pytest.raises(ValueError) as caught:
        asyncio.run(run(payload(), request_id=request_id))
    assert caught.value is error
    assert calls == [request_id]
    raw = (output / f"{request_id.hex}.json").read_text("utf-8")
    assert SECRET not in raw
    assert json.loads(raw)["trace"] == {"synthetic": True}
    with pytest.raises(ValueError, match="diagnostic_output_must_be_empty"):
        probe.create_probe_app()


def test_audit_keeps_chat_content_but_never_headers_or_embedding_vectors():
    raw = b'{"choices":[{"message":{"content":"public"}}],"usage":{},"extra":"omit"}'
    vector = b'{"data":[{"embedding":[123.456,789.012]}]}'
    seen = []

    def upstream(request):
        seen.append(request)
        body = raw if request.url.path.endswith("completions") else vector
        return httpx.Response(200, stream=httpx.ByteStream(body), headers={"x-private": SECRET})

    audit = probe.ChatAudit()
    audit.inner = httpx.MockTransport(upstream)

    async def attempt():
        for path, expected in (("chat/completions", raw), ("embeddings", vector)):
            request = httpx.Request(
                "POST", f"https://openrouter.ai/api/v1/{path}", headers={"authorization": SECRET}
            )
            response = await audit.handle_async_request(request)
            assert await response.aread() == expected
            assert response.headers["x-private"] == SECRET
        with pytest.raises(ValueError, match="diagnostic_provider_target_invalid"):
            await audit.handle_async_request(httpx.Request("POST", "https://example.invalid/"))
        await audit.aclose()

    asyncio.run(attempt())
    assert len(seen) == 2
    assert len(audit.rows) == 1
    encoded = json.dumps(audit.rows)
    assert SECRET not in encoded and "123.456" not in encoded and "omit" not in encoded


@pytest.mark.parametrize(
    "body,status",
    [
        (b"not json", "invalid_json"),
        (b'{"usage":{"cost":NaN}}', "invalid_json"),
        (b'{"choices":[],"choices":[]}', "invalid_json"),
        (b"x" * 2_000_001, "response_exceeds_capture_limit"),
    ],
    ids=["plain-text", "nonfinite", "duplicate-key", "oversized"],
)
def test_audit_forwards_invalid_or_oversized_responses_unchanged(body, status):
    upstream_response = httpx.Response(
        503,
        headers={"content-type": "text/plain", "retry-after": "7"},
        stream=httpx.ByteStream(body),
    )
    audit = probe.ChatAudit()
    audit.inner = httpx.MockTransport(lambda _: upstream_response)

    async def attempt():
        response = await audit.handle_async_request(
            httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        )
        assert response is upstream_response
        assert await response.aread() == body
        assert response.headers["retry-after"] == "7"
        await audit.aclose()

    asyncio.run(attempt())
    assert audit.rows == [{"status_code": 503, "capture_status": status}]


def test_audit_preserves_stream_exception_identity():
    error = httpx.ReadError(SECRET)

    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"choices":'
            raise error

    audit = probe.ChatAudit()
    audit.inner = httpx.MockTransport(lambda _: httpx.Response(200, stream=Broken()))

    async def attempt():
        response = await audit.handle_async_request(
            httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        )
        with pytest.raises(httpx.ReadError) as caught:
            await response.aread()
        assert caught.value is error
        await audit.aclose()

    asyncio.run(attempt())
    assert audit.rows == [{"status_code": 200, "capture_status": "incomplete"}]
    assert SECRET not in json.dumps(audit.rows)
