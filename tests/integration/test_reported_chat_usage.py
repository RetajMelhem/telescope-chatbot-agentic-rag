"""Normal Luna calls need no local counter; all HTTP and usage here are synthetic."""

import asyncio
import json
from dataclasses import asdict

import httpx2 as httpx
import pytest
from pydantic import BaseModel, ConfigDict

from telescope_rag.core.settings import Settings
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import (
    ChatMessage,
    EmbeddingFormat,
    TokenCount,
    UsageReport,
)
from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.openrouter import OpenRouterProviders


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str


def settings(**values):
    return Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only", **values)


def response(answer="Synthetic answer", usage=None, **changes):
    return {
        "model": "openai/gpt-6-luna",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"answer": answer}, ensure_ascii=False),
                },
            }
        ],
        "usage": usage,
    } | changes


async def call(providers, budget, text="Synthetic question", output=64):
    return await providers.chat.complete(
        (ChatMessage(role="user", content=text),),
        Result,
        max_output_tokens=output,
        budget=budget,
    )


@pytest.mark.parametrize("text", ["Synthetic English question", "سؤال تجريبي", "بدي جواب تجريبي"])
def test_normal_chat_dispatches_without_local_counter_and_preserves_full_input(text):
    async def scenario():
        config = settings()
        assert config.chat_input_accounting == "reported_usage"
        budget = ExecutionBudget(config)
        seen = []

        def handler(request):
            payload = json.loads(request.read())
            seen.append(payload)
            assert payload["messages"][0]["content"] == text
            assert payload["response_format"]["json_schema"]["strict"]
            assert payload["provider"] == {"require_parameters": True, "allow_fallbacks": False}
            assert budget.input_charged["chat"] is None
            return httpx.Response(
                200,
                json=response(
                    text, {"prompt_tokens": 21, "completion_tokens": 8, "total_tokens": 29}
                ),
            )

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            result = await call(providers, budget, text)
        assert result.data.answer == text and len(seen) == 1
        assert budget.input_charged["chat"] == 21 and budget.output_charged == 8
        receipt = result.receipts[0]
        assert receipt.input_reserved is None and receipt.output_reserved == 64
        assert receipt.count_basis == "reported_usage_only"
        assert receipt.count_profile == "luna-reported-usage-v1"
        data = asdict(receipt)
        data["usage"] = receipt.usage.model_dump(mode="json")
        encoded = json.dumps(data)
        assert "synthetic-only" not in encoded and text not in encoded

    asyncio.run(scenario())


def test_chat_never_uses_an_embedding_or_unknown_counter_as_a_luna_estimate():
    class ForbiddenCounter:
        def count(self, *args):
            raise AssertionError("A counter must not run for normal chat")

    async def scenario():
        config = settings()
        async with OpenRouterProviders(
            config,
            token_counter=ForbiddenCounter(),
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response())),
        ) as p:
            result = await call(p, ExecutionBudget(config))
        assert result.receipts[0].input_reserved is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "usage,input_total,output_total",
    [
        (None, None, 128),
        ({"completion_tokens": 5}, None, 10),
        ({"prompt_tokens": 9}, 18, 128),
        ({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, 0, 0),
    ],
)
def test_missing_partial_or_zero_usage_is_honest_and_does_not_prevent_second_stage(
    usage, input_total, output_total
):
    async def scenario():
        config = settings()
        budget = ExecutionBudget(config)
        async with OpenRouterProviders(
            config,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json=response(usage=usage))
            ),
        ) as p:
            for _ in range(2):
                result = await call(p, budget)
                assert result.data.answer == "Synthetic answer"
        assert budget.input_charged["chat"] == input_total
        assert budget.output_charged == output_total
        assert budget.operations["chat"] == budget.attempts["chat"] == 2
        assert not budget.blocked

    asyncio.run(scenario())


def test_input_usage_above_old_local_ceiling_is_recorded_without_blocking_model_results():
    async def scenario():
        config = settings()
        budget = ExecutionBudget(config)
        async with OpenRouterProviders(
            config,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, json=response(usage={"prompt_tokens": 20000, "completion_tokens": 8})
                )
            ),
        ) as p:
            await call(p, budget)
            await call(p, budget)
        assert budget.input_charged["chat"] == 40000 and not budget.blocked
        assert all(r.input_reserved is None for r in budget.receipts)

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [401, 402, 429, 502, 503, 504])
def test_reported_chat_failures_are_not_automatically_retried(status):
    async def scenario():
        config = settings(provider_max_retries=1)
        budget = ExecutionBudget(config)
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(status, json={"error": "synthetic"})

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            with pytest.raises(ProviderError):
                await call(p, budget)
        assert len(seen) == budget.attempts["chat"] == len(budget.receipts) == 1
        assert budget.input_charged["chat"] is None
        assert budget.output_charged == 64

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status",
    ["invalid_json", "wrong_model", "refusal", "truncation", "extra_fields", "malformed_usage"],
)
def test_bypassing_input_count_does_not_bypass_schema_model_or_protocol_validation(status):
    async def scenario():
        config = settings()
        budget = ExecutionBudget(config)
        payload = response(usage={"prompt_tokens": 12, "completion_tokens": 8})
        if status == "invalid_json":
            payload["choices"][0]["message"]["content"] = "not JSON"
        elif status == "wrong_model":
            payload["model"] = "unapproved/model"
        elif status == "refusal":
            payload["choices"][0]["message"]["refusal"] = "Synthetic refusal"
        elif status == "truncation":
            payload["choices"][0]["finish_reason"] = "length"
        elif status == "extra_fields":
            payload["choices"][0]["message"]["content"] = '{"answer":"ok","extra":1}'
        elif status == "malformed_usage":
            payload["usage"] = {"prompt_tokens": -1}
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json=payload)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            with pytest.raises(ProviderError):
                await call(p, budget)
        assert len(seen) == len(budget.receipts) == 1

    asyncio.run(scenario())


def test_embeddings_still_require_a_verified_counter_in_normal_chat_mode():
    async def scenario():
        config = settings()
        seen = []

        def forbidden(request):
            seen.append(request)
            raise AssertionError("Embedding should not dispatch")

        async with OpenRouterProviders(config, transport=httpx.MockTransport(forbidden)) as p:
            with pytest.raises(ProviderError, match="^token_count_unavailable$"):
                await p.embeddings.embed(
                    ["Synthetic embedding"],
                    role="document",
                    format=EmbeddingFormat(version="synthetic", verified=True),
                    budget=ExecutionBudget(config),
                )
        assert not seen

    asyncio.run(scenario())


def test_remaining_call_output_deadline_and_transport_size_bounds_still_apply():
    async def scenario():
        config = settings()
        budget = ExecutionBudget(config)
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json=response())

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            await call(p, budget, output=1000)
            await call(p, budget, output=1000)
            with pytest.raises(ProviderError, match="operation_budget_exhausted"):
                await call(p, budget)
        assert len(seen) == 2 and budget.output_charged == 2000
        for config, code in (
            (settings(provider_max_request_bytes=16), "provider_request_too_large"),
            (settings(max_total_output_tokens=16), "token_or_attempt_budget_exhausted"),
        ):
            async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
                with pytest.raises(ProviderError, match=code):
                    await call(p, ExecutionBudget(config))
        assert len(seen) == 2

    asyncio.run(scenario())


def test_concurrent_reported_reservations_and_unknown_usage_do_not_invent_totals():
    budget = ExecutionBudget(settings())
    first, second = budget.reserve_reported_chat(64), budget.reserve_reported_chat(64)
    budget.settle(second, UsageReport(input_tokens=20, output_tokens=10))
    assert budget.input_charged["chat"] is None
    budget.settle(first, UsageReport(input_tokens=10, output_tokens=5))
    assert budget.input_charged["chat"] == 30 and budget.output_charged == 15
    budget.settle(first, UsageReport(input_tokens=999, output_tokens=5))
    assert budget.input_charged["chat"] == 30


def test_accounting_modes_cannot_be_mixed_within_one_chat_budget():
    count = TokenCount(units=10, model="synthetic", profile="synthetic", basis="exact")
    budget = ExecutionBudget(settings())
    budget.reserve("chat", count, 64)
    with pytest.raises(ProviderError, match="mixed_chat_accounting_modes"):
        budget.reserve_reported_chat(64)
    budget = ExecutionBudget(settings())
    budget.reserve_reported_chat(64)
    with pytest.raises(ProviderError, match="mixed_chat_accounting_modes"):
        budget.reserve("chat", count, 64)


def test_explicit_strict_mode_keeps_original_no_count_no_dispatch_contract():
    budget = ExecutionBudget(settings(chat_input_accounting="strict"))
    with pytest.raises(ProviderError, match="reported_chat_accounting_not_enabled"):
        budget.reserve_reported_chat(64)


def test_reported_output_above_requested_limit_still_blocks_further_operations():
    budget = ExecutionBudget(settings())
    reservation = budget.reserve_reported_chat(64)
    with pytest.raises(ProviderError, match="reported_usage_exceeds_reservation"):
        budget.settle(reservation, UsageReport(input_tokens=11, output_tokens=65))
    assert budget.blocked and budget.input_charged["chat"] == 11


@pytest.mark.parametrize(
    "language,query,text",
    [
        ("en", "What does the synthetic source say?", "Synthetic improvement may be gradual."),
        ("ar", "ماذا يقول المصدر التجريبي؟", "قد تتحسن النتيجة تدريجياً بعد التقييم."),
        ("ar-JO", "شو بحكي المصدر التجريبي؟", "ممكن تتحسن النتيجة شوي شوي حسب التقييم."),
    ],
)
@pytest.mark.parametrize("missing_usage", [False, True])
def test_actual_graph_and_adapter_complete_both_stages_without_a_local_counter(
    language, query, text, missing_usage
):
    from test_offline_workflow import FakeRetriever, SyntheticCounter, catalog, single_plan, source

    from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft, WorkflowRequest
    from telescope_rag.graph.workflow import OfflineRagWorkflow

    async def scenario():
        config = settings()
        item = source(1, text).model_copy(update={"language": "en" if language == "en" else "ar"})
        evidence = catalog(item)
        retriever = FakeRetriever(lambda i, q: (item.chunk_id,))
        requests = []

        def handler(request):
            wire = json.loads(request.read())
            body = json.loads(wire["messages"][-1]["content"])
            requests.append(wire)
            assert body["original_query"] == query
            if len(requests) == 1:
                value = single_plan(language)(body)
            else:
                assert item.retrieval_text in body["untrusted_candidate_rendering"]
                value = AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=body["parts"][0]["part_id"],
                            status="candidate",
                            quotes=(QuoteDraft(chunk_id=item.chunk_id, quote=item.retrieval_text),),
                            reason_code=None,
                        ),
                    )
                )
            data = response(
                usage=None
                if missing_usage
                else {"prompt_tokens": 20, "completion_tokens": 12, "total_tokens": 32}
            )
            data["choices"][0]["message"]["content"] = value.model_dump_json()
            return httpx.Response(200, json=data)

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            flow = OfflineRagWorkflow(
                settings=config,
                chat=p.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
            )
            run = await flow.run(WorkflowRequest(query=query))
        assert run.result.outcome == "draft_ready" and run.result.error_code is None
        assert (
            len(requests) == run.usage.logical_chat_calls == run.usage.physical_chat_attempts == 2
        )
        assert run.usage.charged_chat_input == (None if missing_usage else 40)
        assert run.usage.charged_embedding_input == 10
        assert run.result.parts[0].quotes[0].quote == text
        assert run.result.parts[0].quotes[0].source_url == item.canonical_url
        assert run.result.language == language and run.result.offline_only
        assert (
            not run.result.luna_compatibility_verified
            and not run.result.semantic_grounding_verified
        )
        assert all(
            r.input_reserved is None and r.count_basis == "reported_usage_only"
            for r in run.usage.receipts
            if r.kind == "chat"
        )

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_reported_chat_cancellation_and_connect_error_leave_input_unknown_without_retry(cancel):
    async def scenario():
        config = settings()
        budget = ExecutionBudget(config)
        started = asyncio.Event()
        seen = []

        async def handler(request):
            seen.append(request)
            started.set()
            if cancel:
                await asyncio.Event().wait()
            raise httpx.ConnectError("Synthetic connection failure")

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as p:
            task = asyncio.create_task(call(p, budget))
            await started.wait()
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(ProviderError, match="provider_connection_failed"):
                    await task
        assert len(seen) == len(budget.receipts) == 1
        assert budget.input_charged["chat"] is None and budget.output_charged == 64

    asyncio.run(scenario())
