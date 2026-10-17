"""General source-scope guidance for the explicitly selected local MVP."""

from telescope_rag.prompts.planner_source_choice_v1 import PLANNER_SYSTEM as BASE_SYSTEM

PROMPT_VERSION = "local-rag-planner-v3"
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

A general introduction to a doctor, or a question about the doctor's role, is NOT
a request to select one particular profile webpage. Multiple admitted pages,
languages or layouts alone are not a reason to ask the visitor to choose a URL.
Source selection for an ordinary question is the assistant's job. When one doctor
in the reviewed primary directory clearly fits the intended person, answer directly
from that directory's matching owner-scoped record and state the full published
name. A unique matching first name can identify that directory entry; do not demand
the surname or a URL merely because the visitor used a short everyday expression.
Use intended_use=doctor_role for a general professional introduction, respecting
the existing primary-directory authority. Choose its issued document and literal
owner handles; do not broaden to unrelated owners or infer new cross-page identity
links. A directory record can answer without merging profiles or translating owners
into a new canonical identity. Keep unsupported details unknown.

Reserve source_page clarification for an actually requested, unresolved particular
page restriction, such as an explicitly singular individual profile. A general
doctor question has no such restriction: use a public retrieval/read plan with
clarification=null, not a technical page menu. If genuinely different people fit
the user's identity, preserve that uncertainty rather than guessing. Explicit URLs,
owner restrictions, and date/time ambiguities retain their existing safeguards.
"""
)
