# Opt-in offline public-hours graph

`HoursRagWorkflow` connects the [reviewed hours data/math layer](PUBLIC_HOURS.md)
to the existing bounded graph. `HoursChatService` exposes it only through explicit
nonproduction construction with `offline_response_format="hours"`. Default chat
remains unavailable. Earlier planner profiles and response contracts are unchanged;
this is not production selection or model acceptance.

## Request interpretation

The separate v12 planner prompt replaces two inherited instructions (the schema
name and unavailable-time rule) and adds hours instructions. Earlier prompt files
remain byte-identical. Its schema adds a required nullable `hours` field to
each part. Public hours parts use the historical `time_comparison` operation,
`general_excerpt` purpose and no retrieval query, with these intents:

| Intent | Input and behavior |
| --- | --- |
| `schedule` | General published opening/closing/working-hours request; all date/time fields and quotes are null. No date or AM/PM clarification is needed. |
| `now` | Literal present-time reference; one aware application clock captured before planning supplies the instant. No model timestamp is accepted. |
| `local` | Calendar date when established, hour/minute and `24h`, `am`, `pm` or `unspecified` basis, with original request quotations. Missing date or material AM/PM ambiguity stays explicit. |

“When does the center open?”, “متى يفتح المركز؟” and “إيمتى بيفتح المركز؟” can
request the full posted schedule. The planner chooses the intent: no keyword
router or date/name parser classifies these strings. Tests supply authored plans;
they do not measure Luna's understanding. Weekday/time comparison currently needs
an established calendar date; there is no automatic “next Friday”. Unsupported
foreign-zone/relative-date interpretation remains unresolved.

Application-issued subject handles identify exact facilities or literal/canonical
doctors from the supplied plan/catalog. Record presence is metadata, not proof of
attendance. Center hours cannot fill a missing doctor schedule. Declared doctor
scope must match the subject; same-field doctors retain separate identities.

Subject/date/time quotations name their origin: current part, its declared
original-query reference, or a selected history message. The application derives
unique literal offsets within that origin. Missing, repeated and out-of-origin
quotes are refused. Original coverage, constraints, source handles, references,
history and negation checks still run. History is not clinic-hours evidence.
Literal binding cannot prove that model-selected subject/date/numeric values
interpret the question correctly. That semantic gate remains unverified.

## Evidence and response

Only reviewed records whose complete evidence is inside the exact part document/
owner/block/language scope are selected. Empty selection stays empty; no source,
language or owner fallback occurs. At most 16 source chunks per hours part are
accepted before downstream retrieval. Original plan IDs/digest and language claims
stay separate. Hours proof uses the same counted assembly and request budget.
Pure hours requests use one planner call, no search/embedding and no draft call;
mixed ordinary public parts can use the existing second extractive-draft call.
No judge, repair, retrieval loop, retry or token/credit guard is added.

The old source-stage `WorkflowResult` is unchanged: hours still records
`unknown / operation_unavailable`. A request-owned `WorkflowRun` sidecar carries
typed computation receipts and the clock. The hours presenter first validates
the original response, then independently rebinds/recomputes those receipts against
the registry, request and same clock. All required proof must actually be offered
to that question. Omitted, context-only and hidden coalesced occurrences cannot
establish an answer. Incomplete proof yields unknown without normalized schedules
or citations to unoffered content.

`offline-hours-response-v1` keeps literal questions, statuses and full citations,
adding a nullable per-question `hours` summary. Independent record IDs, source
hashes, weekly/dated rules, conditions and validity bounds remain in that summary.
Citations retain full source text, owners, URLs, sections, issues, timestamps and
snapshots. General listing compares complete rules, not only today's outcome.
Agreeing records can share a rendered listing while remaining separate records;
disagreement stays unknown even if both sources agree about the present moment.
Unlisted weekdays remain unknown. Freshness/effective/conditional limits, split
shifts, overnight carry, dated exceptions and ending-midnight wording stay explicit.

Time answers describe within/outside **published hours**, retain both unspecified
AM/PM candidates and identify unverified dated exceptions. Actual attendance,
availability and bookings are not established. The complete source booking
recommendation remains in the FAQ citations.

## Verification and remaining gate

The 73 new guarded integration cases use the real graph/provider adapter with
mocked transport and synthetic records. They cover bilingual opening variants,
date/time ambiguity, missing doctor hours, negations, reference origins, exact
scope/no fallback, split/overnight/dated rules, conflicts/freshness/qualifiers,
omitted/coalesced proof, receipt tampering, concurrent isolation, cancellation,
HTTP schema, default 503 and production refusal. The ignored
`artifacts/m5-hours-graph-v1` holds JUnit coverage, actual-bundle checks, preservation,
historical replay and the final seal. These are contract tests, not new whole-corpus
semantic review or live model accuracy.

Next: a bounded bilingual v12 schema and request-to-hours planner screen before
adoption. Author expected decisions before dispatch, include rephrased and mixed
questions, inspect subject/intent/date/AM/PM/constraint/source interpretation, and
record actual usage without automatic repair. Paid calls need authorization; none
ran for this offline implementation. Broader source/model/answer acceptance,
directory completion, publication and deployment remain separate obligations.
