"""Explicit nonproduction composition; no default clients, credentials or acceptance claims."""

from typing import Literal
from uuid import UUID

from telescope_rag.api.schemas import ChatRequest
from telescope_rag.api.validation import validate_chat_limits
from telescope_rag.core.errors import ApplicationError
from telescope_rag.core.settings import Settings
from telescope_rag.graph.contracts import (
    EvidenceRetriever,
    HistoryTurn,
    WorkflowRequest,
    WorkflowResult,
)
from telescope_rag.graph.workflow import OfflineRagWorkflow
from telescope_rag.knowledge.source_authority import DirectoryAuthority
from telescope_rag.providers.contracts import ChatProvider
from telescope_rag.retrieval.assembly import AssemblyCounter, EvidenceCatalog


class OfflineChatService:
    """Compose caller-owned dependencies for offline/development HTTP contract checks.

    The caller manages provider/retriever lifetime. Construction does not perform
    I/O; arbitrary injected dependencies are not certified offline by their type.
    No production model/profile, source approval or serving readiness is selected.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        chat: ChatProvider,
        retriever: EvidenceRetriever,
        catalog: EvidenceCatalog,
        counter: AssemblyCounter,
        planner_profile: Literal[
            "purpose_contract", "referent_context", "dependency_context", "local_constraints"
        ],
        directory_authority: DirectoryAuthority,
        token_basis: Literal["qwen_retrieval_only", "synthetic_test"] = "qwen_retrieval_only",
        planner_output_tokens: int = 1000,
        draft_output_tokens: int = 1000,
    ) -> None:
        if settings.app_env == "production":
            raise ValueError("offline_chat_requires_nonproduction")
        self._settings = settings
        self._workflow = OfflineRagWorkflow(
            settings=settings,
            chat=chat,
            retriever=retriever,
            catalog=catalog,
            counter=counter,
            token_basis=token_basis,
            planner_profile=planner_profile,
            directory_authority=directory_authority,
            planner_output_tokens=planner_output_tokens,
            draft_output_tokens=draft_output_tokens,
        )

    def check_configuration(self, settings: Settings) -> None:
        """Prevent transport/graph configuration drift before accepting requests."""
        if settings.app_env == "production" or settings != self._settings:
            raise ValueError("offline_chat_configuration_mismatch")

    async def draft(self, payload: ChatRequest, *, request_id: UUID) -> WorkflowResult:
        if type(payload) is not ChatRequest or type(request_id) is not UUID:
            raise ApplicationError(422, "invalid_request", "The request payload is invalid.")
        validate_chat_limits(payload, self._settings)
        request = WorkflowRequest(
            query=payload.query,
            language=payload.language,
            history=tuple(HistoryTurn(role=h.role, content=h.content) for h in payload.history),
        )
        run = await self._workflow.run(request, request_id=request_id)
        result = run.result
        if result.request_id != request_id.hex:
            raise ApplicationError(502, "offline_draft_failed", "The offline draft is invalid.")
        if result.outcome == "failed":
            if result.error_code == "deadline_exceeded":
                raise ApplicationError(
                    504, "request_timeout", "The request could not finish within its deadline."
                )
            raise ApplicationError(
                502, "offline_draft_failed", "The offline draft could not be validated."
            )
        # Same application-issued UUID, formatted consistently with HTTP headers.
        # Parts, quotes, ownership and all unverified/offline flags remain literal.
        return result.model_copy(update={"request_id": str(request_id)})
