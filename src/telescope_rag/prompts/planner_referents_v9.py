"""Opt-in standalone referent instruction; existing fields, facts and validators stay intact."""

from telescope_rag.prompts.planner_contract_v8 import PLANNER_SYSTEM as CONTRACT_SYSTEM

PROMPT_VERSION = "offline-rag-planner-referent-context-v9"

REFERENT_CONTEXT_APPEND = """
Before submitting each public search, read its retrieval_query independently of the full
original_query, history and other parts. Preserve the complete unchanged answer target. When
that target refers back to a person, service, procedure, event or ordered group, include the
necessary literal antecedent in reference_text and retain it in retrieval_query. A document
handle, page name or URL identifies where to search; it does not identify which entity or claim
within a page is meant. A page reference alone is sufficient only when the page itself is the
referent. Use an exact quotation from the request or selected history that identifies what this
target asks about; where several names share a qualification, preserve the needed group and
its order. Do not add a redundant reference to an already self-contained target. This context
may quote an antecedent from another question without answering that question again; do not
copy that independent question into original_text merely to supply context. Preserve source,
time, negation and ownership qualifications, and do not mistake a prohibited or unrelated
neighboring topic for the antecedent. History can identify a referent, never establish clinic
facts. If the singular referent genuinely remains ambiguous among several entities, preserve
clear public siblings and ask for clarification for that part without retrieval; never guess,
rewrite names or turn an explicit plural group into ambiguity. These checks are by meaning,
not pronoun keywords. They do not expand source permissions, infer missing facts or authorize
an application-side repair. Read-source and time operations still have no retrieval_query.
"""

PLANNER_SYSTEM = CONTRACT_SYSTEM + REFERENT_CONTEXT_APPEND
