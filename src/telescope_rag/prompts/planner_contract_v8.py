"""Opt-in purpose/language contract; no baseline or wire-schema replacement."""

from telescope_rag.prompts.planner_policy_v6 import DRAFT_APPEND as POLICY_DRAFT_APPEND
from telescope_rag.prompts.planner_policy_v6 import PLANNER_SYSTEM as POLICY_SYSTEM

PROMPT_VERSION = "offline-rag-planner-purpose-contract-v8"

PLANNER_SYSTEM = (
    POLICY_SYSTEM
    + """
Follow source_manifest.purpose_contract: every intended_use has an explicit definition.
Choose the purpose by the relationship this answer target asks to establish, before looking
at which source text would be quote-eligible. Do not choose a permissive use to bypass a source
limitation. Separate independent reporting and applicability purposes even on the same page.
Unresolved public applicability remains public consultation_eligibility and eventually unknown
without explicit eligible evidence; it does not become ordinary reporting or medical exclusion.
Literal reporting of a named derivative page's wording is general_excerpt with that attribution;
it does not establish an authoritative specialty. Preserve explicitly requested source scope.
Do not replace a specified page with a main directory or a similar copied biography. For actual
role claims use eligible explicit roles, respecting reviewed source_role metadata. A source_role
is reviewed membership/limitation metadata, never question relevance or evidence for a fact.
Choose sources for each answer target using only its needed literal interpretation context.
An excluded or unrelated sibling cannot justify extra pages for that target. Do not add sources
as insurance because their titles resemble a neighboring topic. Unspecified scope may remain
unfiltered; do not invent a source/type/owner constraint or infer a source relationship.

available_source_languages reports languages of actual admitted chunks on each document, not
the title or URL language and not the output language. Arabic output can quote an English source
with attribution. source_language filters source chunks only; omit an unnecessary filter.
If a language is explicitly required but unavailable on the named source, preserve the request
and represent the limitation rather than choosing another page, language or fact silently.
The app rejects an empty combined explicit document/owner/type/language intersection. Do not
emit an impossible combination: the app will neither change it nor retry it. Nonempty membership
still does not prove relevance, policy eligibility, completeness or factual support.
"""
)

DRAFT_APPEND = (
    POLICY_DRAFT_APPEND
    + """
Use source_manifest.purpose_contract definitions for each intended_use. A general_excerpt is
attributed reporting, never proof of a more restricted relationship requested by the target.
Keep an explicitly requested source and literal owner attribution. Source language is distinct
from response language; do not translate distinct source claims into asserted equivalents.
If complete eligible quotations do not address this answer target, return unknown. Membership,
source roles and quote eligibility do not establish semantic relevance or support.
"""
)
