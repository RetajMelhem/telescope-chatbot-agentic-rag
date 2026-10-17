"""Opt-in source-choice contract; earlier planner/schema bytes stay unchanged."""

from telescope_rag.prompts.planner_hours_contract_v14 import PLANNER_SYSTEM as BASE_SYSTEM

PROMPT_VERSION = "offline-rag-planner-source-choice-v1"
_RULE = "Return only the closed ContractHoursPlannerReply schema, with at most four parts."
if BASE_SYSTEM.count(_RULE) != 1:
    raise ValueError("source_choice_prompt_base_mismatch")
PLANNER_SYSTEM = (
    BASE_SYSTEM.replace(
        _RULE, "Return only the closed SourceChoicePlannerReply schema, with at most four parts."
    )
    + """
Every part includes clarification, normally null. When the intended source page
is materially ambiguous, use state=clarification_required and clarification with
kind=source_page and two to four distinct issued document_handles as proposed
page choices. Other ambiguities can keep clarification=null. Do not claim that
similar names establish the same person, or that every profile lacks information.

These choices are separate from retrieval filters: a clarification part still has
retrieval_query=null, document_handles=[], owner_handle=null, block_types=[],
source_language=null and hours=null under the existing contract. Keep the original
question, negations and restrictions intact. A proposed page choice is not an
answer, an identity link or permission to retrieve/fetch it. Never invent a handle
or source, choose another page silently, or add clinical claims to a clarification.
"""
)
