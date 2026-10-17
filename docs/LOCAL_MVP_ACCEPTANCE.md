# Local MVP acceptance, 2026-10-18

The explicit local application is usable at `http://127.0.0.1:8000/`. Start it with
`run-local.ps1`; see the [runbook](LOCAL_MVP.md). This is acceptance of a bounded
local development delivery, not a production release or a global accuracy claim.

## What was delivered

- An explicit local factory composes the reviewed 107-document / 955-chunk bundle,
  pinned hours/tokenizer/source policy, existing read-only Qdrant reader, Qwen query
  embeddings and the two-stage Luna/LangGraph flow. The original default app stays
  unavailable; the local selection is deliberate and requires local resources.
- A browser question interface and a typed local API response preserve excerpts,
  question-owned citations, timestamps, owners, exclusions and unresolved parts.
  Static output uses text nodes, with official HTTPS citation links only.
- Startup and readiness validate the pinned local collection without inference.
  Failed startup and shutdown close clients. The launcher binds to loopback and
  can start the existing Qdrant containers; no index, alias or corpus is rewritten.

## Live evidence and repairs

Primary Codex individually read **23 completed live requests / 44 actual parts**
against their cited saved official website evidence. Scripts tracked coverage and
exact source correspondence; they did not make semantic judgments. One interrupted
diagnostic request has no complete result/usage receipt and is not counted as a pass.
No subagent or external model judge was used.

| Observed failure | Local repair | Actual verification |
| --- | --- | --- |
| English visitor questions were restricted to guessed pages, excluding the FAQ | Ordinary general searches stay unfiltered unless the user requests a source restriction | English preparation/duration answers recovered; explicit cataract-page restrictions retained |
| Arabic visit duration was assigned a procedure-specific evidence policy despite the right FAQ ranking first | Select the policy by the relationship requested, preserving administrative/visitor questions as general reporting | Targeted Arabic case now includes both preparation and qualified duration; fresh English paraphrase also succeeds |
| One Arabic single-profile request silently chose the informative page from several possibilities | Ask for a page choice when the intended single profile remains ambiguous | English, Arabic and Jordanian profile cases now offer distinct admitted URLs without merging owners |

The 12-request development cohort has 27 actual parts. Its two remaining failures
were fixed and rerun individually. The **final prompt has nine actual requests /
12 individually reviewed parts**, all adequate within their tested source scope:
five audited targeted runs plus four actual localhost HTTP requests. This is not
a whole-cohort rerun under the final prompt, an independent holdout, or proof of
general model reliability. Exact actual proposals, drafts and final replies remain
in the ignored evidence directories below, including failures.

The real HTTP checks cover English and Jordanian opening hours, a fresh visitor
duration paraphrase, and private-record/booking/key-disclosure injection. Public
facts receive source support; excluded requests perform no private action or secret
disclosure. Earlier mixed English/Arabic/Jordanian checks preserve Friday/date/time,
payments and excluded booking separately. Cataract answers preserve usual duration
and lens-dependent glasses qualifiers; an absent total price remains unknown.

All **33 citation occurrences** match their admitted chunk, URL and owner. **68
original DOM spans across 13 cited chunks / five saved official pages** verify
exactly. One additional Rihab page witness from a failed source-selection case was
checked directly against its original HTML. This verifies the cited evidence; it
does not constitute a new full-corpus or removed-content semantic audit.

## Offline and packaging checks

The full guarded suite passes: **2,115 tests**, including seven new local runtime
cases. They cover bilingual hours transport/provenance, invalid request overrides,
no inference during startup/health, failed index startup and cleanup, read-only
credential selection, and production rejection. Existing tests retain evidence,
hours, provider, ambiguity and private-boundary coverage. Ruff lint/format, locked
dependencies and wheel construction pass. The wheel includes the HTML page and
excludes credentials, environment files and collected data.

Browser automation reports that local browser use is disabled in Work settings.
The page is served and its API works; visual rendering/click testing was not
performed and is not claimed.

## Cost and evidence locations

The project key reported $0.642832270 before this work and $0.538826785 afterward:
a **$0.104005485 usage increase over the work window**. Forty-six fully audited
provider responses (33 chat, 13 embedding) report $0.086427705. Four real HTTP smoke
requests lacked payload auditing, and one interrupted diagnostic lacks complete
usage. Aggregate key change is not independent per-request billing reconciliation.
There were no automatic retries, fallbacks, corpus embeddings or index writes.

Evidence is retained locally, excluded from Git:

- `artifacts/local-mvp-v1/`: preflight, original diagnostic traces, source checks,
  individual semantic review, accounting, tests and verification scripts.
- `artifacts/local-mvp-v2/`: 12 actual development requests, including preserved failures.
- `artifacts/local-mvp-v3/`: five final-prompt targeted runs.
- `artifacts/local-mvp-http-v1/`: four real HTTP checks and readiness response.

## Remaining limits and next action

Answers are literal excerpts; a source may differ in language from the question.
Polished narrative generation, perfect recall, broad independent acceptance and
universal question interpretation remain unproven. The browser uses independent
questions, and this installation depends on excluded local source/tokenizer/secret
files. Production serving, portable API Docker packaging, live source refresh and
website integration are separate work.

Next, use the running local MVP and record concrete failing questions for focused
repairs. This local delivery does not require another preparatory audit milestone.
