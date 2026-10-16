"""Opt-in clarification of local constraints and inherited literal context."""

from telescope_rag.prompts.planner_dependencies_v10 import PLANNER_SYSTEM as DEPENDENCY_SYSTEM

PROMPT_VERSION = "offline-rag-planner-local-constraints-v11"

LOCAL_CONSTRAINTS_APPEND = """
Each constraint_quotes item must be an exact unique quotation wholly inside that part's
original_text. Use an empty list when no such local quotation is needed. Permission to
overlap original spans does not permit a constraint outside its own original span.

A governing qualification inherited from another part or selected history still matters.
Preserve its necessary literal context in reference_text and, for public search, in the
independently consumed retrieval_query; retain additional necessary literal constraints in
that query too. Do not put inherited text into constraint_quotes unless it also occurs
inside this part's original_text. An empty constraint_quotes list does not cancel a shared
source restriction, subject/group, prohibition, comparison or time condition.

Every original non-whitespace character must still be covered by original_text spans.
References and queries do not provide that coverage. Include a leading or trailing shared
qualification in an appropriate contiguous original span, while carrying its context to
other affected targets through the existing reference/query fields. Never fabricate a
noncontiguous original quotation, drop a conjunction or punctuation, or copy an independent
question into another target merely to carry its context. Keep the complete requested
meaning, literal owners, source restrictions and genuine uncertainty. These field rules
do not authorize changing purpose, source, state, permissions or validators.
"""

PLANNER_SYSTEM = DEPENDENCY_SYSTEM + LOCAL_CONSTRAINTS_APPEND
