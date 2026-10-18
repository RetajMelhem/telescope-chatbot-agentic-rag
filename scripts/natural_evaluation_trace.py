"""Opt-in, in-memory receipts for the existing local MVP HTTP evaluation.

Install after ``create_local_app``; call ``reset(case_id)`` before each sequential
ASGI request and ``snapshot()`` after its response. Construction never dispatches
requests. The adapter forwards every original call/result/exception unchanged.
It intentionally records public benchmark messages in caller-owned artifacts,
not application logs. It never records vectors, headers, settings or credentials.

Dense searches retain their individual limit/rank/scope. Their call order is not
a part binding: concurrent searches may finish in any order. RetrievalBatch IDs
are a distinct merged pool, and writer eligibility comes from the actual prompt,
not all assembled occurrences. No monetary estimate or billing request is made.
"""

import json
from collections.abc import Callable
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from functools import wraps
from math import isfinite
from time import perf_counter
from typing import Any
from uuid import UUID

import httpx2 as httpx
from pydantic import BaseModel


def _json(value: Any) -> Any:
    """Serialize only explicitly selected records, never arbitrary object attrs."""
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float:
        return value if isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return {entry.name: _json(getattr(value, entry.name)) for entry in fields(value)}
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    raise TypeError("unsupported_evaluation_record")


def _receipts(value: Any) -> list[dict]:
    names = (
        "operation",
        "kind",
        "attempt",
        "requested_model",
        "reported_model",
        "provider",
        "status_code",
        "outcome",
        "input_reserved",
        "output_reserved",
        "count_profile",
        "count_basis",
        "usage",
        "generation_id",
        "request_id",
        "started_at_utc",
        "finished_at_utc",
    )
    return [{name: _json(getattr(receipt, name, None)) for name in names} for receipt in value]


def _evidence(value: Any) -> dict | None:
    if value is None:
        return None
    return {
        "prepared_digest": value.prepared_digest,
        "parts": _json(value.parts),
        "groups": [
            {
                "group_id": group.group_id,
                "part_occurrences": _json(group.part_occurrences),
                "context_only_parts": _json(group.context_only_parts),
                "occurrences": [
                    {
                        "chunk_id": chunk.chunk_id,
                        "document_id": chunk.document_id,
                        "source_url": chunk.canonical_url,
                        "snapshot_id": chunk.snapshot_id,
                        "literal_owner_id": chunk.doctor_id,
                        "canonical_owner_id": chunk.canonical_doctor_id,
                    }
                    for chunk in group.occurrences
                ],
            }
            for group in value.groups
        ],
        "rendered_text": value.rendered_text,
        "token_count": value.token_count,
        "token_profile": value.token_profile,
        "token_basis": value.token_basis,
    }


def _run(value: Any) -> dict:
    usage = value.usage
    return {
        "request": _json(value.request),
        "result": _json(value.result),
        "plan": _json(value.plan),
        "evidence": _evidence(value.evidence),
        "stages": _json(value.stages),
        "usage": {
            name: _json(getattr(usage, name))
            for name in (
                "logical_chat_calls",
                "logical_embedding_calls",
                "physical_chat_attempts",
                "physical_embedding_attempts",
                "charged_chat_input",
                "charged_embedding_input",
                "charged_output",
            )
        }
        | {"receipts": _receipts(usage.receipts)},
        "request_anchors": _json(value.request_anchors),
        "answer_targets": _json(value.answer_targets),
        "computed_hours": _json(value.computed_hours),
        "operation_clock": _json(value.operation_clock),
        "conversation": _json(value.conversation),
    }


class Capture:
    """One sequential benchmark case, with task-local workflow correlation."""

    def __init__(self) -> None:
        self._active = 0
        self._context: ContextVar[int | None] = ContextVar("natural_evaluation_run", default=None)
        self._data: dict = {}
        self.reset("unassigned")

    def reset(self, case_id: str) -> None:
        if self._active:
            raise RuntimeError("evaluation_trace_reset_during_active_request")
        if type(case_id) is not str or not case_id.strip() or len(case_id) > 128:
            raise ValueError("evaluation_trace_case_id_invalid")
        self._data = {
            "schema_version": "natural-evaluation-trace-v1",
            "case_id": case_id,
            "workflow_runs": [],
            "retrieval_calls": [],
            "dense_calls": [],
            "chat_calls": [],
            "embedding_calls": [],
            "cache_reads": [],
            "writer_contexts": [],
            "cost_events": [],
            "concurrent_run_detected": False,
            "capture_errors": [],
            "cost": None,
            "cost_status": "unavailable",
        }

    def snapshot(self) -> dict:
        """Return a detached JSON-compatible receipt; never a live dependency."""
        result = deepcopy(self._data)
        result["active_workflows"] = self._active
        events = result["cost_events"]
        if events:
            known = [event["reported_usd"] for event in events if event["reported_usd"] is not None]
            complete = all(event.get("complete") for event in events)
            result["cost"] = {
                "reported_usd": sum(known) if complete else None,
                "known_reported_usd": sum(known) if known else None,
                "complete": complete,
                "basis": "provider_response_usage_cost",
            }
            result["cost_status"] = "provider_reported_complete" if complete else "partial"
        return result

    def _observe(self, hook: str, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as error:
            # Never export upstream exception messages, reprs or object attrs.
            self._data["capture_errors"].append({"hook": hook, "error_type": type(error).__name__})

    def _start(self, key: str) -> dict:
        row = {
            "run_index": self._context.get(),
            "call_index": len(self._data[key]),
        }
        self._data[key].append(row)
        return row

    def _wrap_async(
        self,
        owner: Any,
        method: str,
        key: str,
        before: Callable[[dict, tuple, dict], None],
        after: Callable[[dict, Any], None],
    ) -> None:
        original = getattr(owner, method)

        @wraps(original)
        async def traced(*args, **kwargs):
            # Calls outside a workflow are forwarded without capturing startup or
            # unrelated dependency operations under a benchmark case.
            if self._context.get() is None:
                return await original(*args, **kwargs)
            row = self._start(key)
            self._observe(key, lambda: before(row, args, kwargs))
            started = perf_counter()
            try:
                result = await original(*args, **kwargs)
            except BaseException as error:
                row["outcome"] = "raised"
                row["error_type"] = type(error).__name__
                raise
            else:
                row["outcome"] = "returned"
                self._observe(key, lambda: after(row, result))
                return result
            finally:
                row["elapsed_seconds"] = perf_counter() - started

        setattr(owner, method, traced)

    def _install(self, workflow: Any) -> None:
        original = workflow.run

        @wraps(original)
        async def run(*args, **kwargs):
            row = self._start("workflow_runs")
            row["run_index"] = row["call_index"]
            row["request_id"] = _json(kwargs.get("request_id"))
            if self._active:
                self._data["concurrent_run_detected"] = True
            self._active += 1
            token = self._context.set(row["run_index"])
            started = perf_counter()
            try:
                result = await original(*args, **kwargs)
            except BaseException as error:
                row["outcome"] = "raised"
                row["error_type"] = type(error).__name__
                raise
            else:
                row["outcome"] = "returned"
                self._observe("workflow_runs", lambda: row.update(_run(result)))
                return result
            finally:
                row["elapsed_seconds"] = perf_counter() - started
                self._context.reset(token)
                self._active -= 1

        workflow.run = run
        retriever = workflow._retriever

        def retrieval_before(row, args, kwargs):
            row.update(
                queries=_json(args[0] if args else kwargs["queries"]),
                snapshot_id=kwargs["snapshot_id"],
                prepared_digest=kwargs["prepared_digest"],
                pool_kind="dense_literal_and_section_candidates",
            )

        self._wrap_async(
            retriever,
            "retrieve",
            "retrieval_calls",
            retrieval_before,
            lambda row, result: row.update(batch=_json(result)),
        )

        def dense_before(row, args, kwargs):
            row.update(
                requested_limit=kwargs.get("limit", 20),
                scoped_point_ids=_json(kwargs.get("point_ids")),
                part_binding="unavailable",
            )

        def dense_after(row, result):
            row["hits"] = [
                {
                    "rank": rank,
                    "chunk_id": hit.chunk.chunk_id,
                    "point_id": hit.chunk.point_id,
                    "score": _json(hit.score),
                }
                for rank, hit in enumerate(result, 1)
            ]

        self._wrap_async(retriever._reader, "search", "dense_calls", dense_before, dense_after)

        def chat_before(row, args, kwargs):
            messages = args[0] if args else kwargs["messages"]
            schema = args[1] if len(args) > 1 else kwargs["output_model"]
            row.update(
                schema_name=schema.__name__,
                output_schema=schema.model_json_schema(),
                max_output_tokens=kwargs["max_output_tokens"],
                messages=[{"role": m.role, "content": m.content} for m in messages],
            )
            # Only a writer body offers citation capabilities. A planner's source
            # manifest is not answer evidence and must never be scored as recall.
            for message in messages:
                if message.role != "user":
                    continue
                try:
                    body = json.loads(message.content)
                except (ValueError, TypeError):
                    continue
                if isinstance(body, dict) and "untrusted_candidate_rendering" in body:
                    self._data["writer_contexts"].append(
                        {
                            "run_index": row["run_index"],
                            "chat_call_index": row["call_index"],
                            "body": body,
                        }
                    )

        def chat_after(row, result):
            row.update(result=_json(result.data), receipts=_receipts(result.receipts))

        self._wrap_async(workflow._chat, "complete", "chat_calls", chat_before, chat_after)

        def embedding_before(row, args, kwargs):
            profile = kwargs["format"]
            row.update(
                texts=_json(args[0] if args else kwargs["texts"]),
                role=kwargs["role"],
                format_version=profile.version,
            )

        def embedding_after(row, result):
            row.update(
                requested_model=result.requested_model,
                dimensions=result.dimensions,
                format_version=result.format_version,
                vector_count=len(result.vectors),
                receipts=_receipts(result.receipts),
            )

        self._wrap_async(
            retriever._embeddings, "embed", "embedding_calls", embedding_before, embedding_after
        )
        cache = retriever._cache
        if cache is not None:
            get = cache.get

            @wraps(get)
            def cache_get(*args, **kwargs):
                result = get(*args, **kwargs)
                if self._context.get() is not None:

                    def record():
                        row = self._start("cache_reads")
                        row.update(
                            cache_key=args[0] if args else kwargs["key"],
                            hit=result is not None,
                        )

                    self._observe("cache_reads", record)
                return result

            cache.get = cache_get


def install_capture(app: Any) -> Capture:
    """Instrument only this caller-owned app, leaving production source untouched."""
    existing = getattr(app.state, "_natural_evaluation_capture", None)
    if existing is not None:
        if not isinstance(existing, Capture):
            raise ValueError("evaluation_trace_installation_conflict")
        return existing
    workflow = app.state.offline_chat_service._workflow
    capture = Capture()
    capture._install(workflow)
    app.state._natural_evaluation_capture = capture
    return capture


class _CostStream(httpx.AsyncByteStream):
    """Bounded tee: forward identical chunks; export only a numeric usage.cost."""

    def __init__(self, stream, row, capture):
        self._stream, self._row, self._capture = stream, row, capture

    async def __aiter__(self):
        body = bytearray()
        oversized = False
        try:
            async for chunk in self._stream:
                if len(body) + len(chunk) > RecordedCostTransport.MAX_CAPTURE_BYTES:
                    oversized = True
                    body.clear()
                if not oversized:
                    body.extend(chunk)
                yield chunk
        except BaseException as error:
            self._row["error_type"] = type(error).__name__
            raise
        else:
            self._row["stream_finished"] = True
            if oversized:
                self._row["cost_status"] = "response_exceeds_capture_limit"
            else:
                self._capture._observe("cost_events", lambda: self._read_cost(body))

    def _read_cost(self, body):
        try:
            value = json.loads(body)
        except (ValueError, TypeError):
            self._row["cost_status"] = "invalid_json"
            return
        usage = value.get("usage") if isinstance(value, dict) else None
        cost = usage.get("cost") if isinstance(usage, dict) else None
        if type(cost) not in {int, float} or not isfinite(cost) or cost < 0:
            self._row["cost_status"] = "cost_unavailable"
            return
        self._row.update(reported_usd=cost, complete=True, cost_status="provider_reported")
        generation_id = value.get("id")
        if (
            isinstance(generation_id, str)
            and generation_id.startswith("gen-")
            and 4 < len(generation_id) <= 128
            and all(char.isascii() and (char.isalnum() or char == "-") for char in generation_id)
        ):
            self._row["generation_id"] = generation_id

    async def aclose(self):
        await self._stream.aclose()


class RecordedCostTransport(httpx.AsyncBaseTransport):
    """Optional provider transport; bind ``capture`` before making an ASGI query.

    Pass this to ``create_local_app(provider_transport=transport)``, then assign
    ``transport.capture = install_capture(app)``. The same response stream is
    forwarded once. No usage or billing endpoint is called. Missing/invalid costs
    remain unknown, including partially read, cancelled and failed requests.
    """

    MAX_CAPTURE_BYTES = 2_000_000

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None):
        self._inner = inner if inner is not None else httpx.AsyncHTTPTransport(retries=0)
        self.capture: Capture | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        capture = self.capture
        if capture is None or capture._context.get() is None:
            return await self._inner.handle_async_request(request)
        row = capture._start("cost_events")
        # Neither URL, request body nor authorization headers are copied.
        row.update(reported_usd=None, complete=False, stream_finished=False)
        try:
            response = await self._inner.handle_async_request(request)
        except BaseException as error:
            row["error_type"] = type(error).__name__
            raise
        row["status_code"] = response.status_code
        response.stream = _CostStream(response.stream, row, capture)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()
