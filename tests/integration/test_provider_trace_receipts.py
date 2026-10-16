"""Optional trace metadata survives failures without admitting arbitrary content."""

import asyncio
import json
from dataclasses import asdict
from datetime import datetime

import httpx2 as httpx
import pytest
from test_providers import SyntheticCounter, chat_body, complete, config

from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.openrouter import OpenRouterProviders


@pytest.mark.parametrize("failure", [None, "reported_model_mismatch", "provider_error_response"])
def test_trace_metadata_and_timestamps_survive_provider_decoding_failure(failure):
    async def run():
        settings = config()
        budget = ExecutionBudget(settings)
        body = chat_body(id="gen-1234-Test", request_id="req-Test-5678")
        if failure == "reported_model_mismatch":
            body["model"] = "synthetic-wrong-model"
        elif failure == "provider_error_response":
            body["error"] = {"message": "untrusted provider content"}
        async with OpenRouterProviders(
            settings,
            token_counter=SyntheticCounter(),
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
        ) as providers:
            if failure:
                with pytest.raises(ProviderError, match=f"^{failure}$"):
                    await complete(providers, budget)
            else:
                await complete(providers, budget)
        receipt = budget.receipts[0]
        assert receipt.generation_id == "gen-1234-Test"
        assert receipt.request_id == "req-Test-5678"
        start, end = map(datetime.fromisoformat, (receipt.started_at_utc, receipt.finished_at_utc))
        assert start.tzinfo is not None and start <= end
        serialized = json.dumps(asdict(receipt), default=str)
        assert "synthetic-model-key" not in serialized
        assert "untrusted provider content" not in serialized
        assert len(budget.receipts) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad",
    [
        None,
        4,
        {},
        "gen-",
        "gen-secret with spaces",
        "req-x",
        "gen-" + "x" * 129,
        "gen-عربي",
        "gen-underscore_invalid",
        "gen-abc\nxyz",
    ],
)
def test_missing_or_invalid_generation_metadata_never_blocks_valid_answer(bad):
    async def run():
        settings = config()
        budget = ExecutionBudget(settings)
        async with OpenRouterProviders(
            settings,
            token_counter=SyntheticCounter(),
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=chat_body(id=bad))),
        ) as providers:
            result = await complete(providers, budget)
        assert result.data.count == 1
        assert budget.receipts[0].generation_id is None
        assert budget.receipts[0].request_id is None

    asyncio.run(run())


def test_transport_failure_receipt_has_timestamps_and_no_invented_identifier():
    async def run():
        settings = config(provider_max_retries=0)
        budget = ExecutionBudget(settings)

        def fail(request):
            raise httpx.ConnectError("synthetic connection failure", request=request)

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(fail)
        ) as providers:
            with pytest.raises(ProviderError, match="^provider_connection_failed$"):
                await complete(providers, budget)
        receipt = budget.receipts[0]
        assert receipt.generation_id is None and receipt.request_id is None
        assert receipt.started_at_utc and receipt.finished_at_utc
        assert len(budget.receipts) == 1

    asyncio.run(run())
