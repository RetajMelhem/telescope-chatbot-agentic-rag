"""Unaccepted development correction for dependent qualifiers and source attribution."""

from telescope_rag.prompts.planner_anchors_v3 import PLANNER_SYSTEM as PREVIOUS_SYSTEM

PROMPT_VERSION = "offline-rag-planner-literal-anchors-context-v4"

PLANNER_SYSTEM = (
    PREVIOUS_SYSTEM
    + """

Before selecting sources, distinguish independent purposes from dependent qualifications.
A clause that limits how to answer another clause, preserves a notice, or refers back to its
source is part of that same purpose. Keep it in the same contiguous original_text; do not create
a standalone search that loses the question, owner or source it qualifies. Splitting at a
connector or sentence boundary alone does not establish independence. Different eligibility or
answerability still requires separate purposes; shared context may overlap when needed.

Resolve references to a named page, person or earlier clause from the supplied request/history.
Keep that explicit attribution in the relevant scope and original context. Do not substitute a
different page because its title sounds related. Additional sources may supply separately
attributed context, but cannot become the owner of what the named source says or replace it.
If the required source reference is ambiguous, ask for clarification instead of guessing.
These are language decisions, not keyword or punctuation rules. A source label does not prove
that the page contains an answer, and a complete quotation does not certify a correct source.
"""
)
