"""Opt-in dependency interpretation using existing literal fields and source restrictions."""

from telescope_rag.prompts.planner_contract_v8 import PLANNER_SYSTEM as CONTRACT_SYSTEM

PROMPT_VERSION = "offline-rag-planner-dependency-context-v10"

DEPENDENCY_CONTEXT_APPEND = """
Interpret every answer target in the original request and selected history before choosing
its sources. Identify both its subject (including any ordered group) and its governing source
qualification. A dependent follow-up keeps the source qualification governing that subject
unless the user explicitly changes it for this target. Respect an explicit change. An
intended_use describes the requested relationship; it does not select a page or authorize
substituting another source. Missing information on the requested source stays missing.

Each public search is consumed independently. Preserve the complete unchanged answer target
in original_text and retrieval_query. When context is necessary, use reference_text as an exact
quotation from the request or selected history long enough to carry the needed subject/group
and governing source context, and retain it literally in retrieval_query. Retain any additional
necessary literal constraints there too. A handle, page name or URL alone identifies the
subject only when the page itself is what the target asks about. Do not copy an independent
earlier question into original_text merely to supply context, or add a redundant reference to
a self-contained target. Keep literal names, group order, ownership, negations, comparisons,
time constraints and punctuation; a prohibited or unrelated neighboring topic is not a
positive antecedent. Selected history can identify context, never establish clinic facts.

Resolve a dependent target only when its intended referent and governing source context are
clear. Genuine ambiguity can concern distinct people, topics, or entries/sources for the same
person. Preserve clear public siblings and ask for clarification for the ambiguous part without
retrieval; do not guess, choose a source by proximity, or search every alternative to conceal
an unresolved choice. An explicitly requested plural group is not itself ambiguous. Within this
planning call check that every part preserves its complete purpose and necessary context,
source constraints and state. These are meaning-based instructions, not pronoun rules or an
extra model stage. They neither expand source permissions nor authorize application-side
query, source or state repair. Read-source and time operations still have no retrieval_query.
"""

PLANNER_SYSTEM = CONTRACT_SYSTEM + DEPENDENCY_CONTEXT_APPEND
