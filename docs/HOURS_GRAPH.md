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

The later bounded v12 development screen made 12 actual Luna planning requests:
all returned valid schema/literal bindings, but semantic review accepted 10 and
rejected two Arabic/Jordanian mixed doctor-hours identity clarifications. The
general opening questions and explicit evening-time cases passed in each language.
Three ambiguous-time cases directly requested clarification; they did not exercise
typed unspecified-AM/PM input, and current presentation uses a generic clarification.
The screen remains unadopted. Full evidence is in
`artifacts/m5-hours-planner-screen-v1/REPORT.md` and `semantic-review.json`.

The subsequent identity-context candidate below exposes existing approved canonical
relationships alongside literal hours handles and preserves unconfirmed ambiguity.
No question keyword rules or new name equivalences are justified by these cases.
Missing links were a confirmed metadata gap and a plausible contributor; the later
fresh-wording development confirmation does not establish a causal effect.
Broader live now/history/source-scope tests, answer/source/model acceptance,
directory completion, publication and deployment remain separate obligations.

## Bounded development screen runner

`scripts/run_hours_planner_screen.py` freezes an explicitly authored cohort of at
most 12 cases. `--cases <cases.json> --output <new-directory>` captures the actual
graph planning node's messages/schema and a frozen application clock without
dispatch. Expected decisions stay outside the model payload. `--execute` requires
exact case/source/code/payload hashes and a clean committed checkout before an
exclusive start marker and key loading. Only request validation, planning and plan
validation run; retrieval, assembly, drafting, embeddings and Qdrant are forbidden.

The one-call-per-case screen uses a 4,096-token output cap, 30-second deadline,
normal reasoning and reported input usage. Serving settings stay unchanged; no
local input-counting or credit guard is added. Failed/ambiguous attempts are not
retried, and a started run cannot repeat. Actual proposals, binding/computation
receipts, generation IDs when supplied and usage remain in ignored evidence for
separate semantic review. Literal success does not admit a model or production.

## Opt-in approved identity context

`HoursRagWorkflow(hours_profile="identity_links_v13")` projects only existing
admitted `canonical_doctor_id/name` relationships into a separate hours manifest.
Each group retains its canonical subject/owner handles, approved display name,
literal member subject/owner handles, exact labels and source chunk/document
witnesses. All original subjects and labels remain unchanged. No name, specialty
or translation matching creates a relationship. Partial or conflicting identity
metadata fails closed; distinct confirmed IDs stay separate even when their display
labels match. The manifest retains its 96,000-byte bound.

Identity links establish one confirmed person, never a published schedule. They do
not transfer hours records or erase literal document/owner/language restrictions.
The same exact binding and source-proof rules apply; missing doctor hours stay
unknown. The candidate changes only the user body's version and hours-manifest
metadata. System prompt, output schema, caps, reasoning and other payload fields
remain identical to v12. The default remains v12, with no API or production adoption.

The screen runner accepts `--hours-profile identity_links_v13` for a new preparation
directory, pins it in the frozen plan, then rebuilds that same profile on execution.
Six fresh bilingual development cases and their expectations are frozen in
`artifacts/m5-hours-identity-context-v1`; they include approved aliases, separate
doctor/facility requests, genuinely ambiguous identities/history and a two-doctor
comparison. All six actual Luna planning responses are strict/literal-valid; the
primary Codex assistant individually accepts all six proposals/ten parts under
their frozen expectations, with literal-scope and generic-clarification cautions.
Six exact actual-plan offline replays preserve supported facility schedules,
missing doctor hours and both genuine identity ambiguities. Evidence and remaining
limits are in `artifacts/m5-hours-identity-context-v1/REPORT.md` and
`semantic-review.json`. No paid same-input control was run, so no causal effect or
universal robustness is claimed. Default v12 and API behavior remain unchanged.

Next: broader bounded hours acceptance for now/local inputs, unambiguous history,
exact source restrictions and alias-scope contrasts, including old failures and
fresh controls. Production adoption and wider chatbot acceptance stay separate.

The later cohort is frozen in `artifacts/m5-hours-broader-acceptance-v1`: two exact
earlier failures plus ten fresh English/Arabic/Jordanian contrasts. The unchanged
v13 candidate is tested for now intent, explicit Friday/midnight boundaries,
unambiguous history, untrusted assistant assumptions, unspecified AM/PM, exact
FAQ document/language restrictions, contact-only missing proof and a confirmed
alias under a directory restriction. Expectations stay outside provider payloads.
Twelve authored oracle plans pass offline through the actual catalog, Qwen counter,
graph and presenter; oracle success is not evidence of model interpretation.
The development runner uses a captured application clock for reproducibility:
now-intent acceptance does not establish production wall-clock behavior.
The executed bounded screen keeps the prompt/schema/model/caps and default API
unchanged and has no automatic retries. All twelve actual proposals/sixteen parts
were individually reviewed: nine requests/thirteen parts accepted with cautions,
three failed. Two failures are safely rejected (`0/am` midnight representation,
non-null search query on an hours operation). The third selects profile-only
literal h93 under the main-directory d0033 restriction; with no owner filter, binding
accepts the subject without source-membership verification, yielding a safe but
scope-masked unknown. This blocks adoption. Exact actual-plan offline replay
reproduces ten completed requests and both validation failures; four explicitly
authored one-field counterfactuals demonstrate valid representations, not model
repair. The AM/PM case safely asks direct clarification and still does not establish
live typed-unspecified coverage. The report and individual ledger retain all limits.

Next: offline repair of clock representation, hours/search exclusivity and exact
doctor-subject/source-scope linkage in a separate candidate, with focused regressions
and contrasts. Preserve approved identities, literal provenance and unknown outcomes;
do not add automatic normalization, fuzzy matching or question-specific routing.
Freeze further confirmation before paid dispatch; production adoption remains held.

## Separate hours contract candidate

`hours_profile="contracts_v14"` selects `ContractHoursPlannerReply`, explicit
clock/operation descriptions and a versioned prompt. Local validators require
0–23 with 24h and 1–12 with am/pm/unspecified, and non-null hours exactly for public
time_comparison with a null retrieval query and general_excerpt purpose. Invalid
combinations are rejected without conversion or another provider request. The
provider boundary may reject a bad plan before the graph's older validators.

The candidate hours manifest adds exact doctor source-membership tuples for each
existing handle. It preserves literal/canonical owners and labels and retains
the 96,000-byte bound. `ContractHoursBindings` intersects a selected doctor with
all declared document/type/language/owner restrictions; an impossible occurrence
is rejected rather than silently changed to another alias. The independent
presenter rechecks the same relationship. Canonical preference is an explicit
model instruction using already-approved links; it never overrides an explicit
literal-owner restriction or transfers a schedule between owners. Valid scoped
missing hours and facility contact-only unknowns remain unchanged.

All 30 earlier v12/v13 payloads reconstruct exactly. Default graph/API selection
remains v12. The runner's `--hours-profile contracts_v14` option freezes the new
schema; execution uses the frozen profile and exact payload, with no automatic
retry/repair. The candidate is not exposed by default API injection or adopted
for production. The later bounded hosted confirmation below is separate from
the implementation's offline verification.

The real-bundle audit replays twelve saved proposals under v14: nine complete and
all three known bad plans are rejected. Four explicitly authored valid variants
and six frozen confirmation oracle plans work through the actual catalog/Qwen/
graph/presenter with mocked transport. These checks do not establish Luna behavior.
Evidence: `artifacts/m5-hours-contract-repair-v1/REPORT.md`. **1,986 guarded tests**
pass, including 59 new contrasts. Those preparation receipts remain historical;
the frozen six-case confirmation subsequently ran once, as recorded below.

The confirmation made six actual HTTP 200 Luna/OpenAI planner requests: all six
passed strict-schema and literal/binding checks. Primary Codex language reasoning
individually accepted all six complete outputs/six parts against the frozen
criteria and saved official sources, including two cautions. The three previously
failing clock/operation/doctor-scope cases now pass. Fresh contrasts preserve noon,
24-hour midnight/no-booking and an explicitly literal profile restriction. Six
unchanged actual-plan replays through the real catalog/Qwen/graph/presenter complete;
three time comparisons retain both native FAQ citations and three scoped missing
hours remain unknown without fallback. Added facets discard no current exact-scope
member, but future structure completeness is untested. The noon negation survives
in original_text and is correctly interpreted without a separate constraint receipt.

Evidence: `artifacts/m5-hours-contract-confirmation-v1/REPORT.md`, individual ledger,
scope/replay/accounting checks and final seal. The prior 1,986-test pass is preserved
against unchanged code/tests; this documentation/evidence step did not rerun the
full suite. No runtime, source, index, credential or default API behavior changed.
The runner's original summary retains pending semantic review; the later separate
ledger binds every reviewed actual receipt by hash. No receipt is retroactively
rewritten. Three exposed regressions plus three fresh development cases do not
establish broad new-prompt acceptance, independence or production readiness.

Next: offline consolidation of existing hours cohorts under v14 and an explicit
acceptance-gap matrix. Replaying saved decisions tests execution/nonregression,
not the new prompt's ability to make every decision. Select any further minimal
live coverage only from those documented gaps. Typed unspecified AM/PM, broader
hours-model behavior, answer/directory acceptance and serving remain unverified;
default v12 stays and production adoption is held.
