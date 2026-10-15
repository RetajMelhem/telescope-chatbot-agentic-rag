"""Acyclic, dependency-injected offline LangGraph flow; never a public answer adapter."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, TypedDict
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langsmith.run_helpers import tracing_context
from pydantic import ValidationError

from telescope_rag.core.settings import Settings
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import (
    AnswerDraft,
    BudgetSummary,
    EvidenceRetriever,
    PartResult,
    PlannerReply,
    QuotedEvidence,
    RetrievalBatch,
    ValidatedPlan,
    WorkflowRequest,
    WorkflowResult,
    WorkflowRun,
)
from telescope_rag.prompts.offline_v1 import DRAFT_SYSTEM, PLANNER_SYSTEM, PROMPT_VERSION
from telescope_rag.providers.budget import ExecutionBudget
from telescope_rag.providers.contracts import ChatMessage, ChatProvider, StructuredResult, T
from telescope_rag.providers.errors import ProviderError
from telescope_rag.retrieval.assembly import AssembledEvidence, AssemblyCounter, EvidenceCatalog


class WorkflowError(ValueError):
    """Only application-authored event codes cross the offline boundary."""


@dataclass
class _RunContext:
    request_id: str
    budget: ExecutionBudget = field(repr=False)
    plan: ValidatedPlan | None = field(default=None, repr=False)
    evidence: AssembledEvidence | None = field(default=None, repr=False)
    stages: list[str] = field(default_factory=list)


class _State(TypedDict, total=False):
    request: WorkflowRequest
    proposal: PlannerReply
    plan: ValidatedPlan
    candidates: dict[str, tuple[str, ...]]
    evidence: AssembledEvidence
    draft: AnswerDraft
    result: WorkflowResult


class OfflineRagWorkflow:
    """Trusted server DI only. No key loading, default live service, streaming or persistence.

    Injected services retain their own capabilities; this wrapper does not prove
    arbitrary dependencies are offline. Tests use fakes. API wiring stays absent.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        chat: ChatProvider,
        retriever: EvidenceRetriever,
        catalog: EvidenceCatalog,
        counter: AssemblyCounter,
        token_basis: Literal["qwen_retrieval_only", "synthetic_test"] = "qwen_retrieval_only",
    ) -> None:
        if settings.app_env == "production" or token_basis not in {
            "qwen_retrieval_only",
            "synthetic_test",
        }:
            raise WorkflowError("offline_workflow_configuration_invalid")
        self._settings, self._chat, self._retriever = settings, chat, retriever
        self._catalog, self._counter, self._token_basis = catalog, counter, token_basis
        self._bindings = SourceBindings(catalog)
        self._snapshot = next(iter(catalog.chunks.values())).snapshot_id
        builder = StateGraph(_State, context_schema=_RunContext)
        for name, node in (
            ("validate_request", self._validate_request),
            ("plan_query", self._plan_query),
            ("validate_plan", self._validate_plan),
            ("retrieve_evidence", self._retrieve_evidence),
            ("assemble_evidence", self._assemble_evidence),
            ("generate_draft", self._generate_draft),
            ("validate_draft", self._validate_draft),
            ("finalize_safe", self._finalize_safe),
        ):
            builder.add_node(name, node)  # No node retry or cache policy.
        builder.add_edge(START, "validate_request")
        builder.add_edge("validate_request", "plan_query")
        builder.add_edge("plan_query", "validate_plan")
        builder.add_conditional_edges(
            "validate_plan",
            self._after_plan,
            {
                "retrieve": "retrieve_evidence",
                "safe": "finalize_safe",
            },
        )
        builder.add_edge("retrieve_evidence", "assemble_evidence")
        builder.add_conditional_edges(
            "assemble_evidence",
            self._after_assembly,
            {
                "draft": "generate_draft",
                "safe": "finalize_safe",
            },
        )
        builder.add_edge("generate_draft", "validate_draft")
        builder.add_edge("validate_draft", END)
        builder.add_edge("finalize_safe", END)
        self._graph = builder.compile(checkpointer=False)

    @staticmethod
    def _enter(runtime: Runtime[_RunContext], name: str) -> None:
        runtime.context.budget.remaining_seconds()
        if name in runtime.context.stages:
            raise WorkflowError("workflow_stage_repeated")
        runtime.context.stages.append(name)

    async def _validate_request(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        self._enter(runtime, "validate_request")
        request = state["request"]
        settings = self._settings
        if (
            len(request.query) > settings.max_query_chars
            or len(request.history) > settings.max_history_messages
            or sum(len(h.content) for h in request.history) > settings.max_history_chars
        ):
            raise WorkflowError("invalid_request")
        return {}

    @staticmethod
    def _typed(result: object, model: type[T], code: str) -> T:
        try:
            if not isinstance(result, StructuredResult) or type(result.data) is not model:
                raise ValueError
            return model.model_validate_json(result.data.model_dump_json(), strict=True)
        except (ValueError, TypeError, ValidationError):
            raise WorkflowError(code) from None

    async def _plan_query(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        self._enter(runtime, "plan_query")
        request = state["request"]
        body = {
            "prompt_version": PROMPT_VERSION,
            "original_query": request.query,
            "requested_language": request.language,
            "history": [h.model_dump() for h in request.history],
            "max_parts": self._settings.max_subquestions,
            "source_manifest": json.loads(self._bindings.manifest_json),
        }
        try:
            result = await self._chat.complete(
                (
                    ChatMessage(role="system", content=PLANNER_SYSTEM),
                    ChatMessage(role="user", content=json.dumps(body, ensure_ascii=False)),
                ),
                PlannerReply,
                max_output_tokens=min(1000, self._settings.max_total_output_tokens),
                budget=runtime.context.budget,
            )
        except ProviderError:
            raise
        except Exception:
            raise WorkflowError("planning_failed") from None
        return {"proposal": self._typed(result, PlannerReply, "invalid_plan")}

    async def _validate_plan(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        self._enter(runtime, "validate_plan")
        try:
            plan = self._bindings.validate(
                state["proposal"],
                state["request"],
                runtime.context.request_id,
                max_parts=self._settings.max_subquestions,
            )
        except (ValueError, TypeError, ValidationError):
            raise WorkflowError("invalid_plan") from None
        runtime.context.plan = plan
        return {"plan": plan}

    @staticmethod
    def _after_plan(state: _State) -> Literal["retrieve", "safe"]:
        return (
            "retrieve"
            if any(
                p.state == "public" and op != "time_comparison"
                for p, op in zip(
                    state["plan"].assembly_request.parts, state["plan"].operations, strict=True
                )
            )
            else "safe"
        )

    async def _retrieve_evidence(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        self._enter(runtime, "retrieve_evidence")
        plan = state["plan"]
        candidates = {p.part_id: () for p in plan.assembly_request.parts}
        if plan.retrieval_queries:
            try:
                received = await self._retriever.retrieve(
                    plan.retrieval_queries,
                    snapshot_id=self._snapshot,
                    prepared_digest=self._catalog.prepared_digest,
                    budget=runtime.context.budget,
                )
                if type(received) is not RetrievalBatch:
                    raise ValueError
                received = RetrievalBatch.model_validate_json(
                    received.model_dump_json(), strict=True
                )
                expected = {q.part_id for q in plan.retrieval_queries}
                if (
                    received.snapshot_id != self._snapshot
                    or received.prepared_digest != self._catalog.prepared_digest
                    or len(received.parts) != len(expected)
                    or {p.part_id for p in received.parts} != expected
                ):
                    raise ValueError
                for part in received.parts:
                    if (
                        len(part.chunk_ids) > min(self._settings.retrieval_top_k_per_question, 100)
                        or len(set(part.chunk_ids)) != len(part.chunk_ids)
                        or any(i not in self._catalog.chunks for i in part.chunk_ids)
                    ):
                        raise ValueError
                    candidates[part.part_id] = part.chunk_ids
            except ProviderError:
                raise
            except Exception:
                raise WorkflowError("retrieval_failed") from None
        # Complete-source membership is derived inside EvidenceCatalog. Nothing
        # requests an arbitrary URL or equates a top-K response with a full read.
        return {"candidates": candidates}

    async def _assemble_evidence(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        self._enter(runtime, "assemble_evidence")
        try:
            evidence = await asyncio.to_thread(
                self._catalog.assemble,
                state["plan"].assembly_request,
                state["candidates"],
                counter=self._counter,
                token_basis=self._token_basis,
                max_tokens=self._settings.max_evidence_tokens,
                max_groups=min(self._settings.max_evidence_chunks, 100),
            )
        except Exception:
            raise WorkflowError("assembly_failed") from None
        runtime.context.budget.remaining_seconds()
        runtime.context.evidence = evidence
        return {"evidence": evidence}

    def _allowed(
        self, plan: ValidatedPlan, evidence: AssembledEvidence, part_index: int
    ) -> dict[str, str]:
        part = plan.assembly_request.parts[part_index]
        receipt = evidence.parts[part_index]
        if (
            part.state != "public"
            or plan.operations[part_index] == "time_comparison"
            or receipt.admitted_scope_complete is False
        ):
            return {}
        allowed = {}
        for group in evidence.groups:
            if part.part_id in group.context_only_parts:
                continue
            ids = dict(group.part_occurrences).get(part.part_id, ())
            # Only this first occurrence is actually offered as the part's
            # citation in the counted rendering. Other exact occurrences remain
            # provenance, not additional model-visible citation capabilities.
            if ids:
                allowed[ids[0]] = group.group_id
        return allowed

    def _after_assembly(self, state: _State) -> Literal["draft", "safe"]:
        return (
            "draft"
            if any(
                self._allowed(state["plan"], state["evidence"], i)
                for i in range(len(state["plan"].assembly_request.parts))
            )
            else "safe"
        )

    async def _generate_draft(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        self._enter(runtime, "generate_draft")
        body = {
            "prompt_version": PROMPT_VERSION,
            "original_query": state["request"].query,
            "history": [h.model_dump() for h in state["request"].history],
            "language": state["plan"].language,
            "parts": [
                {
                    "part_id": part.part_id,
                    "operation": state["plan"].operations[i],
                    "eligible_quote_chunk_ids": list(
                        self._allowed(state["plan"], state["evidence"], i)
                    ),
                    "assembly_receipt": {
                        "candidate_status": state["evidence"].parts[i].candidate_status,
                        "admitted_scope_complete": state["evidence"]
                        .parts[i]
                        .admitted_scope_complete,
                        "missing_scope_occurrence_ids": state["evidence"]
                        .parts[i]
                        .missing_scope_occurrence_ids,
                    },
                }
                for i, part in enumerate(state["plan"].assembly_request.parts)
            ],
            "untrusted_candidate_rendering": state["evidence"].rendered_text,
            # The rendering has one complete body and a separately valid citation
            # per part/group. All other occurrences stay in the provenance sidecar;
            # duplicating their bodies here would crowd the model input again.
        }
        try:
            result = await self._chat.complete(
                (
                    ChatMessage(role="system", content=DRAFT_SYSTEM),
                    ChatMessage(role="user", content=json.dumps(body, ensure_ascii=False)),
                ),
                AnswerDraft,
                max_output_tokens=max(
                    1,
                    min(
                        1000,
                        self._settings.max_total_output_tokens
                        - runtime.context.budget.output_charged,
                    ),
                ),
                budget=runtime.context.budget,
            )
        except ProviderError:
            raise
        except Exception:
            raise WorkflowError("generation_failed") from None
        return {"draft": self._typed(result, AnswerDraft, "invalid_draft")}

    def _safe_part(
        self, plan: ValidatedPlan, evidence: AssembledEvidence | None, index: int
    ) -> PartResult:
        part = plan.assembly_request.parts[index]
        receipt = evidence.parts[index] if evidence is not None else None
        status, reason = "unknown", "not_found"
        if part.state == "excluded":
            status, reason = "excluded", "scope_excluded"
        elif part.state == "clarification_required":
            status, reason = "clarification_required", "ambiguous_request"
        elif plan.operations[index] == "time_comparison":
            reason = "operation_unavailable"
        elif receipt is not None:
            if receipt.admitted_scope_complete is False:
                reason = "scope_incomplete"
            elif receipt.context_only:
                reason = "context_only"
            elif receipt.omitted_group_ids and not receipt.group_ids:
                reason = "budget_limited"
        return PartResult(
            part_id=part.part_id,
            original_text=plan.assembly_request.original_query[part.start : part.end],
            status=status,
            quotes=(),
            reason_code=reason,
            admitted_scope_complete=receipt.admitted_scope_complete
            if receipt is not None
            else None,
        )

    @staticmethod
    def _result(
        context: _RunContext,
        language: Literal["en", "ar", "ar-JO"],
        parts: Sequence[PartResult],
        error: str | None = None,
    ) -> WorkflowResult:
        outcome = (
            "failed"
            if error is not None
            else "draft_ready"
            if any(p.status == "candidate" for p in parts)
            else "clarification_required"
            if any(p.status == "clarification_required" for p in parts)
            else "out_of_scope"
            if all(p.status == "excluded" for p in parts)
            else "not_found"
        )
        return WorkflowResult(
            request_id=context.request_id,
            outcome=outcome,
            language=language,
            parts=tuple(parts),
            error_code=error,
        )

    async def _finalize_safe(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        self._enter(runtime, "finalize_safe")
        plan, evidence = state["plan"], state.get("evidence")
        parts = [
            self._safe_part(plan, evidence, i) for i in range(len(plan.assembly_request.parts))
        ]
        return {"result": self._result(runtime.context, plan.language, parts)}

    async def _validate_draft(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        self._enter(runtime, "validate_draft")
        plan, evidence, draft = state["plan"], state["evidence"], state["draft"]
        if (
            len(draft.parts) != len(plan.assembly_request.parts)
            or len({p.part_id for p in draft.parts}) != len(draft.parts)
            or {p.part_id for p in draft.parts} != {p.part_id for p in plan.assembly_request.parts}
        ):
            raise WorkflowError("invalid_draft")
        by_id, outputs = {p.part_id: p for p in draft.parts}, []
        for index, part in enumerate(plan.assembly_request.parts):
            entry, safe = by_id[part.part_id], self._safe_part(plan, evidence, index)
            allowed = self._allowed(plan, evidence, index)
            if part.state != "public" or not allowed:
                if (
                    entry.status != safe.status
                    or entry.quotes
                    or entry.reason_code != safe.reason_code
                ):
                    raise WorkflowError("invalid_draft")
                outputs.append(safe)
                continue
            if entry.status == "unknown":
                if entry.quotes or entry.reason_code != "not_found":
                    raise WorkflowError("invalid_draft")
                outputs.append(safe.model_copy(update={"reason_code": "not_found"}))
                continue
            if entry.status != "candidate" or not entry.quotes or entry.reason_code is not None:
                raise WorkflowError("invalid_draft")
            if len({q.chunk_id for q in entry.quotes}) != len(entry.quotes):
                raise WorkflowError("invalid_citation")
            citations = []
            for quote in entry.quotes:
                if quote.chunk_id not in allowed:
                    raise WorkflowError("invalid_citation")
                source = self._catalog.chunks[quote.chunk_id]
                if quote.quote != source.retrieval_text:
                    raise WorkflowError("invalid_quotation")
                citations.append(
                    QuotedEvidence(
                        chunk_id=source.chunk_id,
                        source_url=source.canonical_url,
                        document_id=source.document_id,
                        snapshot_id=source.snapshot_id,
                        fetched_at=source.fetched_at,
                        literal_owner_id=source.doctor_id,
                        canonical_owner_id=source.canonical_doctor_id,
                        quote=quote.quote,
                    )
                )
            if part.scope.complete and {allowed[q.chunk_id] for q in entry.quotes} != set(
                allowed.values()
            ):
                raise WorkflowError("incomplete_source_draft")
            outputs.append(
                safe.model_copy(
                    update={"status": "candidate", "quotes": tuple(citations), "reason_code": None}
                )
            )
        return {"result": self._result(runtime.context, plan.language, outputs)}

    async def run(self, request: WorkflowRequest, *, request_id: UUID | None = None) -> WorkflowRun:
        try:
            if type(request) is not WorkflowRequest or (
                request_id is not None and type(request_id) is not UUID
            ):
                raise ValueError
            request = WorkflowRequest.model_validate_json(request.model_dump_json(), strict=True)
        except (ValueError, TypeError, ValidationError):
            raise WorkflowError("invalid_request") from None
        context = _RunContext((request_id or uuid4()).hex, ExecutionBudget(self._settings))
        try:
            # Disable ambient LangSmith tracing even if inherited environment
            # variables enable it. Never accept user RunnableConfig/callbacks.
            with tracing_context(enabled=False):
                async with asyncio.timeout(context.budget.remaining_seconds()):
                    state = await self._graph.ainvoke(
                        {"request": request},
                        context=context,
                        config={"recursion_limit": 12, "callbacks": []},
                    )
                    context.budget.remaining_seconds()
                    result = state["result"]
        except (WorkflowError, ProviderError, TimeoutError) as error:
            code = (
                str(error)
                if isinstance(error, WorkflowError)
                else "deadline_exceeded"
                if isinstance(error, TimeoutError)
                else "provider_failed"
            )
            result = self._failure(request, context, code)
        except Exception:
            result = self._failure(request, context, "workflow_failed")
        # CancelledError deliberately propagates; no retries, resumes or fallback calls.
        budget = context.budget
        return WorkflowRun(
            request,
            result,
            context.plan,
            context.evidence,
            tuple(context.stages),
            BudgetSummary(
                budget.operations["chat"],
                budget.operations["embedding"],
                budget.attempts["chat"],
                budget.attempts["embedding"],
                budget.input_charged["chat"],
                budget.input_charged["embedding"],
                budget.output_charged,
                budget.receipts,
            ),
        )

    def _failure(self, request: WorkflowRequest, context: _RunContext, code: str) -> WorkflowResult:
        language = (
            context.plan.language
            if context.plan is not None
            else (
                request.language if request.language != "auto" else self._settings.default_language
            )
        )
        if context.plan is not None:
            parts = [
                self._safe_part(context.plan, context.evidence, i)
                for i in range(len(context.plan.assembly_request.parts))
            ]
        else:
            parts = [
                PartResult(
                    part_id=f"{context.request_id}-p1",
                    original_text=request.query,
                    status="unknown",
                    quotes=(),
                    reason_code="draft_unavailable",
                    admitted_scope_complete=None,
                )
            ]
        return self._result(context, language, parts, code)
