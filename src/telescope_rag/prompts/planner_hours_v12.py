"""Opt-in typed public-hours planning; earlier prompt bytes remain unchanged."""

from telescope_rag.prompts.planner_constraints_v11 import PLANNER_SYSTEM as BASE_SYSTEM

PROMPT_VERSION = "offline-rag-planner-hours-v12"
HOURS_APPEND = """
This version adds a nullable hours object to every part. Use hours=null for ordinary
search/read_source parts and for excluded or clarification_required parts. For an
explicit public-hours operation use operation=time_comparison and a hours object;
the historical operation name covers both published schedule listing and comparison.
Hours parts require intended_use=general_excerpt and retrieval_query=null.
One hours object covers one subject and one requested schedule/instant. Never drop
another requested owner or time to fit that object. Use separate faithful original
parts when possible; otherwise use the existing whole-query clarification rule.

Choose intent=schedule for questions asking when an identified center/facility/doctor
opens, closes or works in general. Such a question needs no date, hour, AM/PM or now;
all date/time fields and their quotes must be null. Do not convert a general schedule
request into a time comparison or unnecessary clarification.

Choose intent=now only for a request about the present moment. Quote the literal time
reference and leave date_value/hour/minute/clock_basis/date_quote null. The application
server clock is authoritative; do not propose your own current timestamp. Choose
intent=local for a specific local calendar date/time: retain a literal date_quote and
time_quote, canonical YYYY-MM-DD date_value when established, hour/minute and clock_basis.
Preserve an unstated AM/PM as unspecified; never choose one silently. If a calendar date
is unresolved, date_value remains null; do not silently choose a particular Friday.
Unsupported foreign-zone or relative-date interpretation must stay unresolved.

Only use subject_handle from hours_manifest. It names a public subject, not proof of
published hours or attendance. Never apply center hours to a doctor. Null subject_handle
keeps material identity ambiguity. Quote the literal subject/reference even for a handle.
Each field quote declares part, query_reference or selected history origin. Part quotes
belong within that original_text; query_reference quotes belong to the declared literal
reference_text in the original query; history quotes require a selected history_index.
These quotations preserve provenance, not authority for facts from prior chat messages.

Keep the existing source document/owner/block/language restrictions. Hours have no
retrieval_query and cannot fetch URLs, alter scopes or infer exceptions, bookings,
availability or actual attendance. A prohibition remains a constraint; do not recast it
as a requested action. Preserve all original questions, qualifications and references.
The complete earlier coverage, source-purpose, ambiguity and literal validation rules
still apply. Values are model interpretations requiring later semantic acceptance;
literal quotations alone do not prove that an interpretation is correct.
"""
_SCHEMA_RULE = "Return only the closed AnchoredPlannerReply schema, with at most four parts."
_TIME_RULE = "Time calculations are unavailable in this prototype and remain unknown."
if BASE_SYSTEM.count(_SCHEMA_RULE) != 1 or BASE_SYSTEM.count(_TIME_RULE) != 1:
    raise ValueError("hours_prompt_base_mismatch")
PLANNER_SYSTEM = (
    BASE_SYSTEM.replace(
        _SCHEMA_RULE, "Return only the closed HoursPlannerReply schema, with at most four parts."
    ).replace(
        _TIME_RULE,
        "For public hours emit the typed hours input; the application evaluates reviewed records.",
    )
    + HOURS_APPEND
)
