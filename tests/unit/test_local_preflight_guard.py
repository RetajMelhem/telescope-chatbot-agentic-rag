"""Synthetic permission-check boundaries; never connect to the real local database."""

import asyncio
from pathlib import Path

import pytest
from pydantic import SecretStr

from telescope_rag.core.settings import Settings


@pytest.fixture
def checker(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))
    from scripts import check_local_qdrant_preflight

    return check_local_qdrant_preflight


@pytest.mark.parametrize(
    "method,path,body,authenticated",
    [
        ("PUT", "collections/telescope_public_" + "b" * 24, {}, True),
        ("DELETE", "collections/telescope_public_" + "b" * 24, None, True),
        ("POST", "collections/telescope_public_" + "b" * 24 + "/points", {}, True),
        ("PATCH", "collections/telescope_public_" + "a" * 24, {}, True),
        ("PATCH", "collections/telescope_public_" + "b" * 24, {"vectors": {}}, True),
        ("PATCH", "collections/telescope_public_" + "b" * 24, {}, False),
        ("GET", "https://outside.invalid/", None, True),
        ("GET", "//outside.invalid/collections", None, True),
        ("GET", "collections/foreign_collection", None, True),
    ],
)
def test_disallowed_requests_stop_before_transport(
    checker, monkeypatch, method, path, body, authenticated
):
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        pytest.fail("Rejected request must not reach transport or forward a key")

    monkeypatch.setattr(checker.QdrantCandidateAudit, "_request", forbidden)

    async def scenario():
        audit = checker.RestrictedAudit(
            Settings(_env_file=None, openrouter_api_key="", qdrant_api_key=""),
            SecretStr("synthetic-reader"),
            "reader",
            "telescope_public_" + "a" * 24,
            [],
            {path},
        )
        try:
            with pytest.raises(ValueError, match="not_permitted"):
                await audit._request(method, path, body, authenticated=authenticated)
            assert calls == []
        finally:
            await audit.aclose()

    asyncio.run(scenario())


def test_update_requires_prior_absence_and_request_cap_is_global(checker, monkeypatch):
    calls = []

    async def fake(self, method, path, body=None, *, authenticated=True):
        calls.append((method, path, body, authenticated))
        return (403 if method == "PATCH" else 404), {}

    monkeypatch.setattr(checker.QdrantCandidateAudit, "_request", fake)

    async def scenario():
        events, absent = [], set()
        path = "collections/telescope_public_" + "b" * 24
        audit = checker.RestrictedAudit(
            Settings(_env_file=None, openrouter_api_key="", qdrant_api_key=""),
            SecretStr("synthetic-reader"),
            "reader",
            "telescope_public_" + "a" * 24,
            events,
            absent,
        )
        try:
            with pytest.raises(ValueError, match="not_permitted"):
                await audit._request("PATCH", path, {})
            assert not calls
            assert (await audit._request("GET", path))[0] == 404
            assert (await audit._request("PATCH", path, {}))[0] == 403
            assert (await audit._request("GET", path))[0] == 404
            assert [r["method"] for r in events] == ["GET", "PATCH", "GET"]
            events.extend({} for _ in range(37))
            with pytest.raises(ValueError, match="request_cap"):
                await audit._request("GET", "collections")
            assert len(calls) == 3
        finally:
            await audit.aclose()

    asyncio.run(scenario())
