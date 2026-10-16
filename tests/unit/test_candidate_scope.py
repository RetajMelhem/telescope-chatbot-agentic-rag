"""Pinned inventory and pre-ranking ID-filter contracts; mock HTTP only."""

import asyncio
import json

import pytest
from test_candidate_retrieval import VECTOR, chunk, point, reader, response


def test_scoped_query_uses_id_filter_before_top_k():
    async def run():
        calls = []

        def handler(request):
            body = json.loads(request.content)
            calls.append(body)
            assert body["filter"] == {"must": [{"has_id": [chunk(2).point_id]}]}
            assert body["limit"] == 1 and body["params"] == {"exact": True}
            return response([point(chunk(2))])

        client = reader(handler)
        try:
            assert (await client.search(VECTOR, limit=1, point_ids=[chunk(2).point_id]))[
                0
            ].chunk == chunk(2)
            assert len(calls) == 1
        finally:
            await client.aclose()

    asyncio.run(run())


def test_server_returning_known_but_out_of_scope_point_is_rejected():
    async def run():
        client = reader(lambda request: response([point(chunk(2))]))
        try:
            with pytest.raises(ValueError, match="point_outside_scope"):
                await client.search(VECTOR, point_ids=[chunk().point_id])
        finally:
            await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "ids",
    [
        "not-a-list",
        [None],
        ["unknown"],
        [chunk().point_id] * 2,
        {chunk().point_id},
        [chunk().point_id] * 10001,
    ],
)
def test_invalid_id_scope_stops_before_http(ids):
    async def run():
        client = reader(lambda request: pytest.fail("No request expected"))
        try:
            with pytest.raises(ValueError, match="invalid_point_scope"):
                await client.search(VECTOR, point_ids=ids)
        finally:
            await client.aclose()

    asyncio.run(run())


def test_empty_id_scope_does_not_become_an_unfiltered_search():
    async def run():
        client = reader(lambda request: pytest.fail("No request expected"))
        try:
            assert await client.search(VECTOR, point_ids=[]) == ()
        finally:
            await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("case", ["exact", "missing", "altered"])
def test_complete_inventory_binding_is_pure_and_rejects_drift(case):
    async def run():
        client = reader(lambda request: pytest.fail("No request expected"))
        try:
            inventory = {c.point_id: c for c in (chunk(), chunk(2))}
            if case == "missing":
                inventory.pop(chunk(2).point_id)
            elif case == "altered":
                inventory[chunk().point_id] = chunk().model_copy(
                    update={"doctor_name": "Different owner"}
                )
            if case == "exact":
                client.check_inventory(inventory)
            else:
                with pytest.raises(ValueError, match="inventory_mismatch"):
                    client.check_inventory(inventory)
        finally:
            await client.aclose()

    asyncio.run(run())
