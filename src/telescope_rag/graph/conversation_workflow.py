"""Local conversational second stage, retaining the existing evidence validation path."""

import json

from langgraph.runtime import Runtime

from telescope_rag.graph.contracts import AnswerDraft, ConversationalDraft, PartDraft, QuoteDraft
from telescope_rag.graph.hours_workflow import HoursRagWorkflow
from telescope_rag.graph.workflow import WorkflowError, _RunContext, _State
from telescope_rag.prompts.conversational_answer_v1 import ANSWER_SYSTEM, PROMPT_VERSION
from telescope_rag.providers.contracts import ChatMessage


class ConversationalRagWorkflow(HoursRagWorkflow):
    async def _generate_draft(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        self._enter(runtime, "generate_draft")
        body = self._draft_body(state, runtime)
        body["prompt_version"] = PROMPT_VERSION
        for i, part in enumerate(body["parts"]):
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
            if not allowed:
                if (
                    entry.sentences
                    or entry.status != safe.status
                    or entry.reason_code != safe.reason_code
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
