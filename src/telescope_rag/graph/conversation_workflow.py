"""Local conversational second stage, retaining the existing evidence validation path."""

import json
from typing import Literal

from langgraph.runtime import Runtime

from telescope_rag.graph.contracts import AnswerDraft, ConversationalDraft, PartDraft, QuoteDraft
from telescope_rag.graph.hours_projection import hours_decision
from telescope_rag.graph.hours_workflow import HoursRagWorkflow
from telescope_rag.graph.workflow import WorkflowError, _RunContext, _State
from telescope_rag.prompts.conversational_answer_v1 import ANSWER_SYSTEM, PROMPT_VERSION
from telescope_rag.providers.contracts import ChatMessage


class ConversationalRagWorkflow(HoursRagWorkflow):
    def _after_assembly(self, state: _State) -> Literal["draft", "safe"]:
        if super()._after_assembly(state) == "draft":
            return "draft"
        # Hours-only questions also use the existing second stage. The writer
        # cannot establish their outcome: it receives the validated computation.
        return (
            "draft"
            if any(
                p.state == "public" and op == "time_comparison"
                for p, op in zip(
                    state["plan"].assembly_request.parts, state["plan"].operations, strict=True
                )
            )
            else "safe"
        )

    async def _generate_draft(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        self._enter(runtime, "generate_draft")
        body = self._draft_body(state, runtime)
        body["prompt_version"] = PROMPT_VERSION
        hours = {op.part_id: op for op in runtime.context.computed_hours}
        decisions = {}
        for i, part in enumerate(body["parts"]):
            operation = hours.get(part["part_id"])
            if operation is not None:
                decision = hours_decision(
                    operation,
                    part=state["plan"].assembly_request.parts[i],
                    evidence=state["evidence"],
                    catalog=self._catalog,
                    max_age=self.hours_bindings.engine.max_source_age,
                    admitted_scope_complete=state["evidence"].parts[i].admitted_scope_complete,
                )
                decisions[part["part_id"]] = decision
                part["eligible_quote_chunk_ids"] = (
                    [c.chunk_id for c in operation.assessment.evidence]
                    if decision.draft_status == "candidate"
                    else []
                )
                part["validated_hours"] = {
                    "intent": operation.supplied.intent,
                    "subject": operation.assessment.subject.model_dump(mode="json")
                    if operation.assessment.subject is not None
                    else None,
                    "status": decision.status,
                    "reason": decision.reason,
                    "local_candidates": [
                        value.isoformat() for value in operation.assessment.local_candidates
                    ]
                    if operation.supplied.intent != "schedule"
                    else [],
                    "clock_ambiguous": operation.assessment.clock_ambiguous,
                    "dated_exception_applied": False
                    if operation.supplied.intent == "schedule"
                    else operation.assessment.dated_exception_applied,
                    "dated_exceptions_unverified": True
                    if operation.supplied.intent == "schedule"
                    else operation.assessment.dated_exceptions_unverified,
                    "schedules": [r.model_dump(mode="json") for r in operation.schedules]
                    if decision.proof_present
                    else [],
                }
                part["fixed_outcome"] = (
                    {"status": decision.draft_status, "reason_code": decision.reason_code}
                    if decision.draft_status != "candidate"
                    else None
                )
                continue
            safe = self._safe_part(state["plan"], state["evidence"], i)
            part["fixed_outcome"] = (
                {"status": safe.status, "reason_code": safe.reason_code}
                if not part["eligible_quote_chunk_ids"]
                else None
            )
        result = await self._chat.complete(
            (
                ChatMessage(role="system", content=ANSWER_SYSTEM),
                ChatMessage(role="user", content=json.dumps(body, ensure_ascii=False)),
            ),
            ConversationalDraft,
            max_output_tokens=max(
                1,
                min(
                    self._draft_output_tokens,
                    self._settings.max_total_output_tokens - runtime.context.budget.output_charged,
                ),
            ),
            budget=runtime.context.budget,
        )
        reply = self._typed(result, ConversationalDraft, "invalid_conversational_answer")
        expected = tuple(p.part_id for p in state["plan"].assembly_request.parts)
        if len(reply.parts) != len(expected) or {p.part_id for p in reply.parts} != set(expected):
            raise WorkflowError("invalid_conversational_coverage")
        proposed = {p.part_id: p for p in reply.parts}
        drafts = []
        for index, identity in enumerate(expected):
            entry = proposed[identity]
            allowed = self._allowed(state["plan"], state["evidence"], index)
            safe = self._safe_part(state["plan"], state["evidence"], index)
            decision = decisions.get(identity)
            if decision is not None:
                if (
                    entry.status != decision.draft_status
                    or entry.reason_code != decision.reason_code
                ):
                    raise WorkflowError("invalid_conversational_hours_outcome")
                allowed = set(body["parts"][index]["eligible_quote_chunk_ids"])
            if not allowed:
                if (
                    entry.sentences
                    or entry.status != (decision.draft_status if decision else safe.status)
                    or entry.reason_code != (decision.reason_code if decision else safe.reason_code)
                ):
                    raise WorkflowError("invalid_conversational_fixed_outcome")
                drafts.append(
                    PartDraft(
                        part_id=identity,
                        status=safe.status,
                        quotes=(),
                        reason_code=safe.reason_code,
                    )
                )
                continue
            if entry.status == "unknown":
                if entry.sentences or entry.reason_code != "not_found":
                    raise WorkflowError("invalid_conversational_unknown")
                drafts.append(
                    PartDraft(
                        part_id=identity, status="unknown", quotes=(), reason_code="not_found"
                    )
                )
                continue
            if entry.status != "candidate" or not entry.sentences or entry.reason_code is not None:
                raise WorkflowError("invalid_conversational_answer")
            selected = []
            for sentence in entry.sentences:
                if (
                    not sentence.text.strip()
                    or len(set(sentence.chunk_ids)) != len(sentence.chunk_ids)
                    or any(identity not in allowed for identity in sentence.chunk_ids)
                    or "[" in sentence.text
                    or "]" in sentence.text
                ):
                    raise WorkflowError("invalid_conversational_citation")
                selected.extend(i for i in sentence.chunk_ids if i not in selected)
            # Complete-source reads retain their full provenance coverage separately
            # from the sentence-specific support references; do not force irrelevant prose.
            if state["plan"].assembly_request.parts[index].scope.complete:
                selected = list(allowed)
            if decision is not None:
                # Hours remain the independently recomputed operation, not a quote
                # claim admitted by the ordinary source-draft validator.
                drafts.append(
                    PartDraft(
                        part_id=identity,
                        status=safe.status,
                        quotes=(),
                        reason_code=safe.reason_code,
                    )
                )
                continue
            drafts.append(
                PartDraft(
                    part_id=identity,
                    status="candidate",
                    reason_code=None,
                    quotes=tuple(
                        QuoteDraft(chunk_id=i, quote=self._catalog.chunks[i].retrieval_text)
                        for i in selected
                    ),
                )
            )
        runtime.context.conversation = reply
        # The original validator independently rechecks source scope, exact retained
        # quotations, ownership, coverage and per-question citation capabilities.
        return {"draft": AnswerDraft(parts=tuple(drafts))}
