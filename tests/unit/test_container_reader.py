"""The container route adds one fixed local DNS target; all read guards remain."""

import asyncio
import json

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from test_candidate_retrieval import COLLECTION, VECTOR, chunk, point, response

from telescope_rag.core.settings import Settings
from telescope_rag.retrieval.candidate import CandidateDenseReader


def construct(target="loopback", url="http://telescope-m3-qdrant:6333", handler=None):
    item = chunk()
    return CandidateDenseReader(
        Settings(_env_file=None, app_env="test", qdrant_url=url),
        SecretStr("synthetic-read"),
        collection=COLLECTION,
        chunks={item.point_id: item},
        target=target,
        transport=httpx.MockTransport(handler or (lambda r: response([point()]))),
    )


@pytest.mark.parametrize(
    "target,url",
    [
        ("loopback", "http://telescope-m3-qdrant:6333"),
        ("local_container", "http://127.0.0.1:6333"),
        ("local_container", "http://qdrant:6333"),
        ("local_container", "http://telescope-m3-qdrant:6334"),
        ("local_container", "https://example.com"),
        ("other", "http://127.0.0.1:6333"),
    ],
)
def test_other_targets_and_missing_container_opt_in_are_rejected(target, url):
    with pytest.raises(ValueError, match="local_target_required"):
        construct(target, url)


def test_container_keeps_exact_scoped_authenticated_read_and_rejects_write():
    async def run():
        calls = []

        def handle(request):
            calls.append(request)
            assert str(request.url) == (
                f"http://telescope-m3-qdrant:6333/collections/{COLLECTION}/points/query"
            )
            assert request.headers["api-key"] == "synthetic-read"
            body = json.loads(request.content)
            assert body["filter"] == {"must": [{"has_id": [chunk().point_id]}]}
            assert body["params"] == {"exact": True}
            return response([point()])

        client = construct("local_container", handler=handle)
        try:
            assert (await client.search(VECTOR, limit=1, point_ids=(chunk().point_id,)))[
                0
            ].chunk == chunk()
            with pytest.raises(ValueError, match="route_not_allowed"):
                await client._request("PUT", f"collections/{COLLECTION}", {})
            assert len(calls) == 1
        finally:
            await client.aclose()

    asyncio.run(run())
