"""Explicit caller-owned nonproduction hours composition, with no default plan or provider."""

from collections.abc import Callable
from datetime import datetime
from typing import Literal
from uuid import UUID

from telescope_rag.api.hours_presentation import project_hours_response
from telescope_rag.api.hours_responses import HoursChatResponse
from telescope_rag.api.offline_service import OfflineChatService
from telescope_rag.api.schemas import ChatRequest
from telescope_rag.api.source_choices import project_source_choices
from telescope_rag.core.errors import ApplicationError
from telescope_rag.core.settings import Settings
from telescope_rag.graph.contracts import EvidenceRetriever, WorkflowResult
from telescope_rag.graph.hours_contract import HoursProfile
from telescope_rag.graph.hours_workflow import HoursRagWorkflow
from telescope_rag.knowledge.hours import PublicHoursPlan
from telescope_rag.knowledge.public_links import PublicLinksCatalog
from telescope_rag.knowledge.source_authority import DirectoryAuthority
from telescope_rag.providers.contracts import ChatProvider
from telescope_rag.retrieval.assembly import AssemblyCounter, EvidenceCatalog


class HoursChatService(OfflineChatService):
    def __init__(
        self,
        *,
        settings: Settings,
        chat: ChatProvider,
        retriever: EvidenceRetriever,
        catalog: EvidenceCatalog,
        counter: AssemblyCounter,
        directory_authority: DirectoryAuthority,
        hours_plan: PublicHoursPlan,
        expected_hours_plan_digest: str,
        token_basis: Literal["qwen_retrieval_only", "synthetic_test"] = "qwen_retrieval_only",
        planner_output_tokens: int = 1000,
        draft_output_tokens: int = 1000,
        clock: Callable[[], datetime] | None = None,
        hours_profile: HoursProfile = "v12",
        reviewed_profile_limitations: bool = False,
        source_page_clarifications: bool = False,
        local_mvp_search: bool = False,
        conversational_answers: bool = False,
        website_links: PublicLinksCatalog | None = None,
        reuse_page_candidates: bool = False,
    ) -> None:
        if type(conversational_answers) is not bool or (
            conversational_answers and not local_mvp_search
        ):
            raise ValueError("conversational_answers_require_local_mvp")
        if website_links is not None and not conversational_answers:
            raise ValueError("website_links_require_local_conversation")
        workflow_type = HoursRagWorkflow
        if conversational_answers:
            from telescope_rag.graph.conversation_workflow import ConversationalRagWorkflow

            workflow_type = ConversationalRagWorkflow
        self._settings, self._catalog = settings, catalog
        self._conversational_answers = conversational_answers
        self._source_page_clarifications = source_page_clarifications
        self._website_links = website_links
        self._workflow = workflow_type(
            settings=settings,
            chat=chat,
            retriever=retriever,
            catalog=catalog,
            counter=counter,
            directory_authority=directory_authority,
            hours_plan=hours_plan,
            expected_hours_plan_digest=expected_hours_plan_digest,
            token_basis=token_basis,
            planner_output_tokens=planner_output_tokens,
            draft_output_tokens=draft_output_tokens,
            clock=clock,
            hours_profile=hours_profile,
            reviewed_profile_limitations=reviewed_profile_limitations,
            source_page_clarifications=source_page_clarifications,
            local_mvp_search=local_mvp_search,
            reuse_page_candidates=reuse_page_candidates,
            **({"website_links": website_links} if conversational_answers else {}),
        )

    async def draft(self, payload: ChatRequest, *, request_id: UUID) -> WorkflowResult:
        raise ValueError("hours_service_requires_hours_response_format")

    async def respond(self, payload: ChatRequest, *, request_id: UUID) -> HoursChatResponse:
        run = await self._run(payload, request_id=request_id)
        try:
            response = project_hours_response(
                run,
                catalog=self._catalog,
                request_id=request_id,
                bindings=self._workflow.hours_bindings,
            )
            if self._source_page_clarifications:
                response = project_source_choices(
                    response, run, catalog=self._catalog, bindings=self._workflow._bindings
                )
            if self._conversational_answers:
                from telescope_rag.api.conversation import project_conversation

                if self._website_links is not None:
                    from telescope_rag.api.website_links import project_website_links

                    response = project_website_links(response, run, self._website_links)

                response = project_conversation(response, run)
            return response
        except ValueError:
            raise ApplicationError(
                502, "offline_response_failed", "The offline response could not be validated."
            ) from None
