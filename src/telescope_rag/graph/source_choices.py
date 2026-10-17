"""Opt-in source-page clarification proposals and literal handle bindings.

Choices are interpretation proposals, never identity links, factual support or
retrieval authorization. No name matching or free-form reason parsing occurs.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import ClosedRecord, ValidatedPlan
from telescope_rag.graph.hours_contract import ContractHoursPlannerPart, ContractHoursPlannerReply


class SourcePageChoiceInput(ClosedRecord):
    kind: Literal["source_page"]
    document_handles: tuple[str, ...] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def distinct_documents(self):
        if len(set(self.document_handles)) != len(self.document_handles):
            raise ValueError("duplicate_source_page_choice")
        return self


class SourceChoicePlannerPart(ContractHoursPlannerPart):
    clarification: SourcePageChoiceInput | None = Field(
        description=(
            "Only for clarification_required when the requested source page is ambiguous: "
            "2..4 distinct issued document handles proposed as choices. Otherwise null. "
            "Does not assert shared identity, source support or permission to retrieve."
        )
    )

    @model_validator(mode="after")
    def clarification_state(self):
        if self.clarification is not None and self.state != "clarification_required":
            raise ValueError("source_choices_require_clarification")
        return self


class SourceChoicePlannerReply(ContractHoursPlannerReply):
    parts: tuple[SourceChoicePlannerPart, ...] = Field(min_length=1, max_length=4)


@dataclass(frozen=True)
class SourcePageChoiceBinding:
    part_id: str
    document_handles: tuple[str, ...]
    document_ids: tuple[str, ...]
    snapshot_id: str
    prepared_digest: str


@dataclass(frozen=True)
class SourceChoicePlan(ValidatedPlan):
    source_page_choices: tuple[SourcePageChoiceBinding, ...] = ()


def bind_source_choices(
    proposal: SourceChoicePlannerReply, plan: ValidatedPlan, bindings: SourceBindings
) -> SourceChoicePlan:
    records = []
    for proposed, part in zip(proposal.parts, plan.assembly_request.parts, strict=True):
        choice = proposed.clarification
        if choice is None:
            continue
        if proposed.state != part.state or part.state != "clarification_required":
            raise ValueError("source_choices_require_clarification")
        handles = choice.document_handles
        if any(h not in bindings.documents for h in handles):
            raise ValueError("source_choice_handle_unissued")
        documents = tuple(bindings.documents[h] for h in handles)
        catalog = bindings._catalog
        records.append(
            SourcePageChoiceBinding(
                part.part_id,
                handles,
                documents,
                next(iter(catalog.chunks.values())).snapshot_id,
                catalog.prepared_digest,
            )
        )
    return SourceChoicePlan(
        plan.language,
        plan.assembly_request,
        plan.operations,
        plan.retrieval_queries,
        plan.semantic_interpretation_verified,
        tuple(records),
    )
