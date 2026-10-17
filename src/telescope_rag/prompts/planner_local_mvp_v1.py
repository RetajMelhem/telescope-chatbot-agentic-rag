"""General source-scope guidance for the explicitly selected local MVP."""

from telescope_rag.prompts.planner_source_choice_v1 import PLANNER_SYSTEM as BASE_SYSTEM

PROMPT_VERSION = "local-rag-planner-v2"
PLANNER_SYSTEM = (
    BASE_SYSTEM
    + """
For public search with intended_use=general_excerpt, leave document_handles=[],
owner_handle=null, block_types=[] and source_language=null unless the user actually
restricts that answer to a page, owner, source type or source language. A likely
topic match in a page title is not a user restriction. General references to the
center or its website do not identify an individual page. Search the admitted
corpus rather than guessing one page and excluding the answer before retrieval.
Keep every explicit source restriction. This guidance does not change the source
authority rules for doctor roles, applicability, eligibility or working hours.
Do not turn a requested single profile into an unrestricted search.

Determine intended_use from the relationship the answer must establish. Use
procedure_specific only for a claim about a particular treatment or procedure.
Administrative and visitor information remains general_excerpt even when medical
care is mentioned as context; an isolated clinical word does not establish a
procedure-specific relationship. Preserve separate applicability/eligibility uses.

When a user asks for one individual's profile without identifying the page, and
multiple admitted individual profiles could satisfy that description, request a
source_page clarification. More information on one page, or a language difference,
does not resolve which page the user intended. Offer the distinct relevant pages
without merging their owners. An exact URL or other unambiguous page identifier
resolves that source choice; then keep that exact restriction.
"""
)
