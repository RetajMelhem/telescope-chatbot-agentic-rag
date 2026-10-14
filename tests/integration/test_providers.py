"""Offline boundary tests: synthetic credentials, counts, formats, and HTTP responses."""

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import httpx2 as httpx
import pytest
from pydantic import BaseModel, ConfigDict

from telescope_rag.core.settings import Settings
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import (
    ChatMessage,
    EmbeddingFormat,
    OperationKind,
    TokenCount,
)
from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.openrouter import OpenRouterProviders


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str
    count: int


class SyntheticCounter:
    def __init__(self, units: int = 100) -> None:
        self.units = units
        self.inputs: list[dict[str, Any]] = []

    def count(self, kind: OperationKind, payload: Mapping[str, Any]) -> TokenCount:
        self.inputs.append(dict(payload))
        return TokenCount(
            units=self.units,
            model=payload["model"],
            profile="synthetic-fixture",
            basis="upper_bound",
        )


def config(**overrides: Any) -> Settings:
    values = {
        "app_env": "test",
        "openrouter_api_key": "synthetic-model-key",
        "embedding_dimensions": 32,
        "provider_retry_delay_seconds": 0,
    }
    return Settings(_env_file=None, **(values | overrides))


def chat_body(**overrides: Any) -> dict[str, Any]:
    return {
        "model": "openai/gpt-6-luna",
        "provider": "SyntheticProvider",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": '{"answer":"أهلاً","count":1}'},
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 8,
            "total_tokens": 18,
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    } | overrides


def embedding_body() -> dict[str, Any]:
    return {
        "model": "qwen/qwen3-embedding-8b",
        "data": [{"index": 1, "embedding": [2.0] * 32}, {"index": 0, "embedding": [1.0] * 32}],
        "usage": {"prompt_tokens": 10, "total_tokens": 10},
    }


MESSAGES = [ChatMessage(role="user", content="مين الدكاترة؟ And what are their specialties?")]
FORMAT = EmbeddingFormat(
    version="synthetic-test-v1", verified=True, query_prefix="Instruct: synthetic test\nQuery: "
)


async def complete(providers: OpenRouterProviders, budget: ExecutionBudget):
    return await providers.chat.complete(MESSAGES, Answer, max_output_tokens=64, budget=budget)


def test_chat_wire_bilingual_and_content_free_receipt() -> None:
    async def scenario() -> None:
        settings, counter = config(), SyntheticCounter()
        budget = ExecutionBudget(settings)
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            payload = json.loads(request.read())
            assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer synthetic-model-key"
            assert payload["messages"][0]["content"] == MESSAGES[0].content
            assert payload["response_format"]["json_schema"]["strict"] is True
            assert payload["provider"] == {"require_parameters": True, "allow_fallbacks": False}
            assert payload["max_completion_tokens"] == 64
            assert not ({"tools", "plugins", "models", "temperature"} & payload.keys())
            return httpx.Response(200, json=chat_body())

        async with OpenRouterProviders(
            settings, token_counter=counter, transport=httpx.MockTransport(handler)
        ) as providers:
            assert not requests and not counter.inputs
            result = await complete(providers, budget)
            assert result.data.answer == "أهلاً"
            assert result.data.count == 1
            assert len(result.receipts) == 1
            assert result.receipts[0].usage.reasoning_tokens == 2
            assert budget.input_charged["chat"] == 10
            assert budget.output_charged == 8  # reasoning is a subset, not another charge
            assert counter.inputs[0]["response_format"]["json_schema"]["schema"]
            assert MESSAGES[0].content not in repr(result)
            assert "synthetic-model-key" not in repr(result)
        assert len(requests) == 1
        with pytest.raises(ProviderError, match="^provider_closed$"):
            await complete(providers, budget)

    asyncio.run(scenario())


@pytest.mark.parametrize("role", ["query", "document"])
def test_embeddings_reorder_and_format_exactly_once(role: str) -> None:
    async def scenario() -> None:
        settings = config()
        texts = [" د. أحمد / طب عيون ", "Doctor details\nTreatment techniques"]

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.read())
            prefix = FORMAT.query_prefix if role == "query" else ""
            assert payload["input"] == [prefix + text for text in texts]
            assert str(request.url) == "https://openrouter.ai/api/v1/embeddings"
            assert payload["dimensions"] == 32 and payload["encoding_format"] == "float"
            assert payload["provider"]["allow_fallbacks"] is False
            return httpx.Response(200, json=embedding_body())

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            result = await providers.embeddings.embed(
                texts, role=role, format=FORMAT, budget=ExecutionBudget(settings)
            )
            assert result.vectors == ((1.0,) * 32, (2.0,) * 32)
            assert result.format_version == FORMAT.version
            assert texts[0] not in repr(result)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case,code",
    [
        ("missing_key", "missing_provider_credentials"),
        ("invalid_key", "invalid_provider_credentials"),
        ("counter", "token_count_unavailable"),
        ("count_model", "incompatible_token_count"),
        ("input", "token_or_attempt_budget_exhausted"),
        ("output", "token_or_attempt_budget_exhausted"),
        ("operations", "operation_budget_exhausted"),
        ("request_size", "provider_request_too_large"),
        ("deadline", "execution_budget_exhausted"),
    ],
)
def test_preflight_failures_make_zero_http_requests(case: str, code: str) -> None:
    async def scenario() -> None:
        overrides = {
            "missing_key": {"openrouter_api_key": ""},
            "invalid_key": {"openrouter_api_key": "unsafe\nkey"},
            "output": {"max_total_output_tokens": 32},
            "request_size": {"provider_max_request_bytes": 10},
        }
        settings = config(**overrides.get(case, {}))
        counter = None if case == "counter" else SyntheticCounter()
        if case == "input":
            counter = SyntheticCounter(20000)
        if case == "count_model":

            class WrongCounter(SyntheticCounter):
                def count(self, kind, payload):
                    return TokenCount(
                        units=100, model="wrong/model", profile="fixture", basis="exact"
                    )

            counter = WrongCounter()
        budget = ExecutionBudget(settings)
        if case == "operations":
            for _ in range(settings.max_llm_calls):
                budget.begin("chat")
        if case == "deadline":
            budget.deadline = 0

        def handler(request):
            pytest.fail("preflight failure dispatched HTTP")

        async with OpenRouterProviders(
            settings, token_counter=counter, transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError, match=f"^{code}$"):
                await complete(providers, budget)
            assert not budget.receipts and budget.attempts["chat"] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status,retry",
    [
        (400, False),
        (401, False),
        (402, False),
        (403, False),
        (404, False),
        (422, False),
        (429, True),
        (500, False),
        (502, True),
        (503, True),
        (504, False),
        (307, False),
    ],
)
def test_http_retry_allowlist_and_safe_errors(status: int, retry: bool) -> None:
    async def scenario() -> None:
        settings, calls = config(), []
        budget = ExecutionBudget(settings)

        def handler(request):
            calls.append(request)
            return httpx.Response(status, json={"error": "secret upstream query and key"})

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError) as caught:
                await complete(providers, budget)
            assert caught.value.status_code == status
            assert "secret" not in str(caught.value) and "secret" not in repr(budget.receipts)
        expected = 2 if retry else 1
        assert len(calls) == len(budget.receipts) == expected
        assert budget.input_charged["chat"] == expected * 100
        assert budget.output_charged == expected * 64

    asyncio.run(scenario())


def test_retry_success_has_both_receipts_and_retains_unknown_first_charge() -> None:
    async def scenario() -> None:
        settings, calls = config(), []
        budget = ExecutionBudget(settings)

        def handler(request):
            calls.append(request)
            return httpx.Response(
                503 if len(calls) == 1 else 200, json={} if len(calls) == 1 else chat_body()
            )

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            result = await complete(providers, budget)
        assert [receipt.attempt for receipt in result.receipts] == [1, 2]
        assert [receipt.outcome for receipt in result.receipts] == [
            "provider_unavailable",
            "success",
        ]
        assert budget.operations["chat"] == 1
        assert budget.input_charged["chat"] == 110 and budget.output_charged == 72

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "retry_after,code",
    [
        ("999", "retry_deadline_exhausted"),
        ("tomorrow", "provider_rate_limited"),
        ("-1", "provider_rate_limited"),
        ("nan", "provider_rate_limited"),
    ],
)
def test_retry_after_is_not_shortened_or_guessed(retry_after: str, code: str) -> None:
    async def scenario() -> None:
        settings, calls = config(), []

        def handler(request):
            calls.append(request)
            return httpx.Response(429, json={}, headers={"retry-after": retry_after})

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError, match=f"^{code}$"):
                await complete(providers, ExecutionBudget(settings))
        assert len(calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("limit", ["input", "output"])
def test_retry_reserves_again_before_dispatch(limit: str) -> None:
    async def scenario() -> None:
        settings = config(**({} if limit == "input" else {"max_total_output_tokens": 100}))
        calls, budget = [], ExecutionBudget(settings)

        def handler(request):
            calls.append(request)
            return httpx.Response(503, json={})

        async with OpenRouterProviders(
            settings,
            token_counter=SyntheticCounter(10000 if limit == "input" else 100),
            transport=httpx.MockTransport(handler),
        ) as providers:
            with pytest.raises(ProviderError, match="^token_or_attempt_budget_exhausted$"):
                await complete(providers, budget)
        assert len(calls) == len(budget.receipts) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "usage,charge",
    [
        (None, (100, 64)),
        ({"prompt_tokens": 10}, (100, 64)),
        ({"prompt_tokens": 10, "completion_tokens": 8}, (10, 8)),
    ],
)
def test_missing_or_partial_usage_never_fabricates_spend(usage, charge) -> None:
    async def scenario() -> None:
        settings, budget = config(), ExecutionBudget(config())
        async with OpenRouterProviders(
            settings,
            token_counter=SyntheticCounter(),
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=chat_body(usage=usage))
            ),
        ) as providers:
            result = await complete(providers, budget)
        assert (budget.input_charged["chat"], budget.output_charged) == charge
        if usage is None:
            assert result.receipts[0].usage.input_tokens is None

    asyncio.run(scenario())


def test_usage_overrun_blocks_every_subsequent_operation() -> None:
    async def scenario() -> None:
        settings, calls = config(), []
        budget = ExecutionBudget(settings)

        def handler(request):
            calls.append(request)
            return httpx.Response(
                200, json=chat_body(usage={"prompt_tokens": 101, "completion_tokens": 8})
            )

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError, match="^reported_usage_exceeds_reservation$"):
                await complete(providers, budget)
            with pytest.raises(ProviderError, match="^execution_budget_exhausted$"):
                await complete(providers, budget)
        assert len(calls) == 1 and budget.blocked
        assert budget.receipts[0].outcome == "reported_usage_exceeds_reservation"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure,retry,code",
    [
        (httpx.ConnectError, True, "provider_connection_failed"),
        (httpx.ReadTimeout, False, "provider_timeout"),
        (httpx.WriteTimeout, False, "provider_timeout"),
        (httpx.ReadError, False, "provider_transport_error"),
    ],
)
def test_transport_failures_do_not_retry_ambiguous_dispatch(failure, retry, code) -> None:
    async def scenario() -> None:
        settings, calls = config(), []
        budget = ExecutionBudget(settings)

        def handler(request):
            calls.append(request)
            raise failure("sensitive upstream failure", request=request)

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError, match=f"^{code}$"):
                await complete(providers, budget)
        assert len(calls) == len(budget.receipts) == (2 if retry else 1)

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_and_cancellation_keep_reservation_and_close_response(cancel: bool) -> None:
    class SlowStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            started.set()
            await asyncio.Event().wait()
            yield b"unreachable"

        async def aclose(self):
            self.closed = True

    async def scenario() -> None:
        nonlocal started
        started = asyncio.Event()
        settings = config(provider_timeout_seconds=0.03)
        budget, calls, stream = ExecutionBudget(settings), [], SlowStream()

        def handler(request):
            calls.append(request)
            return httpx.Response(200, stream=stream, headers={"content-type": "application/json"})

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            task = asyncio.create_task(complete(providers, budget))
            await started.wait()
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(ProviderError, match="^provider_timeout$"):
                    await task
        assert len(calls) == 1 and stream.closed
        assert budget.input_charged["chat"] == 100 and budget.output_charged == 64
        assert budget.receipts[0].outcome == ("cancelled" if cancel else "provider_timeout")

    started = None
    asyncio.run(scenario())


@pytest.mark.parametrize(
    "body,code",
    [
        (chat_body(model="another/model"), "reported_model_mismatch"),
        (chat_body(model=None), "missing_reported_model"),
        (chat_body(usage={"prompt_tokens": True}), "invalid_provider_usage"),
        (chat_body(error={"message": "upstream sensitive"}), "provider_error_response"),
        (chat_body(choices=[]), "invalid_chat_response"),
        (
            chat_body(choices=[{"finish_reason": "length", "message": {"role": "assistant"}}]),
            "truncated_completion",
        ),
        (
            chat_body(
                choices=[{"finish_reason": "content_filter", "message": {"role": "assistant"}}]
            ),
            "provider_refusal",
        ),
        (
            chat_body(choices=[{"finish_reason": "tool_calls", "message": {"role": "assistant"}}]),
            "unexpected_completion_kind",
        ),
        (
            chat_body(
                choices=[{"finish_reason": "stop", "message": {"role": "assistant", "content": ""}}]
            ),
            "missing_structured_output",
        ),
        (
            chat_body(
                choices=[
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"answer":"x","count":"1"}'},
                    }
                ]
            ),
            "structured_output_invalid",
        ),
    ],
)
def test_invalid_success_response_is_not_repaired_or_retried(body, code) -> None:
    async def scenario() -> None:
        settings, calls = config(), []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=body)

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError, match=f"^{code}$"):
                await complete(providers, ExecutionBudget(settings))
        assert len(calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case,code",
    [
        ("declared", "provider_response_too_large"),
        ("streamed", "provider_response_too_large"),
        ("length", "invalid_provider_content_length"),
        ("json", "invalid_provider_json"),
        ("media", "invalid_provider_media_type"),
    ],
)
def test_response_bounds_and_invalid_wire(case: str, code: str) -> None:
    class ChunkStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"x" * 90
            yield b"x" * 90

        async def aclose(self):
            self.closed = True

    async def scenario() -> None:
        settings, stream = config(provider_max_response_bytes=128), ChunkStream()

        def handler(request):
            if case == "streamed":
                return httpx.Response(
                    200, stream=stream, headers={"content-type": "application/json"}
                )
            if case == "declared":
                return httpx.Response(200, content=b"{}", headers={"content-length": "999"})
            if case == "length":
                return httpx.Response(200, content=b"{}", headers={"content-length": "bad"})
            return httpx.Response(
                200,
                content=b"sensitive invalid JSON",
                headers={"content-type": "text/html" if case == "media" else "application/json"},
            )

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError, match=f"^{code}$"):
                await complete(providers, ExecutionBudget(settings))
        if case == "streamed":
            assert stream.closed

    asyncio.run(scenario())


def test_default_counter_and_unverified_embedding_format_prevent_dispatch() -> None:
    async def scenario() -> None:
        settings = config()

        def handler(request):
            pytest.fail("unverified adapter dispatched")

        async with OpenRouterProviders(
            settings, transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError, match="^embedding_format_unverified$"):
                await providers.embeddings.embed(
                    ["data"],
                    role="document",
                    format=EmbeddingFormat(version="unverified"),
                    budget=ExecutionBudget(settings),
                )
            with pytest.raises(ProviderError, match="^token_count_unavailable$"):
                await providers.embeddings.embed(
                    ["data"], role="document", format=FORMAT, budget=ExecutionBudget(settings)
                )

    asyncio.run(scenario())


def test_embedding_missing_model_is_honest_and_embedding_limit_is_separate() -> None:
    async def scenario() -> None:
        settings, budget = config(), ExecutionBudget(config())
        body = embedding_body()
        body.pop("model")
        async with OpenRouterProviders(
            settings,
            token_counter=SyntheticCounter(),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
        ) as providers:
            result = await providers.embeddings.embed(
                ["a", "b"], role="document", format=FORMAT, budget=budget
            )
            assert result.receipts[0].reported_model is None
            assert budget.input_charged == {"chat": 0, "embedding": 10}
            with pytest.raises(ProviderError, match="^operation_budget_exhausted$"):
                await providers.embeddings.embed(
                    ["a", "b"], role="document", format=FORMAT, budget=budget
                )

    asyncio.run(scenario())


def test_shared_budget_permits_two_chat_stages_and_no_third_dispatch(caplog) -> None:
    async def scenario() -> None:
        settings, calls = config(), []
        budget = ExecutionBudget(settings)

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=chat_body())

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            first = await complete(providers, budget)
            second = await complete(providers, budget)
            assert first.receipts[0].operation == 1 and second.receipts[0].operation == 2
            assert len(second.receipts) == 1
            with pytest.raises(ProviderError, match="^operation_budget_exhausted$"):
                await complete(providers, budget)
        assert len(calls) == 2 and budget.output_charged == 16
        assert "synthetic-model-key" not in caplog.text
        assert MESSAGES[0].content not in caplog.text
        assert "أهلاً" not in caplog.text

    asyncio.run(scenario())


def test_zero_retries_and_two_stage_output_reservations() -> None:
    async def scenario() -> None:
        settings = config(provider_max_retries=0, max_total_output_tokens=100)
        calls, budget = [], ExecutionBudget(settings)

        def handler(request):
            calls.append(request)
            return httpx.Response(503, json={})

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError, match="^provider_unavailable$"):
                await complete(providers, budget)
            with pytest.raises(ProviderError, match="^token_or_attempt_budget_exhausted$"):
                await complete(providers, budget)
        assert len(calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case,code",
    [
        ("duplicate", "embedding_index_mismatch"),
        ("dimensions", "embedding_dimension_mismatch"),
        ("model", "reported_model_mismatch"),
        ("batch", "embedding_batch_mismatch"),
    ],
)
def test_embedding_wire_failure_preserves_usage_and_does_not_retry(case: str, code: str) -> None:
    async def scenario() -> None:
        settings, calls = config(), []
        budget, body = ExecutionBudget(settings), embedding_body()
        if case == "duplicate":
            body["data"][0]["index"] = 0
        elif case == "dimensions":
            body["data"][0]["embedding"] = [1.0]
        elif case == "model":
            body["model"] = "another/model"
        else:
            body["data"].pop()

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=body)

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError, match=f"^{code}$"):
                await providers.embeddings.embed(
                    ["أحمد", "Doctor"], role="document", format=FORMAT, budget=budget
                )
        assert len(calls) == len(budget.receipts) == 1
        assert budget.receipts[0].usage.input_tokens == 10

    asyncio.run(scenario())


@pytest.mark.parametrize("texts", [[], ["  "], ["data"] * 33, [1]])
def test_invalid_embedding_inputs_are_rejected_before_dispatch(texts) -> None:
    async def scenario() -> None:
        settings = config()

        def handler(request):
            pytest.fail("invalid embedding input dispatched")

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError, match="^invalid_embedding_input$"):
                await providers.embeddings.embed(
                    texts, role="document", format=FORMAT, budget=ExecutionBudget(settings)
                )

    asyncio.run(scenario())


def test_expired_shared_deadline_rejects_decoded_success() -> None:
    async def scenario() -> None:
        now = [0.0]
        settings = config()
        budget = ExecutionBudget(settings, clock=lambda: now[0])

        def handler(request):
            now[0] = settings.request_timeout_seconds + 1
            return httpx.Response(200, json=chat_body())

        async with OpenRouterProviders(
            settings, token_counter=SyntheticCounter(), transport=httpx.MockTransport(handler)
        ) as providers:
            with pytest.raises(ProviderError, match="^execution_budget_exhausted$"):
                await complete(providers, budget)
        assert budget.receipts[0].outcome == "execution_budget_exhausted"
        assert budget.receipts[0].usage.output_tokens == 8

    asyncio.run(scenario())


def test_cleanup_is_bounded_and_does_not_infer() -> None:
    class StuckTransport(httpx.MockTransport):
        async def aclose(self):
            await asyncio.Event().wait()

    async def scenario() -> None:
        settings = config(shutdown_timeout_seconds=0.03)

        def handler(request):
            pytest.fail("cleanup dispatched inference")

        providers = OpenRouterProviders(settings, transport=StuckTransport(handler))
        with pytest.raises(ProviderError, match="^provider_cleanup_failed$"):
            await providers.aclose()

    asyncio.run(scenario())
