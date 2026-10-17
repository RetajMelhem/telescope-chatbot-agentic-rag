"""Concurrency and audit bounds with mocked sockets; no provider/index requests."""

import asyncio
import json

import httpx2 as httpx
import pytest

from telescope_rag.providers.screen_audit import ScreenTransport

URL = "http://127.0.0.1:6333/collections/synthetic/points/query"


def transport(tmp_path, handler, *, maximum=2):
    return ScreenTransport(
        httpx.MockTransport(handler),
        tmp_path,
        kind="qdrant",
        allowed_paths=frozenset({URL}),
        max_attempts=maximum,
    )


def test_concurrent_reads_reserve_unique_files_before_either_response(tmp_path):
    async def run():
        arrivals = []
        both_started = asyncio.Event()

        async def handler(request):
            body = json.loads(request.read())
            arrivals.append(body["part"])
            if len(arrivals) == 2:
                both_started.set()
            await both_started.wait()
            return httpx.Response(200, json={"result": {"part": body["part"]}})

        audit = transport(tmp_path, handler)
        async with httpx.AsyncClient(transport=audit) as client:
            responses = await asyncio.wait_for(
                asyncio.gather(
                    *(
                        client.post(
                            URL,
                            json={"part": part, "query": [1.0, 0.0]},
                            headers={"api-key": "synthetic-secret-never-recorded"},
                        )
                        for part in ("first", "second")
                    )
                ),
                timeout=2,
            )
        assert [r.json()["result"]["part"] for r in responses] == ["first", "second"]
        paths = sorted(tmp_path.glob("qdrant-http-*.json"))
        assert [p.name for p in paths] == ["qdrant-http-01.json", "qdrant-http-02.json"]
        records = [json.loads(p.read_bytes()) for p in paths]
        assert [r["payload"]["part"] for r in records] == ["first", "second"]
        assert all(r["status_code"] == 200 and r["error_type"] is None for r in records)
        assert all("query" not in r["payload"] for r in records)
        assert all("synthetic-secret-never-recorded" not in p.read_text() for p in paths)

    asyncio.run(run())


def test_attempt_bound_counts_inflight_reads_before_dispatch(tmp_path):
    async def run():
        calls = []

        async def handler(request):
            calls.append(request)
            await asyncio.sleep(0)
            return httpx.Response(200, json={"result": {}})

        async with httpx.AsyncClient(transport=transport(tmp_path, handler, maximum=1)) as client:
            results = await asyncio.gather(
                *(client.post(URL, json={"query": [1.0]}) for _ in range(2)), return_exceptions=True
            )
        assert len(calls) == 1
        assert sum(isinstance(r, ValueError) for r in results) == 1
        assert len(list(tmp_path.iterdir())) == 1

    asyncio.run(run())


def test_existing_journal_path_stops_before_any_network_call(tmp_path):
    (tmp_path / "qdrant-http-01.json").write_text("preserved", encoding="utf-8")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    async def run():
        async with httpx.AsyncClient(transport=transport(tmp_path, handler)) as client:
            with pytest.raises(FileExistsError):
                await client.post(URL, json={"query": [1.0]})
        assert calls == []
        assert (tmp_path / "qdrant-http-01.json").read_text() == "preserved"

    asyncio.run(run())
