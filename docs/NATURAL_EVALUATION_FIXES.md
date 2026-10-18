# Targeted baseline diagnosis and candidate verification

On 2026-10-19 the user authorized diagnosing the seven baseline problem cases,
fixing the observed causes, and rerunning those exact questions. No subagents
were used for this phase. The original 50-case baseline and installed v0.1.0
service remain intact.

## Observed causes and changes

The unchanged-image diagnostic replay reproduced incomplete doctor lists. The
planner chose ordinary ranked search, sometimes with a generic reporting purpose.
The writer received only a subset of the primary directory: four doctors for the
English team request and six eligible ophthalmologists for the English eye-doctor
request. A top-K candidate pool cannot establish an exhaustive roster.

Local planner v12 directs roster questions to the existing `read_source` operation,
using the issued primary directory, doctor records and available source language.
Writer v12 includes every matching person concisely and filters specialty subsets
by explicit roles, preserving the anesthesiologist's distinct role. No names,
benchmark IDs, expected answers, runtime query classifier or additional model
calls were added. The real complete directory fits the existing 6,000-token
budget: 3,573 English / 3,859 Arabic tokens, with 11 groups each.

The English clinics replay retrieved amenities and unrelated topics, with no
support for the requested specialties. The writer's abstention was appropriate
for that evidence. Planner v12 makes clinical-department meaning explicit in a
faithful search paraphrase, without presuming which specialties exist. It retains
the ordinary facility/amenity meaning when that is what the visitor asks.

The three original HTTP 502 errors expose only `offline_draft_failed`. Each passed
twice in unchanged-image diagnostic replays. Their exact historical causes remain
**unconfirmed**. Closed, content-free warning logs now retain request ID, workflow
failure code, stage and provider outcome. Unknown labels become `unknown`; request
text, sources, credentials, headers and upstream exception bodies are excluded.
The public error response, strict validation and no-retry behavior are unchanged.
This improves diagnosis if failures recur; it is not proof those intermittent
errors have been permanently fixed.

## Actual targeted rerun

The seven exact problem questions ran once over real HTTP against the candidate:

| Case | Baseline | Candidate |
| --- | --- | --- |
| U06-ar-JO | 6/11 staff | 11/11 |
| U06-en | 4/11 staff | 11/11 |
| U10-ar-JO | HTTP 502 | Supported parking answer, HTTP 200 |
| U15-ar-JO | HTTP 502 | 8/8 eye doctors, HTTP 200 |
| U15-en | 6/8 eye doctors | 8/8 |
| U19-en | HTTP 502 | Supported cataract answer, HTTP 200 |
| U24-en | Unnecessary abstention | All three specialty categories |

All seven passed provisional AI source review, delivering 43/43 required facts.
Source/citation identities and quotations validate against the unchanged gold and
admitted source bundle. Full-source directory provenance remains separate from
the matching people named in prose. Median/p95 HTTP latency: 10.11 / 12.89 seconds.
This is a targeted set of long lists and prior failures, not a second full-50
evaluation, independent human acceptance or a controlled causal proof for the 502s.

The candidate is available at **http://127.0.0.1:8001/**; installed v0.1.0 remains
at **http://127.0.0.1:8000/**. It uses the same container factory/command, reviewed
data, read-only private database, mounted credentials, dependencies and model/call
limits. All 99 Python package files match the candidate checkout. Only application
code and the candidate loopback port differ. No installer state, existing container,
database, public release/tag or remote repository was replaced.

Artifacts stay ignored under `artifacts/natural-evaluation-fixes-candidate-r1/`:
`REPORT.md`, `RESPONSES.md`, `diagnosis-each-case.json`, image/source identity and
before/after receipts, plus exact HTTP responses, case-bound provisional review,
scores and comparison hashes in `rerun-v1/`. Unchanged-image diagnostic replays are
separate in `artifacts/natural-evaluation-fixes-diagnostic-v1/` and `-v2/`; those
in-process observations are not deployed HTTP latency measurements.

Verification: 2,415 full guarded offline tests passed, followed by nine focused
logging/diagnostic-selection checks; Ruff lint/format and local links pass. The v3
baseline plan remains sealed to its historical code at checkpoint `92b6652`.
Application changes intentionally invalidate its current-checkout code comparison;
do not edit that old seal. Historical code hashes were checked from Git before
starting the candidate. Candidate code/image bindings are separate.

Use the candidate for local review. If a 502 recurs, use its request-correlated
safe failure event to identify the failing stage before changing validation or
adding retry behavior. Distribution through the installer requires a separate
versioned release; no publication is part of this verification.

## Remaining 502 investigation

On 2026-10-19, a separate diagnostic HTTP listener repeated only U10-ar-JO,
U15-ar-JO and U19-en ten times each. **All 30 returned HTTP 200** and reached
`draft_ready`; all 90 provider attempts succeeded, with no retries. The three
original request IDs have no diagnostic details in the original container logs.
**No root cause was identified or fixed.** Successful repeated samples cannot
establish why the earlier failures occurred. HTTP success here is not a new
answer-completeness score.

The diagnostic image extends the original v0.1.0 image with an explicit probe
factory and observer. All 99 product Python files match historical Git after LF
normalization. It preserves settings, models, call budgets, source and read-only
database access; only the exact three configured request payloads are accepted,
with empty history and a 30-request cap. Each response and local trace was saved.
The loopback probe was stopped after completing the cap. Before/after preflight
receipts confirm the original installation is unchanged. All 116 source files,
955 chunks and sealed question/gold/plan hashes still verify.

The completed probe revision buffered chat bodies and forwarded status and
content-type, rather than every upstream response header. No failing, malformed
or oversized response occurred in that run. The checked-in diagnostic helper
now observes the original stream without replacing response identity, chunks or
headers; nine offline tests cover scope/cap enforcement, failure preservation,
header/vector exclusions, malformed/oversized bodies and stream exceptions. This
observer revision was not substituted into the completed run. These are temporary,
caller-owned diagnostics, not default product logging or a new public debug API.

`artifacts/remaining-502-investigation-v1/` contains `REPORT.md`, `RESPONSES.md`,
the raw `trials/` and `captures/`, `trial-index.json` hash bindings, image/source
identity, original-log check and `FINAL_VERIFICATION.json`. Full guarded offline
verification: **2,428 tests pass**, with Ruff lint/format passing. No subagents,
speculative application change, release, tag, installer modification or push ran.

The three errors remain **unconfirmed**. R1's existing content-free
`chat_workflow_failed` event can identify the stage/code/provider outcome of an
actual recurrence. Use that specific failure for an offline reproduction and
targeted correction before claiming a cause was fixed.
