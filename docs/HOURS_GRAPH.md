# Opt-in offline public-hours graph

`HoursRagWorkflow` connects the [reviewed hours data/math layer](PUBLIC_HOURS.md)
to the existing bounded graph. `HoursChatService` exposes it only through explicit
nonproduction construction with `offline_response_format="hours"`. Default chat
remains unavailable. Earlier planner profiles and response contracts are unchanged;
this is not production selection or model acceptance.

Trusted callers may pass `hours_profile="contracts_v14"` to `HoursChatService`;
`"identity_links_v13"` is also supported. The constructor forwards the selected
profile to `HoursRagWorkflow`, preserving `"v12"` when omitted. This is an explicit
nonproduction composition option, not a field in `ChatRequest`, environment toggle
or default factory change. The caller still supplies the source catalog, reviewed
hours plan/digest, directory authority, providers and counter, and owns their
lifetimes. The service type does not make injected providers inherently offline.

Planner output remains 1,000 by default. Replaying the hosted development screens
uses explicit `planner_output_tokens=4096` and their matching bounded settings to
preserve the exact tested wire. Selecting a profile alone does not change capacity,
retry policy or budgets, and live compliance at the default cap is not established.

## Actual-plan retrieval and draft continuation (2026-10-17)

The [bounded downstream screen](../artifacts/m5-general-downstream-v1/REPORT.md)
continues the three accepted P01/P03/P05 treatment plans with exact original wire
checks and zero new paid planning. Three actual Luna drafts, two Qwen query
embeddings (77 tokens) and three authenticated exact Qdrant queries complete with
HTTP 200 after offline controls and preflight. The English query uses its existing
cache; new vectors are request-local. No retry, fallback, K increase, index write
or default adoption occurred.

Primary Codex individually reviewed all three actual drafts / four final question
parts against saved official sources. All four requested role witnesses are
retrieved and cited, keeping Odaibat/Farash separate, Arabic qualifiers intact and
hours citations with the hours part. Farash remains anesthesia/critical care;
the inherited department heading does not establish his specialty. The hours
draft's unknown/operation_unavailable is intentional: the existing deterministic
hours presenter supplies the reviewed schedule and preserves uncertainty.

Scoped witness Recall@5 and binary nDCG@5 are 1.0 in each request, with 13
primary-authored judgments frozen before ranking. The English scope contains 11
cards; Arabic scopes contain one each, making their ranking trivial once the scope
is correct. Three unrelated English top-five cards are not cited. These results
establish neither global corpus recall nor a causal answer gain over control.

Exact offline replay reproduces every actual draft/final response, query vector
and filter. Ninety-two original DOM spans across 15 chunks / four saved pages pass,
covering nine offered and six cited chunks. Seventy-six focused guarded regressions,
Ruff (202 files) and the 65-package lock pass. The previous full 2,075-test receipt
remains bound to unchanged runtime and tests; it was not rerun here.

New cost is $0.001569545, exactly matching key usage change and per-call route/cache
rates: 7,992 chat input / 1,140 output tokens, including 501 reasoning tokens already
within output, plus 77 embedding tokens. The observed remaining allowance is
$0.954834715 at October 17 15:32:57 Asia/Amman. Mean continuation is 6.224 seconds,
excluding previous planning/resource loading. Earlier planner charges are referenced
once separately. Source/cache/credential bytes and candidate metadata remain intact.

Next freeze an independently worded M5 acceptance cohort and source judgments,
starting offline, before further bounded live acceptance or serving integration.
P02/P04 source-page choices remain pending, full excerpts retain presentation
limits, and polished Jordanian generation is unverified. This screen does not
re-audit all 955 chunks, approve defaults or establish production readiness.

## Paired live planner comparison (2026-10-17)

The [six-pair development screen](../artifacts/m5-profile-limitations-live-v1/REPORT.md)
made 12 actual planner calls at checkpoint `0e4f6a7`, with counterbalanced first
arms, identical paired inputs except the optional source-view field, and no retry.
All schemas passed; literal/source validation passed 5/6 control and 6/6 treatment
plans. The failed control used a sparse profile with a different main-directory
owner and was rejected without repair.

Primary Codex individually read 12 actual proposals / 14 parts and the relevant
saved source excerpts. General role questions with all target source witnesses
reachable improved from 1/3 control to 3/3 treatment on this screen (2/4 to 4/4
role witnesses). Both versions respected all three explicit profile-only requests.
The original English comparison selected the correct main directory in both arms,
so that pair alone demonstrates no treatment gain. Two source-choice cases remain
unresolved; there is no six-of-six semantic acceptance score. These are planner
source-scope results, not measured ranking, Recall@K/nDCG or final answer accuracy.

The review also corrects an earlier overgeneralization: informative individual
profiles already exist at `/dr-osama-odaibat/` and `/ar/dr-rihab-ghanma/`, alongside
separate name-only `/doctors/` pages. Exact saved HTML supports their content.
The occurrence-scoped implementation did not suppress these informative sources.
The old sealed review and frozen expectations remain intact, with the correction
and material page-choice uncertainty documented separately. No source text,
identity link or admission decision changed.

All 12 actual plans and their exact source-validation outcomes replay offline;
both restricted Farash plans assemble to unknown/context_only without a draft.
Thirty-two source chunks / 14 saved pages have 194 exact DOM witness checks.
Thirty-nine focused guarded regressions and Ruff/lock checks pass. The earlier
2,075-test full result remains bound to unchanged runtime/tests, not newly rerun.

Cost was $0.04229628, exactly reconciled to the key change and independently
recomputed for every call with cache rates. The view added 2,001 native input
tokens per call. Control/treatment costs were $0.021030825 / $0.021265455, with
observed mean attempt times 8.310 / 5.883 seconds. Different reasoning/output
lengths and caching confound cost/latency comparisons; no causal speed gain or
generalization estimate follows. The last key observation was $0.95640426 remaining
at October 17 04:09:54 Asia/Amman; no further review-time API request refreshed it.

The subsequent P01/P03/P05 actual retrieval/draft continuation is recorded above.
Its three plans are reused without new paid planning. Ambiguous individual-page
choices remain pending and the view stays opt-in; serving adoption and production
readiness remain unproven.

## Reviewed profile-limitations source view (2026-10-17)

With `hours_profile="contracts_v14"`, trusted callers may explicitly set
`reviewed_profile_limitations=True`. The default is false; v12/v13 reject enabling
it. This adds only `source_manifest.reviewed_profile_limitations` to the planner's
input. The system prompt, output schema, draft input, source validation, retrieval,
budgets and public request schema remain unchanged. No environment selector or
default adoption was added.

The view projects the existing admitted
`name_only_profile_no_specialty_or_biography_claim` flag. Each listed chunk keeps
its exact document handle, literal/canonical owner handles, source language and
block type, bound to the existing prepared digest and admission policy. Other
chunks for the same person or document do not inherit that flag. Other issue codes
are not inventoried here, and absence is not evidence that a source is informative
or complete. Naming/literal quotation remains possible; explicit profile-only
restrictions cannot be broadened. No names, question patterns or source IDs select
an operation or source automatically. The existing 96,000-byte manifest bound is
retained without truncation.

The [offline evidence](../artifacts/m5-profile-limitations-view-v1/REPORT.md) records
22 exact projected occurrences and 66 original DOM witnesses. Primary Codex read
each annotation and its identity witnesses; this is not a new semantic audit of all
955 chunks or excluded content. Thirty-six new / 2,075 full guarded tests pass.
Authored English, Arabic and Jordanian Arabic HTTP controls preserve useful
directory evidence, synthetic informative profiles, literal names and profile-only
unknowns. Six control/treatment replays retain all prior actual outputs; removing
the new field reconstructs the original planner payloads exactly. Holding outputs
fixed verifies isolation, not a model accuracy gain.

The source manifest grows from 44,022 to 49,700 UTF-8 bytes. Native token usage,
cost, latency and improved model source selection were unmeasured at this offline
checkpoint. Six paired development cases / 12 planner-only payloads were frozen
without execution; the subsequent live comparison is documented above. No draft,
embedding, index call, source edit, allowance refresh or new spend occurred during
that preparation step.

## Mixed-source offline verification (2026-10-17)

The subsequent [live mixed screen](../artifacts/m5-mixed-live-screen-v1/REPORT.md)
ran three actual planner requests against the same corpus/candidate. Arabic PRK
completed real retrieval and a strict extractive draft; English hours succeeded,
but doctor-role retrieval was restricted to name-only profiles and stayed unknown.
The Jordanian request's evaluation journal hit a concurrent filename collision;
the original failure is preserved. After the independently tested audit fix
(`677b1b6`), a separately frozen continuation reused that actual plan, repeated its
72-token embedding batch deliberately and completed retrieval/drafting without a
new paid planning call. It is not an uninterrupted initial end-to-end success.

All three actual plans, two actual drafts and seven final parts received individual
Codex language review; six parts are source-supported, with one safe unknown recall
failure. Exact mocked replay reproduces their actual payloads and final responses.
The live evidence establishes these two draft-schema/extractive representations;
general answer quality, colloquial presentation and default serving remain unaccepted.
No new source fact, source/identity policy, normal graph behavior or default profile
was introduced. The subsequent opt-in source-view implementation is described
above; its effect on actual model choices remains unverified.

`tests/integration/test_hours_dense_http.py` exercises the v14 HTTP service with
the existing request-scoped dense bridge and actual provider/candidate adapters,
using synthetic sources, a synthetic test tokenizer, authored planner/draft replies
and mocked transports. Thirty-seven tests cover three input languages, separate
same-field doctors, hours/source citation ownership, booking exclusion, cache and
complete-source paths, missing evidence, stale hours, missing chat usage, concurrent
budgets, corrupted payloads, altered/swapped citations, omitted parts and timeouts.
Failure tests assert the specific internal rejection, not just an HTTP error.

Nine additional development controls use the unchanged Telescope bundle and pinned
Qwen tokenizer, with historically authenticated cached vectors. All 21 parts pass
through HTTP, graph, source assembly, extractive draft validation and presentation.
Six controls use cached cosine candidates through mocked embedding/Qdrant transports;
three two-doctor controls use exact owner-scoped main-directory reads. Both model
stages are authored replies. The source review and all 30 original DOM-span matches
are recorded in [the local report](../artifacts/m5-mixed-hours-retrieval-v1/REPORT.md).
These generated local artifacts are not distributed clinic knowledge or Git assets.

The unscoped two-doctor top-five pools all miss the second doctor. Correct scoped
reads establish representability, not a live planner's interpretation. No K increase,
corpus edit or runtime special case was introduced. Full source excerpts and formal
Arabic presentation remain review-only. The later live screen is documented above;
default chat, source policy and production refusal are unchanged.

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
interpret the question correctly. Broader semantic acceptance remains unverified;
the bounded v14 development results and their limits are recorded below.

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

## Consolidated hours acceptance evidence

`artifacts/m5-hours-consolidation-v1` binds all four cohorts: 36 actual saved
proposals/50 parts, representing 31 distinct request contents. Their existing
individual semantic verdicts are imported with exact output/review hashes; this
does not claim a new semantic grading or new v14 model decisions. Every proposal
is replayed unchanged against both its original wire/profile and v14 at its
original clock, using actual catalog/Qwen/graph/presenter, mocked transport and
socket/DNS guards. All 36 old payloads reconstruct exactly. Of 72 mocked calls,
34 original-profile and 33 v14 requests complete. All 33 jointly completed projected
responses are identical. The three known invalid broader-screen proposals are
rejected under v14, including the formerly accepted doctor/document mismatch.
The two earlier false identity clarifications still execute and remain inherited
semantic failures. Execution completion never substitutes for meaning review.

The authored 12-row `acceptance-gap-matrix.json` distinguishes older-prompt
decisions, current six-case v14 live evidence, offline execution contracts and
separate serving/answer gates. Current live v14 evidence has no supported weekly
listing, now/inside-boundary result, mixed positive booking, genuine ambiguity or
supported exact-language FAQ listing. The proposed six-case cohort targets these
gaps without repeating the successful midnight/profile checks. Two requests are
exact exposed regressions and four are fresh development compositions; they are
not an independent holdout. All six authored oracles/12 parts pass offline through
the real bundle, with explicit source-grounded language review. No oracle is
represented as actual Luna output. Either faithful direct AM/PM clarification or
typed unspecified input remains acceptable; do not spend repeated calls to force
one safe representation. Generic clarifications/dialect style remain limitations.

The focused hours suite passes 253 guarded tests; lint/format (197 files), lock
(65 packages), prior 481-file seal, source/cache/credential preservation and local
links pass. The earlier full 1,986-test pass is preserved, not rerun. No runtime,
prompt, source, API or index behavior changed; no external request/spend occurred.
The frozen unexecuted proposal is
`artifacts/m5-hours-consolidation-v1/proposed-run/plan.json`, with expectations
outside model payloads. Next is the separately requested bounded six-case broader
acceptance after allowance/pricing refresh, then individual actual-output review
and unchanged replay. Production adoption and whole-system readiness remain held.

That proposed broader screen subsequently executed once at checkpoint `e5ee6fa`:
six actual HTTP 200 Luna/OpenAI responses, all strict-schema/literal-valid. Primary
Codex language reasoning individually accepts six complete actual proposals/12
parts against the frozen criteria and saved official sources, with explicit cautions.
The full weekly opening response, Arabic pharmacy/confirmed canonical Lina/excluded
booking, two independent now comparisons plus the optical opening boundary, native
English/Arabic FAQ restrictions and two genuine clarifications with a retained
pharmacy answer all satisfy their scoped expectations. All six actual proposals
replay unchanged through the catalog/Qwen/graph/presenter. Eight supported parts
retain 14 exact question-owned citations; one doctor unknown, one booking exclusion
and two direct clarifications remain safe. The runner's original pending flags
stay unchanged; the later individual review is separately hash-bound.

Evidence: `artifacts/m5-hours-v14-broader-acceptance-v1/REPORT.md`, individual ledger,
replay, source/owner checks, coverage update and accounting receipts. The combined
two v14 screens contain 12 actual proposals/18 parts with development acceptance;
this is not an independent holdout, broad accuracy estimate or production approval.
The new screen has two exact exposed requests and four fresh compositions. Direct
AM/PM clarification remains acceptable; no live typed-unspecified example is claimed
or required by paid retries. Both direct visitor clarifications render generically;
the fixed Arabic presenter does not establish Jordanian style quality. Now uses
the frozen clock, not a tested production clock. Previous 253 focused/1,986 full
guarded test passes and exact code/source/cache bytes stay preserved without a
new full-suite run; no runtime/source/index/default change occurred.

The inspected integration gap is concrete: `HoursRagWorkflow` accepts
`hours_profile`, while `HoursChatService` neither exposes nor forwards it and
therefore constructs v12. Next is explicit trusted constructor selection for the
nonproduction service, retaining v12 default and unchanged public request schemas,
then offline FastAPI tests using saved actual v14 outputs. Preserve default API
unavailability, production refusal, per-question proof and the one-budget/no-retry
contract. No additional paid planner micro-screen is recommended first. This
integration is not implemented by the screen and does not authorize production
adoption, generated-answer acceptance, index publication or deployment.

The explicit nonproduction service option is now implemented and checked through
HTTP. Thirteen new integration checks cover old/default and selected profiles,
exact closed-schema selection, weekly source ownership, refusal of malformed v14
clock/query/doctor scope without retry, public profile-override rejection,
production/default API refusal and concurrent budget/profile isolation. Full
regressions pass **1,999 tests**, with lint/format (198 files) and the 65-package lock.

`artifacts/m5-hours-service-v14-integration-v1/actual-http-replay.json` records all
12 saved actual v14 decisions/18 parts through FastAPI, middleware, the service,
real catalog/Qwen/graph/provider adapter and presenter, using mocked HTTP with
socket/DNS guards. All emitted planner payloads match their original frozen wire
exactly; all projected responses match the earlier reviewed projections after only
opaque request/question ID renaming. Twenty question-owned source citations and
twelve isolated request budgets survive. All 42 historical hours packets reconstruct
exactly. Original semantic judgments remain inherited, not newly graded or inferred
from HTTP success. No model/provider metadata/embedding/Qdrant call, source/index
write or deployment occurred. Existing API schemas and v12 default remain intact.

This verifies opt-in hours HTTP integration, not ordinary retrieval/draft behavior,
new model reasoning or production acceptance. Generic clarification/style and
other earlier caveats remain. Next is offline full-path verification of mixed hours
and ordinary public website questions with development cases/cached evidence,
before separately bounded full-path model acceptance. Default chat/readiness and
production admission remain closed; no hours-only replay can satisfy those gates.
