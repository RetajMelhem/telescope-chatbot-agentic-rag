"""Separate candidate; old hours prompt bytes and defaults remain unchanged."""

from telescope_rag.prompts.planner_hours_v12 import PLANNER_SYSTEM as BASE_SYSTEM

PROMPT_VERSION = "offline-rag-planner-hours-contract-v14"
_RULE = "Return only the closed HoursPlannerReply schema, with at most four parts."
if BASE_SYSTEM.count(_RULE) != 1:
    raise ValueError("hours_contract_prompt_base_mismatch")
PLANNER_SYSTEM = (
    BASE_SYSTEM.replace(
        _RULE, "Return only the closed ContractHoursPlannerReply schema, with at most four parts."
    )
    + """
For local hours, pair hour and clock_basis consistently: 24h accepts 0 through 23;
am, pm and unspecified accept 1 through 12. Midnight at the start of a stated date
is 12/am or 0/24h; noon is 12/pm or 12/24h. Retain the original date and literal
time quote. Never silently move midnight to another date. Preserve unspecified
AM/PM or ask the existing faithful clarification; do not guess a clock basis.

A public time_comparison part has hours, retrieval_query=null and
intended_use=general_excerpt. Search/read_source, excluded and clarification parts
have hours=null. Missing scoped hours proof does not turn hours into a search.
Retain the requested source filters and leave unsupported hours unknown.

Doctor hours handles expose exact source_membership tuples: document_handle,
block_type and source_language. The selected doctor's tuple must satisfy all
declared source filters jointly. Different literal owners can name one approved
person while having different document memberships. For a confirmed person with
no explicit literal-owner restriction, prefer its issued canonical subject and
retain the user's exact alias quotation and source restrictions. For an explicitly
restricted literal owner, keep that owner's subject and scope. Do not select an
out-of-scope literal occurrence merely because its label matches the request.
Canonical identity links never transfer hours records, source ownership, language
or qualifications. Unconfirmed identities stay separate; no fuzzy equivalences,
fallback sources, fabricated facts or automatic output repair are permitted.
"""
)
