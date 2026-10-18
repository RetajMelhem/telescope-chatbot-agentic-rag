"""Opt-in bounded hours graph, reusing the existing request budget and source draft graph."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from langgraph.runtime import Runtime

from telescope_rag.core.settings import Settings
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.contracts import EvidenceRetriever
from telescope_rag.graph.hours_contract import (
    ContractHoursBindings,
    HoursProfile,
    contract_hours_manifest,
    hours_reply_model,
)
from telescope_rag.graph.hours_identity import IDENTITY_PROMPT_VERSION, identity_hours_manifest
from telescope_rag.graph.hours_inputs import HoursBindings
from telescope_rag.graph.planning import planner_messages
from telescope_rag.graph.source_choices import SourceChoicePlannerReply, bind_source_choices
from telescope_rag.graph.workflow import OfflineRagWorkflow, WorkflowError, _RunContext, _State
from telescope_rag.knowledge.hours import PublicHoursPlan
from telescope_rag.knowledge.source_authority import DirectoryAuthority
from telescope_rag.knowledge.time_calculations import PublicHoursCatalog
from telescope_rag.prompts.planner_hours_contract_v14 import PLANNER_SYSTEM as CONTRACT_SYSTEM
from telescope_rag.prompts.planner_hours_contract_v14 import PROMPT_VERSION as CONTRACT_VERSION
from telescope_rag.prompts.planner_hours_v12 import PLANNER_SYSTEM, PROMPT_VERSION
from telescope_rag.prompts.planner_local_mvp_v1 import PLANNER_SYSTEM as LOCAL_SYSTEM
from telescope_rag.prompts.planner_local_mvp_v1 import PROMPT_VERSION as LOCAL_VERSION
from telescope_rag.prompts.planner_source_choice_v1 import PLANNER_SYSTEM as SOURCE_CHOICE_SYSTEM
from telescope_rag.prompts.planner_source_choice_v1 import PROMPT_VERSION as SOURCE_CHOICE_VERSION
from telescope_rag.providers.contracts import ChatMessage, ChatProvider
from telescope_rag.retrieval.assembly import AssemblyCounter, EvidenceCatalog


class HoursRagWorkflow(OfflineRagWorkflow):
    def __init__(
        self,
        *,
        hours_plan: PublicHoursPlan,
        expected_hours_plan_digest: str,
        settings: Settings,
        chat: ChatProvider,
        retriever: EvidenceRetriever,
        catalog: EvidenceCatalog,
        counter: AssemblyCounter,
        directory_authority: DirectoryAuthority,
        token_basis: Literal["qwen_retrieval_only", "synthetic_test"] = "qwen_retrieval_only",
        planner_output_tokens: int = 1000,
        draft_output_tokens: int = 1000,
        clock: Callable[[], datetime] | None = None,
        hours_profile: HoursProfile = "v12",
        reviewed_profile_limitations: bool = False,
        source_page_clarifications: bool = False,
        local_mvp_search: bool = False,
        reuse_page_candidates: bool = False,
    ) -> None:
        if type(reviewed_profile_limitations) is not bool or (
            reviewed_profile_limitations and hours_profile != "contracts_v14"
        ):
            raise ValueError("profile_limitations_require_contracts_v14")
        if type(source_page_clarifications) is not bool or (
            source_page_clarifications and hours_profile != "contracts_v14"
        ):
            raise ValueError("source_choices_require_contracts_v14")
        self._source_page_clarifications = source_page_clarifications
        if reuse_page_candidates and not local_mvp_search:
            raise ValueError("page_reuse_requires_local_mvp")
        if type(local_mvp_search) is not bool or (
            local_mvp_search and not source_page_clarifications
        ):
            raise ValueError("local_search_requires_source_choices")
        self._hours_reply_model = (
            SourceChoicePlannerReply
            if source_page_clarifications
            else hours_reply_model(hours_profile)
        )
        # The old profiles and their payload builder are not changed/adopted.
        super().__init__(
            planner_profile="local_constraints",
            settings=settings,
            chat=chat,
            retriever=retriever,
            catalog=catalog,
            counter=counter,
            directory_authority=directory_authority,
            token_basis=token_basis,
            planner_output_tokens=planner_output_tokens,
            draft_output_tokens=draft_output_tokens,
            reuse_page_candidates=reuse_page_candidates,
        )
        self._planner_source_manifest_json = (
            self._bindings.with_reviewed_profile_limitations()
            if reviewed_profile_limitations
            else None
        )
        plan = PublicHoursPlan.model_validate_json(hours_plan.model_dump_json())
        engine = PublicHoursCatalog(
            plan=plan,
            catalog=self._catalog,
            expected_plan_digest=expected_hours_plan_digest,
            max_source_age=timedelta(hours=self._settings.knowledge_max_age_hours),
        )
        bindings_type = ContractHoursBindings if hours_profile == "contracts_v14" else HoursBindings
        self.hours_bindings = bindings_type(plan, self._catalog, self._bindings, engine)
        self._hours_manifest_json = (
            contract_hours_manifest(self.hours_bindings, self._bindings)
            if hours_profile == "contracts_v14"
            else identity_hours_manifest(self.hours_bindings, self._bindings)
            if hours_profile == "identity_links_v13"
            else self.hours_bindings.manifest_json
        )
        self._hours_prompt_version = (
            CONTRACT_VERSION
            if hours_profile == "contracts_v14"
            else IDENTITY_PROMPT_VERSION
            if hours_profile == "identity_links_v13"
            else PROMPT_VERSION
        )
        self._hours_system = CONTRACT_SYSTEM if hours_profile == "contracts_v14" else PLANNER_SYSTEM
        if source_page_clarifications:
            self._hours_prompt_version = SOURCE_CHOICE_VERSION
            self._hours_system = SOURCE_CHOICE_SYSTEM
        if local_mvp_search:
            self._hours_prompt_version = LOCAL_VERSION
            self._hours_system = LOCAL_SYSTEM
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _plan_query(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        self._enter(runtime, "plan_query")
        now = self._clock()
        if type(now) is not datetime or now.utcoffset() is None:
            raise WorkflowError("hours_server_clock_invalid")
        runtime.context.operation_clock = now.astimezone(UTC)
        old = planner_messages(
            state["request"],
            self._bindings,
            max_parts=self._settings.max_subquestions,
            profile="local_constraints",
        )
        body = json.loads(old[-1].content)
        if self._planner_source_manifest_json is not None:
            body["source_manifest"] = json.loads(self._planner_source_manifest_json)
        body.update(
            prompt_version=self._hours_prompt_version,
            hours_manifest=json.loads(self._hours_manifest_json),
            server_clock={
                "now_utc": runtime.context.operation_clock.isoformat(),
                "timezone": "Asia/Amman",
            },
        )
        result = await self._chat.complete(
            (
                ChatMessage(role="system", content=self._hours_system),
                ChatMessage(role="user", content=json.dumps(body, ensure_ascii=False)),
            ),
            self._hours_reply_model,
            max_output_tokens=min(
                self._planner_output_tokens, self._settings.max_total_output_tokens
            ),
            budget=runtime.context.budget,
        )
        return {"proposal": self._typed(result, self._hours_reply_model, "invalid_hours_plan")}

    async def _validate_plan(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        proposal = state["proposal"]
        if type(proposal) is not self._hours_reply_model:
            raise WorkflowError("invalid_hours_plan")
        # Project the old fields byte-for-byte into their existing validators;
        # keep the new typed input and its literal receipts separately.
        old = AnchoredPlannerReply.model_validate_json(
            json.dumps(
                {
                    "language": proposal.language,
                    "parts": [
                        p.model_dump(
                            mode="json",
                            exclude={"hours", "clarification"}
                            if self._source_page_clarifications
                            else {"hours"},
                        )
                        for p in proposal.parts
                    ],
                }
            )
        )
        result = await super()._validate_plan({**state, "proposal": old}, runtime)
        records = []
        try:
            for proposed, part, target in zip(
                proposal.parts,
                result["plan"].assembly_request.parts,
                runtime.context.answer_targets,
                strict=True,
            ):
                is_hours = proposed.state == "public" and proposed.operation == "time_comparison"
                if is_hours != (proposed.hours is not None):
                    raise ValueError
                if is_hours:
                    runtime.context.budget.remaining_seconds()
                    records.append(
                        self.hours_bindings.bind(
                            proposed.hours,
                            part=part,
                            request=state["request"],
                            reference_text=target.reference_text,
                            history_indices=target.history_indices,
                            now=runtime.context.operation_clock,
                        )
                    )
        except (ValueError, TypeError, IndexError):
            raise WorkflowError("invalid_hours_input") from None
        runtime.context.computed_hours = tuple(records)
        if self._source_page_clarifications:
            try:
                result["plan"] = bind_source_choices(proposal, result["plan"], self._bindings)
            except (ValueError, TypeError, KeyError):
                raise WorkflowError("invalid_source_page_choices") from None
            runtime.context.plan = result["plan"]
        runtime.context.budget.remaining_seconds()
        return result

    @staticmethod
    def _after_plan(state: _State) -> str:
        return (
            "retrieve"
            if any(p.state == "public" for p in state["plan"].assembly_request.parts)
            else "safe"
        )

    async def _retrieve_evidence(self, state: _State, runtime: Runtime[_RunContext]) -> _State:
        result = await super()._retrieve_evidence(state, runtime)
        for operation in runtime.context.computed_hours:
            result["candidates"][operation.part_id] = tuple(
                c.chunk_id for c in operation.assessment.evidence
            )
        return result
