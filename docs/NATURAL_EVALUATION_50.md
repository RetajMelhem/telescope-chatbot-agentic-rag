# Installed v0.1.0 evaluation: 50 approved questions

The user selected `install-mvp.ps1 -Version v0.1.0` as the evaluation target.
The evaluator sends real HTTP requests to that installed Docker API. It does not
construct a second host application or change the released image, prompts,
retrieval settings, corpus, ports, mounts or credentials. The user runs the
installer and configures its OpenRouter key; the evaluator never reads that key.

The [50 approved questions](NATURAL_QUESTIONS_50_DRAFT.md) are unchanged: 25
Jordanian Arabic / English pairs, including two exact-price questions. Preparation
is offline. The user confirmed installation and key setup on 2026-10-19;
see [current status](../PROJECT_STATUS.md) for the actual run result.

## Prepared package

The current package is `artifacts/natural-evaluation-50-v3/`:

- `requests.jsonl`: exact approved request bytes, without gold fields.
- `gold.json`: 50 minimum required fact groups, 470 exact witness quotations from
  299 distinct admitted chunks. Both authored sections have independent reviews.
- `ANSWER_KEY.md`: readable bilingual expected facts and review notes.
- `human-review-template.json`: null judgments; source support is judged from
  citations, with actual internal context explicitly unavailable.
- `plan.json`: frozen source/question/gold/code hashes, v0.1.0 image identities,
  transport and call limits. Earlier ASGI plans v1/v2 remain historical and are
  superseded; changed code or inputs require a new preparation directory.

The reviewed source is the saved v0.1.0 release: 107 documents / 955 chunks.
All 116 runtime file hashes/sizes and the prepared corpus digest are checked.
Witnesses are selected known positives, not exhaustive relevance judgments.
Gold is used only for offline scoring, never sent to the chatbot.

## Installation and readiness

Run the installer from the project checkout and provide the key through its
normal hidden prompt or supported local key configuration:

```powershell
.\install-mvp.ps1 -Version v0.1.0
```

Its default installation root is `%LOCALAPPDATA%\TelescopeRag`; default API
address is `http://127.0.0.1:8000`. If the installer uses a different port, the
runner reads that port from the validated installation record. Use `--install-root`
only when you deliberately installed to another directory. There is no arbitrary
remote URL option, host-runtime fallback, redirect following or environment proxy.

Before sending questions the runner checks the installation owner/state/release
records, exact API/Qdrant image identities, container ownership/configuration,
read-only data/secret mount locations, loopback API port and private Qdrant
network. It makes readiness/OpenAPI GET requests without inference. The API key
remains mounted inside the installed service. Health readiness does not establish
provider authentication, current provider balance or answer quality.

The runner rechecks installation/container identity after the run and binds the
before/HTTP/after receipts to case files and the execution index. Configuration
changes or incomplete installation verification cannot be scored as a verified
installed run. Completed/failed receipts are retained without automatic replay.
The runner never runs the installer, starts containers or writes a database.

## Commands

Use the locked environment from the repository root. On this workspace, `uv` is
available at `.tools/uv-runtime/bin/uv.exe`; `PYTHONPATH=src` resolves the local
package on this non-ASCII Windows path.

Preparation is offline and refuses to overwrite an existing package:

```powershell
uv run --locked python -m scripts.natural_evaluation prepare --output artifacts/NEW_PREPARATION
```

Once the user confirms the installation is ready, a read-only preflight can run
without sending any question or requiring `--execute`:

```powershell
uv run --locked python -m scripts.natural_evaluation preflight --plan artifacts/natural-evaluation-50-v3 --output artifacts/NEW_PREFLIGHT
```

An authorized evaluation uses a new output directory:

```powershell
uv run --locked python -m scripts.natural_evaluation run --plan artifacts/natural-evaluation-50-v3 --output artifacts/NEW_LIVE_RUN --execute
```

Limits are 50 serial requests, one HTTP attempt per question, no client retries,
no additional judge/model requests and no automatic fallback/resume. The unchanged
application permits at most two Luna calls and one Qwen batch per question, with
a 150-second application deadline; the client timeout is 155 seconds. Non-200,
timeout, invalid response or unknown dispatch outcome stops further questions.
These call limits are not a hard USD cap. Provider spending is governed by the
key configured through the installer; the evaluator cannot inspect its balance.

After a stopped run, an explicitly authorized continuation can collect only its
unsent suffix. On 2026-10-19 the user chose to complete all remaining questions
before fixing any problems. The separate helper preserves the original failed
case, attempts each remaining question once, and records per-case errors while
continuing. Runtime/configuration drift or a failure to preserve receipts stops
the continuation. It checks the original run with the strict scorer before any
request, pins its own code hash and parent hashes, and verifies the same installed
runtime. It never edits the original run or the sealed evaluation modules.

```powershell
uv run --locked python -m scripts.continue_installed_evaluation --plan artifacts/natural-evaluation-50-v3 --parent-run artifacts/natural-evaluation-50-installed-run-v1 --output artifacts/NEW_CONTINUATION --execute
```

Its `combined/` directory assembles the exact original case bytes and the new
suffix, with provenance and both batches' receipts. This is the original cohort
observed in two authorized batches, not 50 new requests. Score that combined
directory with the ordinary offline scorer. The helper's own hash is separately
bound in continuation provenance; the original sealed module hashes stay intact.

Score completed receipts offline, then fill the resulting case-bound review
against the answer key, returned answer and cited source text:

```powershell
uv run --locked python -m scripts.natural_evaluation score --plan artifacts/natural-evaluation-50-v3 --run artifacts/NEW_LIVE_RUN --output artifacts/NEW_SCORE
```

For each factual claim record its text, `correct` and
`supported_by_cited_sources` booleans. Complete every required-fact, citation,
language, prohibited-claim and missing-information judgment, and mark the claim
inventory complete. Equivalent wording is accepted. An honestly reviewed
abstention on an answerable question scores fact recall zero, not unreviewed.
Re-score into another new directory with `--review PATH_TO_FILLED_REVIEW`.

## What this installation exposes

| Metric | Available measurement |
| --- | --- |
| Answer fact recall | Correct required facts included / required facts, judged against the frozen key. |
| Claim correctness and source support | Correct factual claims / all claims; claims supported by cited sources / all claims. Requires complete human claim inventory. |
| Citation validity and entailment | Literal source/quote/owner/question checks, plus human review of whether the cited passage supports the claim. |
| Complete-question success | Required facts covered, correct source-supported claims, correct citations/language, no prohibited claims and all question parts handled. |
| Missing-information handling | U25 in each language acknowledges missing exact price without inventing an amount. Price-estimate context is optional, not evidence of an amount. |
| Cited-witness coverage | Required known evidence groups represented among returned citations. This is not retrieval recall. |
| Response latency and failures | Client wall-clock time for real HTTP requests, median/p95, HTTP errors and timeouts. This includes the installed API path; it is a serial cohort, not a load test. |
| Retrieval recall/precision and writer-context coverage | Unavailable: the unchanged v0.1.0 API does not return internal candidates or writer prompts. Null, never inferred from citations. |
| Actual-context faithfulness, provider tokens and cost | Unavailable through this response schema. Citation-supported correctness is distinct from proof of actual model exposure. Missing values are not zero. |

Report by language and overall with reviewed/scored denominators. HTTP failures
and unattempted questions after a stop remain in the requested run's denominator;
label the stopped cohort explicitly. The two price cases have no positive amount
facts, so exact-amount recall is null. Full staff listings require completeness
review against the roster. These visible, authored questions represent 25 paired
intents, not 50 independent observations or production acceptance.

The older in-process capture code remains an offline diagnostic helper. It is
not the selected execution path, and its trace metrics must not be mixed with
installed HTTP observations.

The completed baseline is preserved at checkpoint `92b6652`. After application
changes, its v3 code seal must be verified against that historical checkout rather
than overwritten. [Targeted diagnosis and candidate results](NATURAL_EVALUATION_FIXES.md)
retain separate code/image/response bindings and do not replace the original run.

## Verification

Tests use synthetic installation files, mocked Docker/HTTP responses and fake
services. They cover exact release/configuration binding, no credential access,
real-client request formatting, stop-on-failure, unavailable trace metrics,
source/case/citation ownership, changed receipt rejection and completed human
judgments. Current test results are recorded in [project status](../PROJECT_STATUS.md).

An offline AI source review can fill the same rubric as a provisional assessment.
Label its reviewer and review kind explicitly, preserve claim-level judgments,
and report its scores as provisional AI-reviewed results. Such a review is not
independent human validation, even though the scorer retains its historical
`human` field names. No additional provider judge is called by this runner.
