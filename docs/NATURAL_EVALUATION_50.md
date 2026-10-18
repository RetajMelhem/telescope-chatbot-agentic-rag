# Approved 50-question evaluation

The user approved the [25 Jordanian Arabic / English pairs](NATURAL_QUESTIONS_50_DRAFT.md)
on 2026-10-18, including the two price questions. Preparation is complete offline;
no evaluation requests, embeddings, database operations or paid model calls ran.
The user will supply/configure the API key when it is needed.

## Prepared inputs

The current local package is `artifacts/natural-evaluation-50-v2/`:

- `requests.jsonl`: the unchanged 50 approved requests; no gold fields.
- `gold.json`: 50 minimum required fact groups shared across the 25 intents,
  with 470 exact positive witness quotations from 299 distinct admitted chunks.
- `ANSWER_KEY.md`: readable bilingual expected facts, response notes and prohibited claims.
- `human-review-template.json`: unfilled source-review judgments, never automatic passes.
- `plan.json`: hashes for requests/gold/source/serving code/evaluation code,
  model-call limits and honest cost/prerequisite limitations.
- `PREPARATION_VERIFICATION.json`: source/file/count/hash checks and missing runtime resources.

Two sibling agents independently reviewed each other's authored gold against the
actual saved sources. A required doctor-assessment sentence was removed from the
PRK/LASIK comparison; optional detail is not a completeness requirement. A typical
visit answer such as “Usually around 20–40 minutes” is sufficient. Exact wording
is not required. Detailed gold and all source quotes stay outside Git and serving
knowledge. The earlier unexecuted `natural-evaluation-50-v1` package is superseded
because the evaluation capture code changed during offline verification.

The source is the public v0.1.0 knowledge release, not a refreshed website. All
116 runtime file hashes/sizes and the prepared digest were checked against the
107-document / 955-chunk bundle. Expected facts were written before seeing any
bot response. Witnesses are selected known positives, not an exhaustive set of
all relevant source occurrences; valid unlisted evidence needs adjudication.

## Runner and live prerequisites

`scripts/natural_evaluation.py` has separate `prepare`, `run` and `score` modes.
Preparation and scoring do not create network clients or read credentials. The
live mode requires `--execute`, the sealed plan directory, an explicit runtime
root and a new output directory. It uses `create_local_app` and the actual
`POST /api/v1/chat` route through an in-process ASGI HTTP client. Serving code,
prompts, model choices, corpus and retrieval settings are unchanged.

The API input supports `ar`, not `ar-JO`; the runner sends `ar` while preserving
the approved Jordanian question and the `ar-JO` label in evaluation receipts.

The selected host runtime needs its reviewed source/tokenizer/hour/link files,
project `.env` OpenRouter key, `.tools/qdrant-m3/read.key`, and the existing
compatible read-only Qdrant collection at localhost. This clone currently lacks
those serving-root files and credentials. Its downloaded inspection bundle is
kept separately under ignored artifacts. Docker CLI presence alone does not prove
Docker/Qdrant readiness. The runner never installs, starts, restores or writes a
database and does not substitute a different retrieval implementation.

Check current provider route/pricing/allowance and the spend boundary before an
authorized live run. Limits are 50 serial requests, one HTTP attempt each, at most
100 Luna calls and 50 Qwen query batches, no retries/fallbacks or judge calls.
Normal per-question application limits remain two Luna calls, one embedding batch,
150 seconds and the existing evidence/output ceilings. The outer client timeout
is 155 seconds. The runner stops at the first non-200/unknown dispatch failure,
preserves completed receipts and does not automatically repeat or resume.

These call/deadline limits are **not a hard dollar cap**. An estimate is not yet
available because planner-selected query/context lengths and current pricing are
not known. A provider-side key limit is needed for a hard spending boundary;
missing costs/usages remain unknown. Do not claim the run is affordable or paid
execution-ready from the offline checks.

## Commands

Run from the repository root with the locked environment and `PYTHONPATH=src`.
Use `uv` on PATH, or this workspace's `.tools/uv-runtime/bin/uv.exe`.

Preparation refuses an existing directory; use a new version after changing code
or approved inputs. It needs the separately stored authored gold and independent
reviews under the source-inspection directory.

```powershell
uv run --locked python -m scripts.natural_evaluation prepare --output artifacts/NEW_PREPARATION
```

The following is a later explicitly authorized live action, not part of preparing
or opening these files. `RUNTIME_ROOT` must identify the prepared project runtime.

```powershell
uv run --locked python -m scripts.natural_evaluation run --plan artifacts/natural-evaluation-50-v2 --runtime-root RUNTIME_ROOT --output artifacts/NEW_LIVE_RUN --execute
```

After every attempted case is saved, offline scoring creates candidate/context
coverage and a case-bound human-review template. It does not invent semantic
answer judgments or use another model:

```powershell
uv run --locked python -m scripts.natural_evaluation score --plan artifacts/natural-evaluation-50-v2 --run artifacts/NEW_LIVE_RUN --output artifacts/NEW_SCORE
```

Fill the new score directory's human-review template against the answer key,
actual response and actual writer context. For every factual claim, record its
text, `correct` and `supported_by_context` booleans. Mark the complete claim
inventory explicitly, every required fact and each response/citation/language
judgment. An honest unsupported answer on an answerable question is a reviewed
failure with fact recall zero; it does not remain unreviewed. Then repeat offline
scoring into another new directory with `--review PATH_TO_FILLED_REVIEW`.

## Metrics and interpretation

| Metric | Definition and limit |
| --- | --- |
| Candidate witness recall at 5/10 per search part | Required known evidence groups found in the union of each search part's first k merged candidates, divided by required groups. This is not one global ranking or dense-only recall. |
| Dense witness coverage | Request-level group coverage at actual dense query limits, normally five per query. Dense calls have no authenticated part association; do not relabel them dense recall@10/20. |
| Writer-eligible coverage | Required witness groups among IDs actually offered in the writer's prompt, including validated hours evidence where applicable. Provenance-only duplicates do not count as model exposure. No writer means zero positive-fact exposure; price-amount coverage stays null. |
| Retrieval precision | Requires human relevance labels for every distinct candidate being measured. Unlisted/unjudged witnesses are not automatically irrelevant. The recorded fraction concerns the unique top-k-per-part candidate union, not fixed-denominator TREC precision@k. |
| Answer fact recall | Required facts correctly included, divided by required facts, from a completed source review. Equivalent wording is accepted. |
| Answer claim precision / faithfulness | Correct claims / all factual claims, and claims supported by actual supplied evidence / all factual claims. A complete claim inventory is required; no factual claims gives a null precision rather than a perfect score. |
| Citations | Automated ID/URL/owner/quote/question checks are separate from human semantic entailment. One part cannot borrow another part's citation. |
| Complete-question success | Correct HTTP response, required facts covered, claims correct and grounded, all parts accounted for, correct language, correct citations and no prohibited claims. HTTP failures/unattempted cases after a stop remain in the requested run's denominator. |
| Missing-information handling | U25-ar-JO/U25-en acknowledge missing exact price without inventing an amount. Estimate-after-consultation text is optional context, never positive amount support. Exact-amount retrieval recall is null. |
| Latency / usage / cost | Median and nearest-rank p95 ASGI application HTTP time, separately reported actual usage and existing-response `usage.cost` when available. Reserved token ceilings are never reported as actual usage. Missing costs are not zero. |

Report overall and by language with scored/reviewed denominators. Search recall
is null for complete-source/hours-only paths; final-context and answer judgments
still apply. Directory questions require full roster review, not one top-k hit.
This is a small, visible set of authored everyday questions: 50 requests represent
25 paired intents. It is not unseen statistical acceptance, load testing, deployed
network/container latency, clinical validation or proof of production readiness.

## Verification

Meaningful offline cases cover request-only payloads/dialect mapping, OR witnesses
versus AND groups, source ownership, provenance versus writer exposure, missing
price/usage/cost, unjudged candidates, completed abstentions, cross-question
citations, swapped/tampered receipts, no duplicate dispatch, stop-on-failure,
transparent tracing and bounded cost capture. The full guarded test suite and
Ruff checks are recorded in current [project status](../PROJECT_STATUS.md).
