# Source-bound public hours and pure calculations

`knowledge/hours.py` defines closed reviewed-hours records and typed time inputs.
`PublicHoursCatalog` in `knowledge/time_calculations.py` binds a supplied plan to
an exact evidence catalog and calculates against published intervals. It has no
question parser, provider, database client, source fetch, persistence or default
data loading. This completes the offline data/math layer, not graph time answers.

## Reviewed source candidate

The complete hours paragraphs and governing question/section context in the
[English FAQ](https://telescopecenter.com/faqs/) and
[Arabic FAQ](https://telescopecenter.com/ar/faqs/) were read individually. Their
accessible official-page text agrees with the retained snapshot. No raw snapshot
or its fetch timestamps were refreshed or replaced.

| Literal owner claim | Separate normalized interpretation for each language |
| --- | --- |
| Main center | Daily 09:00 to the ending midnight; Friday 14:00 to the ending midnight. |
| Optical center | The explicit same-hours relationship includes the main-center intervals and Friday exception. |
| Pharmacy | Its own 24/7 claim produces 00:00 to ending midnight on all seven weekdays. |

These are six independent owner/language records, with 42 weekday rows. English
and Arabic claims remain separate source records; there is no translation merge.
Their agreement is assessed at calculation time. Opening offsets use minutes
from the named day's midnight; 1440 is its ending midnight. The Arabic typo and
the full advance-booking recommendation remain untouched in the source proof.
Booking is recommended in that paragraph, not asserted to be a prerequisite for
opening; this establishes no appointment availability or actual attendance.

No doctor schedule, holiday exception or effective-date range is established by
these paragraphs. Missing doctor records remain unknown; that is not a claim
that every website page was rereviewed or contains no doctor hours. `Asia/Amman`
is the specified application timezone, separately identified as policy rather
than an invented source quotation.

The ignored `artifacts/m5-public-hours-v1` directory contains the immutable
`reviewed-hours-plan.json`, six authored semantic decisions, exact source
passages/offsets, complete source proofs and actual-bundle calculations. Its plan
digest is `609a93a48f86b802c3ab2356a128fbc3b8736079dfd241b5ffa1572f1a5e59f7`.
Ten original DOM spans were checked against saved HTML. Codex made the six
language/owner interpretations; scripts materialize those explicit values and
track bindings. No independent subagent was invoked, and this is not a new
semantic audit of all 955 chunks. Original source approval remains unchanged.

## Binding and calculation contract

Trusted construction supplies a `PublicHoursPlan`, expected plan digest, exact
`EvidenceCatalog` and explicit maximum source age. The constructor revalidates
all records, the prepared digest/snapshot and full source-chunk hashes. Doctor
IDs must match the declared literal/canonical ownership; generic facility hours
cannot inherit doctor-owned sources. Sources with diagnostic codes are refused. Hash
checks authenticate a mapping's bytes; they cannot prove that prose entails it.
The trusted caller must authenticate review authority before supplying a plan.

`HoursQuery` accepts an exact typed subject and one of: server `now`, an aware
instant, or a local date/hour/minute with an explicit clock basis. No relative
date/name resolution, booking/private operation or arbitrary text is accepted.
The caller supplies an aware server clock; model-generated time is not a clock.
Missing identity/date asks for clarification. A missing schedule stays unknown.

Intervals use `open <= instant < close`, preserving split shifts, lunch gaps and
explicit overnight carry. A reviewed dated rule replaces its calendar date,
including previous weekly spillover. Admitting that rule requires explicit
source support for that scope; no holiday calendar supplies exceptions. A
weekly closed-day claim conflicting with a published overnight carry remains
unknown. Missing days are never filled with closed intervals. Source conditions,
effective bounds, future fetches, stale sources and unsupported historical
extrapolation remain explicit. The caller uses the existing configured freshness
policy; this adds no token, credit or provider budget guard.

An unspecified 1–12 hour is evaluated as both AM and PM. Different outcomes ask
for clarification; identical outcomes retain both candidate instants and an
ambiguity flag. Friday noon and midnight, for example, are both outside the
reviewed main-center hours, so that ambiguity need not change the hours outcome.
Historical timezone gaps/folds are not silently shifted; ambiguous/nonexistent
local input asks for clarification, and unresolved interval boundaries stay
unknown. Comparisons use UTC instants after explicit local-zone conversion.

Separate source records are never voted away. A conflict or unusable relevant
record prevents a definitive aggregate result. Each per-record/per-instant
decision and complete original chunk proof remains available. Results say
`within_posted_hours` or `outside_posted_hours`, with explicit weekly/dated scope;
they do not assert actual opening, attendance or availability. Interpretation
verification remains false until a later request-to-operation contract is proven.

## Verification and next step

**1,822 guarded offline tests pass**, including **89 new checks** and a 10,080
minute weekly grid. Tests cover opening/closing/midnight, split/overnight shifts,
dated overrides, missing/conflicting/stale/conditional/historical evidence,
AM/PM/noon, timezone gaps/folds, typed input refusal, exact digest/owner checks,
separate same-field doctors and canonical identities. Twelve source-bound checks
also run on the actual immutable 107-document/955-chunk bundle. An initial test
incorrectly expected Friday noon-versus-midnight to change the result; its receipt
is preserved, and the corrected oracle retains ambiguity with the same outcome.

Ruff lint/format, lockfile, document links, historical replay and source/cache/
staging checks are recorded in the evidence directory. There were three official
page read/find operations across two URLs, no paid/provider metadata/inference,
embedding, Qdrant, source/index write, deployment or subagent request. New API
spend is $0; the last $1.1424752 allowance observation remains unrefreshed.

Next: prepare an explicit, source/owner-bound graph time-operation input contract
that preserves original date/time/negation/reference text, then wire these results
without another model stage or heuristic parser. The current planner has no typed
date/time fields; `time_comparison` therefore still returns
`unknown / operation_unavailable`. Existing prompts/payloads, graph, response
formats, readiness and default 503 behavior are unchanged. Planner/source/model
acceptance, directory completion, publication and deployment remain pending.
