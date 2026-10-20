"""OpenRouter wire adapters with explicit retries and no startup/health inference."""

import asyncio
import json
import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar

import httpx2 as httpx

from telescope_rag.core.settings import Settings
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import (
    AttemptReceipt,
    ChatMessage,
    EmbeddingFormat,
    EmbeddingResult,
    OperationKind,
    StructuredResult,
    T,
    TokenCount,
    TokenCounter,
    UnavailableTokenCounter,
    UsageReport,
)
from telescope_rag.providers.errors import ProviderError
from telescope_rag.providers.validation import (
    load_json,
    output_schema,
    parse_chat,
    parse_usage,
    parse_vectors,
)

V = TypeVar("V")


class _Client:
    def __init__(
        self,
        settings: Settings,
        counter: TokenCounter | None,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        self.settings = settings
        self.counter = counter if counter is not None else UnavailableTokenCounter()
        self.http = httpx.AsyncClient(
            base_url=str(settings.openrouter_base_url).rstrip("/") + "/",
            transport=transport if transport is not None else httpx.AsyncHTTPTransport(retries=0),
            timeout=settings.provider_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )

    async def execute(
        self,
        path: str,
        kind: OperationKind,
        payload: dict[str, Any],
        output: int,
        budget: ExecutionBudget,
        decode: Callable[[dict[str, Any]], V],
        *,
        reported_model_alias: str | None = None,
    ) -> tuple[V, tuple[AttemptReceipt, ...]]:
        if reported_model_alias is not None and (
            kind != "embedding"
            or payload.get("model") != "qwen/qwen3-embedding-8b"
            or reported_model_alias != "Qwen/Qwen3-Embedding-8B"
            or payload.get("provider", {}).get("only") != ["deepinfra/us"]
        ):
            raise ProviderError("invalid_provider_request")
        if self.http.is_closed:
            raise ProviderError("provider_closed")
        key = self.settings.openrouter_api_key.get_secret_value()
        if not key:
            raise ProviderError("missing_provider_credentials")
        if not key.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in key):
            raise ProviderError("invalid_provider_credentials")
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise ProviderError("invalid_provider_request") from None
        if len(encoded) > self.settings.provider_max_request_bytes:
            raise ProviderError("provider_request_too_large")
        count = None
        if kind != "chat" or self.settings.chat_input_accounting == "strict":
            try:
                count = self.counter.count(kind, payload)
            except ProviderError:
                raise
            except Exception:
                raise ProviderError("token_count_unavailable") from None
            if not isinstance(count, TokenCount) or count.model != payload["model"]:
                raise ProviderError("incompatible_token_count")
        operation = budget.begin(kind)
        retries = self.settings.provider_max_retries if count is not None else 0
        for attempt in range(1, retries + 2):
            try:
                value = await self._attempt(
                    path,
                    kind,
                    payload["model"],
                    encoded,
                    key,
                    count,
                    output,
                    budget,
                    operation,
                    attempt,
                    decode,
                    reported_model_alias,
                )
                receipts = tuple(
                    item
                    for item in budget.receipts
                    if item.kind == kind and item.operation == operation
                )
                return value, receipts
            except ProviderError as error:
                if not error.retryable or attempt > retries:
                    raise
                delay = (
                    error.retry_after_seconds
                    if error.retry_after_seconds is not None
                    else self.settings.provider_retry_delay_seconds
                )
                if delay >= budget.remaining_seconds():
                    raise ProviderError("retry_deadline_exhausted") from None
                await asyncio.sleep(delay)
        raise ProviderError("provider_retry_exhausted")  # defensive; the loop always exits above

    async def _attempt(
        self,
        path: str,
        kind: OperationKind,
        model: str,
        encoded: bytes,
        key: str,
        count: TokenCount | None,
        output: int,
        budget: ExecutionBudget,
        operation: int,
        attempt: int,
        decode: Callable[[dict[str, Any]], V],
        reported_model_alias: str | None,
    ) -> V:
        reservation = (
            budget.reserve(kind, count, output)
            if count is not None
            else budget.reserve_reported_chat(output)
        )
        usage = UsageReport()
        status = None
        reported_model = provider = None
        generation_id = request_id = None
        started_at = datetime.now(UTC).isoformat()
        outcome = "provider_protocol_error"
        try:
            timeout = min(self.settings.provider_timeout_seconds, budget.remaining_seconds())
            async with asyncio.timeout(timeout):
                async with self.http.stream(
                    "POST",
                    path,
                    content=encoded,
                    timeout=timeout,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                ) as response:
                    status = response.status_code
                    raw = await self._read_bounded(response)
                    if status != 200:
                        raise self._http_error(response)
                    media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if media_type != "application/json" and not media_type.endswith("+json"):
                        raise ProviderError("invalid_provider_media_type")
                    body = load_json(raw)
                    generation_id = self._trace_id(body.get("id"), prefix="gen-")
                    request_id = self._trace_id(body.get("request_id"), prefix="req-")
                    if "error" in body:
                        raise ProviderError("provider_error_response")
                    usage = parse_usage(body.get("usage"), kind)
                    reported_model = self._metadata(body.get("model"))
                    provider = self._metadata(body.get("provider"))
                    if reported_model is None and kind == "chat":
                        raise ProviderError("missing_reported_model")
                    if reported_model is not None and reported_model not in {
                        model,
                        reported_model_alias,
                    }:
                        raise ProviderError("reported_model_mismatch")
                    value = decode(body)
                    budget.remaining_seconds()
            outcome = "success"
            return value
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except ProviderError as error:
            outcome = error.code
            raise
        except (TimeoutError, httpx.TimeoutException):
            outcome = "provider_timeout"
            raise ProviderError(outcome) from None
        except httpx.ConnectError:
            outcome = "provider_connection_failed"
            raise ProviderError(outcome, retryable=True) from None
        except httpx.HTTPError:
            outcome = "provider_transport_error"
            raise ProviderError(outcome) from None
        except Exception:
            outcome = "provider_protocol_error"
            raise ProviderError(outcome) from None
        finally:
            try:
                budget.settle(reservation, usage)
            except ProviderError as error:
                outcome = error.code
                raise
            finally:
                budget.record(
                    AttemptReceipt(
                        operation=operation,
                        kind=kind,
                        attempt=attempt,
                        requested_model=model,
                        reported_model=reported_model,
                        provider=provider,
                        status_code=status,
                        outcome=outcome,
                        input_reserved=count.units if count is not None else None,
                        output_reserved=output,
                        count_profile=count.profile
                        if count is not None
                        else "luna-reported-usage-v1",
                        count_basis=count.basis if count is not None else "reported_usage_only",
                        usage=usage,
                        generation_id=generation_id,
                        request_id=request_id,
                        started_at_utc=started_at,
                        finished_at_utc=datetime.now(UTC).isoformat(),
                    )
                )

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                size = int(declared)
            except ValueError:
                raise ProviderError("invalid_provider_content_length") from None
            if size < 0:
                raise ProviderError("invalid_provider_content_length")
            if size > self.settings.provider_max_response_bytes:
                raise ProviderError("provider_response_too_large")
        result = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=65536):
            if len(result) + len(chunk) > self.settings.provider_max_response_bytes:
                raise ProviderError("provider_response_too_large")
            result.extend(chunk)
        return bytes(result)

    @staticmethod
    def _trace_id(value: Any, *, prefix: str) -> str | None:
        # Optional correlation metadata must neither reject valid answers nor
        # copy arbitrary provider text into content-free receipts.
        if (
            not isinstance(value, str)
            or not value.startswith(prefix)
            or not len(prefix) < len(value) <= 128
            or any(
                c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
                for c in value
            )
        ):
            return None
        return value

    @staticmethod
    def _metadata(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value or len(value) > 128:
            raise ProviderError("invalid_provider_metadata")
        return value

    @staticmethod
    def _http_error(response: httpx.Response) -> ProviderError:
        status = response.status_code
        code = {
            400: "provider_request_rejected",
            401: "provider_authentication_failed",
            402: "provider_credit_unavailable",
            403: "provider_authentication_failed",
            404: "provider_model_unavailable",
            422: "provider_request_rejected",
            429: "provider_rate_limited",
            502: "provider_unavailable",
            503: "provider_unavailable",
            504: "provider_timeout",
        }.get(status, "provider_http_error")
        retryable = status in {429, 502, 503}
        delay = None
        retry_after = response.headers.get("retry-after")
        if retry_after is not None:
            try:
                delay = float(retry_after)
                if not math.isfinite(delay) or delay < 0:
                    raise ValueError("invalid_retry_delay")
            except ValueError:
                # Unrecognized/date-form timing is not guessed or shortened.
                retryable = False
                delay = None
        return ProviderError(
            code, status_code=status, retryable=retryable, retry_after_seconds=delay
        )


class OpenRouterChatProvider:
    def __init__(self, client: _Client) -> None:
        self._client = client

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        output_model: type[T],
        *,
        max_output_tokens: int,
        budget: ExecutionBudget,
    ) -> StructuredResult[T]:
        if (
            not messages
            or len(messages) > 32
            or any(not isinstance(m, ChatMessage) for m in messages)
        ):
            raise ProviderError("invalid_chat_input")
        if type(max_output_tokens) is not int or max_output_tokens < 16:
            raise ProviderError("invalid_output_limit")
        payload = {
            "model": self._client.settings.openrouter_chat_model,
            "messages": [message.model_dump() for message in messages],
            "response_format": {"type": "json_schema", "json_schema": output_schema(output_model)},
            "max_completion_tokens": max_output_tokens,
            "stream": False,
        }
        if self._client.settings.chat_provider_routing == "open":
            payload["provider"] = {"require_parameters": False, "allow_fallbacks": False}
        else:
            payload["provider"] = {"require_parameters": True, "allow_fallbacks": False}
        if self._client.settings.chat_reasoning_effort is not None:
            payload["reasoning"] = {"effort": self._client.settings.chat_reasoning_effort}
        data, receipts = await self._client.execute(
            "chat/completions",
            "chat",
            payload,
            max_output_tokens,
            budget,
            lambda body: parse_chat(body, output_model),
        )
        return StructuredResult(data, receipts)


class OpenRouterEmbeddingProvider:
    def __init__(self, client: _Client) -> None:
        self._client = client

    async def embed(
        self,
        texts: Sequence[str],
        *,
        role: Literal["query", "document"],
        format: EmbeddingFormat,
        budget: ExecutionBudget,
    ) -> EmbeddingResult:
        settings = self._client.settings
        if (
            role not in {"query", "document"}
            or not texts
            or len(texts) > settings.max_embedding_batch_size
            or any(not isinstance(text, str) or not text.strip() for text in texts)
        ):
            raise ProviderError("invalid_embedding_input")
        payload = {
            "model": settings.openrouter_embedding_model,
            "input": [format.format(text, role) for text in texts],
            "dimensions": settings.embedding_dimensions,
            "encoding_format": "float",
            "provider": {"require_parameters": True, "allow_fallbacks": False},
        }
        if format.provider_slug is not None:
            payload["provider"]["only"] = [format.provider_slug]
        vectors, receipts = await self._client.execute(
            "embeddings",
            "embedding",
            payload,
            0,
            budget,
            lambda body: parse_vectors(body, len(texts), settings.embedding_dimensions),
            reported_model_alias=format.reported_model,
        )
        return EmbeddingResult(
            vectors,
            settings.openrouter_embedding_model,
            settings.embedding_dimensions,
            format.version,
            receipts,
        )


class OpenRouterProviders:
    """Own the shared client; embeddings and strict chat require a counter."""

    def __init__(
        self,
        settings: Settings,
        *,
        token_counter: TokenCounter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = _Client(settings, token_counter, transport)
        self.chat = OpenRouterChatProvider(self._client)
        self.embeddings = OpenRouterEmbeddingProvider(self._client)

    async def __aenter__(self) -> "OpenRouterProviders":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        try:
            async with asyncio.timeout(self._client.settings.shutdown_timeout_seconds):
                await self._client.http.aclose()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ProviderError("provider_cleanup_failed") from None
