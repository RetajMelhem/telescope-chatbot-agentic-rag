# Evaluation and acceptance

Status: API/provider/ingestion and comparison contracts have offline tests. A source-bound, independently reviewed 90-case benchmark is frozen for v6; its initial dense/BM25/hybrid retrieval comparison has executed. Dense is retained provisionally under the frozen rule. Source-policy enforcement, generated answers and deployment acceptance remain unverified. Current results are recorded in [PROJECT_STATUS.md](../PROJECT_STATUS.md).

## Offline checks first

Unit tests use synthetic/source fixtures and verify pure behavior. Integration tests use mocked OpenRouter responses and a fake retrieval adapter unless a local database check is explicitly being exercised. No provider requests are implicit in `pytest` or the existence of an API key.

M1 tests use synthetic settings and fake knowledge probes, never the user's `.env`. External socket connections are blocked; loopback/Unix sockets remain available for event-loop internals on Windows and other platforms. No live local service is used by the test suite. The current tests cover configuration, startup/lifecycle, bounded shutdown, health readiness, chat schema rejection, bilingual input transport, body limits, deadlines, CORS including early/error responses, method-rejection headers, diagnostic exposure, and safe error/log behavior. They do not verify Arabic understanding or RAG answer quality.

## Required case families

| Family | Cases and expected result |
| --- | --- |
| Language | Equivalent English, Arabic, Jordanian Arabic, and code-switched questions retain meaning and source ownership. |
| Doctor identity | Exact profile, ambiguous short name, similar names, and an unknown doctor; ambiguity stays unresolved. |
| Specialty and technique | Supported doctor-specific claim, clinic-wide service only, and absent attribution; do not promote a generic service into a doctor's specialty. |
| Decomposition | Simple, compound, dependent, negative, comparative, and over-limit requests; account for every original part. |
| Conversation | Clear pronoun, ambiguous pronoun, fabricated history, and stale prior answers; only current evidence establishes facts. |
| Listings | Complete directory manifest and incomplete crawl/top-k hits; only verified coverage supports an exhaustive listing. |
| Cleaning/formatting | Navigation removal without deleting footer hours/contact facts; HTML entities, Unicode/Arabic text, lists, table labels/footnotes, original-source mappings, and retained qualifiers. |
| Structural chunking | Adjacent doctors stay separate; question/answer pairs retain their question; list ordering and table header relationships survive; small units are not padded; overflow preserves ownership/context or records a gap. |
| Hours | Before opening, exact opening, exact closing, split shifts, overnight intervals, Friday, missing hours, explicit closure, date exceptions, stale hours, and ambiguous AM/PM. |
| Public/private schedule boundary | Posted doctor working hours can be answered; availability, private calendars, actual attendance, and booking requests remain excluded. |
| Mixed scope | Supported specialty plus record/booking request; answer the public part and retain the excluded part. |
| Missing/conflicting evidence | Empty results, mismatched evidence, conflicting pages, extraction gaps, crawl limits; uncertainty is explicit. |
| Citations | Unknown source ID, fabricated URL, wrong doctor source, source not passed to generation, and fabricated quotation; structural validation rejects invalid references. |
| Injection | User or page text demands ignoring instructions, exposing keys, fetching an external URL, or reading records; no new permissions or actions result. |
| Provider protocol | Invalid JSON, unsupported schema response, reordered embedding indexes, vector mismatch, 429, 5xx, timeout, and partial batch failure; bounded safe failure. |
| Budget | Long Arabic input, oversized history/evidence, exhausted token reservation, retry exhaustion, and deadline cancellation; no silent loss of original meaning. |
| Operations | Missing index readiness, incompatible collection, denied API writes, atomic snapshot switch, restart persistence, and rollback. |

## Source-based evaluation corpus

After ingestion, create a small versioned bilingual set covering every core family rather than relying on a large count of similar questions. Include known-answer positives, deliberately unanswerable questions, mixed questions, and source attribution traps. Mark synthetic hours and doctor examples explicitly so they cannot enter real clinic knowledge.

Each fixture stores the original query, language, any history, pinned snapshot, expected outcome, expected supporting source spans, required request parts, and prohibited claims. A fluent answer is not a pass if the source does not support it.

### Frozen source benchmark v1

The current local benchmark is [artifacts/m3-retrieval-benchmark-v1/manifest.json](../artifacts/m3-retrieval-benchmark-v1/manifest.json). It contains 30 intents, each in English, Arabic and everyday Jordanian Arabic: 90 individually authored and independently reviewed cases. All cases bind to v6 prepared digest `a46be2d3fd18f11d46c79ff9bc992de22aab496836894a708bc57c1e8b48af88`; the benchmark canonical content hash is `e753d931c558c29a74ccfd18c0921efc4dd943b04c8a972267643943458be84b`. Manifest SHA-256 is `ee9ace13c784f6c8182ec9f9db4cf76fdc39dc24dc82ba9ad62c8c1b18dbd499`.

Gold cases, exact source witnesses, approved-alias authority, per-part supported/unknown/clarification/excluded outcomes, prohibited inferences/actions and hash-bound independent review records remain separate from `requests.jsonl`. Requests contain only case ID, language, query and synthetic history. Do not pass gold answers, chunk IDs, tags, expected outcomes or review rationales into planning/retrieval/answer prompts. These files are evaluation artifacts, never admitted clinic knowledge.

The split has 18 development and 72 evaluation cases. All three language variants of an intent stay together. Evaluation cases are visible local fixtures, not a secret or statistically independent production holdout. Do not tune retrieval to the evaluation cases or add case-specific runtime behavior. Preserve original failed drafts and repair reviews as evidence; future fixture changes use a new version and new review hashes.

Run the read-only verifier from the repository root:

```powershell
& .\.tools\uv\bin\uv.exe run --locked python -m scripts.check_frozen_benchmark --benchmark artifacts/m3-retrieval-benchmark-v1 --manifest-sha256 ee9ace13c784f6c8182ec9f9db4cf76fdc39dc24dc82ba9ad62c8c1b18dbd499
```

The verifier checks frozen file inventory/hashes, actual corpus digest, source-policy/configuration/manifest bindings, every exact source quote, all 90 independent case reviews, requests without gold fields, witness payloads and split integrity. It does not make semantic judgments, execute retrieval or establish readiness. The offline freezer is `scripts/freeze_retrieval_benchmark.py`; it refuses an existing output directory. Collected source quotes and generated evaluation files remain ignored by Git/Docker.

For later authorized runs, evaluate known answer-support witness-group recall at `k=5,10,20`, separately from uncertainty/clarification-context recall. All groups are AND requirements; alternatives inside a group are explicit OR choices. Cases without a role's evidence groups have a null metric. A relevant generic FAQ or free-consultation advertisement is not support for an unresolved specific claim. The gold witnesses are selected known positives, not an exhaustive inventory of every valid source; manually adjudicate valid unlisted alternatives before revising fixtures. Exact duplicate occurrences retain their own provenance and are not silently made interchangeable.

`score_receipts` in `scripts/retrieval_benchmark.py` scores only supplied ranked receipts and never issues retrieval/model/database calls. Call it only after verifying the frozen benchmark and actual source bundle; direct use of its in-memory arguments is not corpus attestation. Synthetic contract-test receipts must remain labeled synthetic and cannot be mixed with real retrieval receipts. No real scores are recorded in the frozen v1 preparation artifact.

The 11-owner directory question must be reported separately from small top-k passage retrieval: five retrieved chunks cannot satisfy eleven distinct directory-owner witnesses. Conversation cases require the future context-aware planner; embedding an isolated pronoun is not an end-to-end conversation evaluation. Compare chunking strategies with identical source selections, query handling, provider/configuration and budgets. Any fixed-window baseline stays isolated from the serving policy.

After an actual run, a source reviewer must assess every request part for supported facts/qualifiers/negations, correct ownership/citation, partial/unknown outcomes and prohibited actions. `answer-review-template.json` starts with null judgments. Retrieval recall does not measure answer faithfulness, citation entailment, diagnosis safety or runtime enforcement of source issue codes. No second paid judge-model call is authorized by this benchmark.

Keep evaluation fixtures separate from live knowledge and prompts. Do not introduce case-specific runtime rules to pass a benchmark.

### Dense versus local hybrid comparison

`scripts/compare_retrieval.py` implements a separate evaluation-only comparison on the unpublished v6 candidate. It reuses the 955 stored occurrence vectors and compares exact Qwen dense top 20, a local BM25 control, and dense+BM25 application-side reciprocal rank fusion. It does not wire the public API to the candidate or change its configuration/aliases. The original frozen preparation artifact remains immutable; actual results use a new evidence directory.

BM25 uses the same literal chunk retrieval texts, fixed `k1=1.2`, `b=.75`, positive `log(1+(N-df+.5)/(df+.5))` IDF, and NFC/casefold/Unicode-letter-number-mark tokens. It has no stemming, Arabic letter folding, translations, stopword list or query expansion. Original RRF uses equal contributions and one-based ranks with `k=60`; this is explicitly application-side fusion, not Qdrant's default/native RRF. Dense results are queried once per case and reused unchanged by hybrid. Fetched ties sort by chunk ID; exact ties crossing the top 20 cutoff remain a documented limitation. All source occurrences and issue codes remain independent and intact.

Prepare/count without dispatch:

```powershell
& .\.tools\uv\bin\uv.exe run --locked python -m scripts.compare_retrieval --output artifacts/NEW_COMPARISON
```

Only an explicitly authorized run adds `--execute`. The bounded query stage uses the unchanged pinned Qwen query prefix/route, batches of 16, at most six requests and 4,758 exact input tokens for the 90 raw queries, retries/fallbacks off and a 180-second experiment deadline. Existing corpus embeddings are not repeated. Query vectors are cached by exact formatted input/configuration and shared across modes. The runner verifies current route pricing/key allowance and candidate reads before dispatch, preserves all completed per-case rankings before scoring, and rejects silent repetition of a started evidence directory. Any failure stops and preserves receipts/cache; no automatic paid fallback or candidate cleanup occurs.

Report known support/context witness recall at 5/10/20 for all 90 cases, by development/evaluation split and language. The frozen preliminary selection rule excludes six raw-query conversation and three exhaustive-directory cases from its eligible denominator while retaining their separate scores/receipts. Hybrid qualifies only if development support recall@10 strictly increases, support and context recall do not decrease in any language, and evaluation confirms all conditions without retuning. Otherwise retain dense as the experimental baseline and call the comparison inconclusive. Development context coverage has only three cases; aggregate gains cannot establish universal superiority. Manual source review of gains/losses and valid unlisted alternatives is required before adoption. Ranking scores and diagnostic flags do not establish source-policy enforcement, answer correctness or readiness.

#### Executed comparison v1

The authorized run is recorded separately in [the local comparison report](../artifacts/m4-retrieval-comparison-v1/REPORT.md). All 90 raw queries ran: six query-embedding attempts, 4,758 reserved/reported tokens, 90 cached 4096-dimensional vectors, 90 exact candidate reads, 270 ranked lists and 810 case/cutoff score rows. No corpus embedding, index mutation, alias publication or Luna call was repeated/initiated.

The predeclared eligible evaluation split has 63 cases, including 51 with support groups and 15 with uncertainty/clarification groups (roles can overlap). The six history and three exhaustive-directory cases remain scored separately. Macro recall concerns the selected known witness groups, not all relevant chunks or generated answers:

| Mode | Support@5 | Support@10 | Support@20 | Context@10 |
| --- | ---: | ---: | ---: | ---: |
| Dense | 73.53% | 84.31% | 88.24% | 56.67% |
| Local BM25 | 50.98% | 53.92% | 62.75% | 33.33% |
| Dense + BM25 RRF | 64.71% | 76.47% | 87.25% | 60.00% |

Hybrid's development support@10 improved from 54.44% to 60.00%, but evaluation support fell in each language. The frozen rule returns `inconclusive_dense_baseline_retained`; do not describe this one fusion/analyzer configuration as proving that dense is universally better.

GPT-6.1 Sol actually reviewed every individual query/part and complete dense/hybrid top 10 source text across all 90 cases, with exact source IDs/quotes and family ledgers. Scripts only bound/tracked judgments and verified inputs. Review found real loss of active-acne details for two Arabic hybrid queries, plus strict-witness misses with legitimate alternate phone/location/role evidence. Independent adjudication qualifies profile-path ambiguity and rejects a derivative directory claim as sufficient specialty authority for either mode. Gold and scores were not rewritten. Both modes still fail some compound/history/exhaustive-list needs; repeated footer/contact occurrences can consume top-k. BM25-only and lower top 20 semantic contents were not exhaustively reviewed, and no new full-site semantic audit is claimed.

The full 786-test offline suite passed before execution; an independent post-run audit passed 506 deterministic checks covering sources, cache/receipts, rankings, all score rows and the selector. Empty alias responses were checked but not separately saved during execution; fresh read-only observations corroborate current state only. Query quote is $0.00004758 at the checked route price; key counters remained unchanged at the final bounded observation, so final billing is unresolved. No answer-level safety/readiness follows from these checks.

Next: bounded evidence assembly, complete admitted source reads when a question requires that scope, occurrence-preserving presentation and explicit source/identity/uncertainty enforcement. Use development fixtures and a new reviewed evaluation version; do not tune to the now-exposed evaluation cases or delete useful source occurrences to improve ranking scores.

### M5 planner preparation

The next offline graph step is prepared in `artifacts/m5-planner-cases-v1`: **24 new authored cases, eight families × English/Arabic/Jordanian Arabic, covering 63 parts**. Six cases are development; 18 are reserved evaluation, grouped by family. These are new compositions of known source/policy challenges, not an unseen statistical holdout. Prompts and runtime were fixed before authoring; no runtime tuning used these cases. The old 90-case benchmark remains unchanged.

GPT-6.1 Sol authors made the semantic decisions. A different service reviewer actually reviewed 12 cases/36 parts; root independently reviewed the other author's 12 doctor cases/27 parts after the first reviewer was interrupted. Each record identifies its actual reviewer, current case/plan hashes, individual part rationale and saved source evidence. Forty selected witness chunks span 15 saved official URLs. This is targeted fixture review, not another full-corpus or fresh live-site audit. Selected witnesses are not exhaustive relevance labels.

[planner_review.py](../scripts/planner_review.py) verifies coverage, literal spans/history anchors, app-issued handles, source-use restrictions, split integrity, independent judgment bindings, exact source payloads/owners, original HTML hashes and DOM coordinates. Scripts make **zero semantic decisions**. Frozen source packets preserve 42 per-ledger chunk entries (40 distinct chunks), 333 node entries and 358 source/context span references, including repeated source/context references. It checks that `requests.jsonl` contains no expected plans, selected-witness labels or rationales and keeps requested language separate from the case's language.

Read-only verification requires the manifest hash recorded in the local report:

```powershell
& .\.tools\uv\bin\uv.exe run --locked python -m scripts.planner_review --frozen artifacts/m5-planner-cases-v1 --manifest-sha256 HASH_FROM_REPORT
```

The accompanying [offline Luna payload preparation](../scripts/prepare_luna_screen.py) exercises the actual adapter and graph with an always-rejecting counter and a forbidden mock transport. An explicitly labelled authored plan and selected-witness oracle allow inspection of the second-stage payload; they are not model planning or search results. All 24 cases captured both payloads, and all draft dispatches stop at unavailable counting. No draft answers were fabricated. Neither the resulting `provider_failed` outcomes nor the authored 33 candidate/18 unknown/three clarification/nine excluded expectations are model accuracy scores.

Complete source reads remain bounded to the admitted membership, while source language, doctor ownership, comparisons, negations and public/private siblings stay distinct. Unknown source claims and unavailable time operations remain unknown. This preparation measured no nDCG, new retrieval gain, Luna planning accuracy, answer quality, live latency or provider cost. Its strict-counting gate is historical: the user subsequently authorized normal chat with provider-reported usage. The frozen preparation still binds its original code; use a new execution record with current code hashes rather than altering its manifest. Before the larger live screen, verify the actual planner/draft schemas and retain all partial/unknown outcomes. Readiness remains false.

### Offline cached assembly replay

The first candidate-assembly implementation has synthetic contract/safety tests and an independent code review. [replay_evidence_assembly.py](../scripts/replay_evidence_assembly.py) provides a separate offline experiment: `cached_occurrence20`, `cached_pool20_coalesced`, and `cached_distinct20`. They use the same cached query/document vectors, exact local float64 cosine, source corpus and 6,000-Qwen-token/16-rendered-unit budget. The second arm changes presentation within an unchanged pool; the third also changes candidate supply by grouping before truncation. No re-chunking, query decomposition, provider call, index request or API integration is performed.

Prepare with `uv run --locked python -m scripts.replay_evidence_assembly --output artifacts/NEW_OFFLINE_REPLAY`; explicitly add `--execute-offline` for local computation. The runner requires every existing 834 document and 90 query cache entry, verifies each file against its original hosted-run hash and configuration/vector checks, pins historical inventories and the corpus configuration plan, preserves every selected occurrence and counted rendering, refuses repetition of a started output directory and saves selections before gold scoring. Missing/corrupt/changed cache stops without model fallback. Original sealed benchmark files remain unchanged.

The replay reports strict selected-witness membership after K rendered units, retaining all explicitly selected occurrence members of an exact group. This is a presentation/pooling ablation: K groups can represent more source occurrences than K separate slots. Report the unit definition, actual rendered groups/tokens and source members; do not call a witness-membership gain semantic answer coverage or compare it silently with a different K definition. Witness membership among attached occurrences does not prove that a displayed representative citation satisfies an explicit source constraint. The fixed counter/budget is retrieval-only and does not establish Luna admission. Opaque whole-query probes do not prove preservation of semantic subquestions or correct private/ambiguous classification. The same 90 exposed cases are regression evidence, not a new holdout. nDCG and source-claim relevance/answer judgments remain separate unmeasured gates.

The v2 replay has now completed: 90 cases, 270 renderings and 810 score rows; zero provider/index calls. Evaluation support @10 remains 84.31% and context 56.67% in all three arms. Before-limit grouping repairs D07 contact crowding in development (development support 54.44% to 70.00%); within-pool coalescing saves 3.20% average rendered tokens without an evaluation gain. There is no selected-witness regression at K=5/10/20, and no generalization or semantic nonregression claim. Independent checks reconstruct every score/render/count and all 924 historical cache hashes. See [measured results, source review limits and next experiment](EVIDENCE_ASSEMBLY_RESULTS.md).

Before approving a claim of optimal chunking in M3/M4, compare structure-aware chunks with a bounded fixed-window baseline using the same source snapshot, embedding model, retrieval budget, and bilingual questions. Review retained facts, exact source mapping, doctor/FAQ/table integrity, relevant-evidence recall, supported answers, embedding input count, and cost. No strategy is the proven best for this corpus before that comparison. A semantic/LLM chunker is a later candidate only if a measured gap justifies its complexity.

## Metrics and release criteria

### Initial M5 offline graph checks

The compiled `OfflineRagWorkflow` is tested with injected synthetic plans, source catalogs, counters and providers. Tests cover English/Arabic/Jordanian Arabic passages, unchanged history, explicit excluded/clarification siblings, complete-source reads without search, source-policy context restrictions, exact full-passage quotation/qualifier preservation, per-part source/citation isolation, missing evidence/scope, invalid provider/retrieval output, shared budgets, deadlines and cancellation. Ambient tracing, explicit strict-counter refusal, normal reported-usage chat and two-stage continuation with missing usage are tested separately. The public chat route remains `503`.

These are control-flow/contract tests, not measured natural-language planning, fresh retrieval improvement or semantic grounding. Full-passage identity avoids deterministic acceptance of clipped qualifiers; it still does not establish relevance or completeness of an answer. The reviewed 24-case planner/source-scope fixture set is prepared; its live evaluation and a fresh held-out evaluation remain needed. Normal chat no longer requires a local input counter; actual planner/draft strict-schema compatibility and model interpretation still require verification. Record mock success separately from production acceptance.

Track per-question retrieval recall against known source spans, attribution correctness, completeness of addressed request parts, citation validity, source support of generated claims, correct uncertainty, public/private boundary behavior, latency, physical provider attempts, and token usage.

All mandatory boundary, attribution, citation-reference, and deterministic-hours cases must pass. Every answer in the curated release set must be reviewed for source support, and all requested parts must be represented. Report failures rather than averaging a harmful attribution error into a favorable score.

Structural validators can check IDs, URLs, quotations, and coverage fields, but cannot prove the meaning of every paraphrase. Semantic grounding needs fixture-based review and clinic review of public facts. No second LLM judge is required for the initial design.

Performance targets need measurements on the chosen model/provider and deployment. The 30-second request deadline is a limit, not a success-time promise. Record latency and cost observations without treating documentation or mocked tests as live acceptance.

## Live compatibility screen

The development-only planner runner is [run_luna_planner_screen.py](../scripts/run_luna_planner_screen.py). It shares the graph's exact [planner input builder](../src/telescope_rag/graph/planning.py), original prompt and 1,000-output-token cap. Preparation verifies sealed source/fixture/review/DOM hashes and writes a new plan binding all current runtime/script bytes. Historical fixture manifests remain unchanged; their changed code bindings are explicitly recorded. The model receives only original synthetic request/history and the server source manifest, never expected plans, witness labels or reviewer rationales.

```powershell
& .\.tools\uv\bin\uv.exe run --locked python -m scripts.run_luna_planner_screen --output artifacts/NEW_DEVELOPMENT_SCREEN
```

Only an authorized execution adds `--execute` with that same directory. Execution requires matching prepared bytes and committed code, uses the project dotenv key, and records at most six distinct development requests with zero retries/fallbacks and no embedding, index or draft call. A create-exclusive start marker prevents repeating a partially completed run. Fatal account/model/protocol errors stop the screen. Other per-case failures remain explicit. The 18 reserved evaluation cases are never dispatched. Local schema/offset/handle validation is recorded separately from root's subsequent language/source review; exact equality with one authored expected plan is not a semantic accuracy metric. No local input-token count or pre-run cost guarantee is claimed.

The explicit `--profile source_types_no_reasoning` candidate uses a new directory, `planner_candidate_v2.py`, exact per-document `available_block_types` from existing chunks and `reasoning.effort=none`. The baseline prompt, default graph and provider-default reasoning remain unchanged. This combines two development corrections; a before/after difference cannot identify their individual causal contributions. Requests, source facts/owners, strict schema, six-case split and 1,000-token output cap stay fixed. Preserve the baseline failure evidence and complete semantic review before adoption; no reserved-case dispatch or deployment is implicit.

When live requests are explicitly authorized, run a small bounded screen for Luna structured planning, answer output, Qwen batch/index mapping, actual embedding dimensions, and Arabic/English retrieval. Record selected model/provider, configuration, schema, usage, errors, and the index snapshot. Do not send patient records or retain raw visitor conversations.

The opt-in `--profile literal_anchors` uses `AnchoredPlannerReply` and a separate prompt, replacing model-counted coordinates with quoted original fragments/constraints. It retains current source-type metadata and provider-default reasoning. Preparation/execution require a new directory. Search queries must include their complete original fragment; there is no runtime query/anchor repair. The actual graph supports this profile through explicit dependency construction, preserving the default baseline.

The initial live anchor screen at `a894547` issued six requests: three contact plans passed schema, literal bindings and individual language review against the saved official contact pages; three mixed-question responses truncated and could not be semantically assessed. Evidence: `artifacts/m5-literal-anchor-development-v1/root-semantic-review.json`. This is three targeted development passes, not six-case success or retrieval/answer accuracy. The runner now accepts an explicit nonempty unique subset of the same six development IDs and `--output-tokens 4096` for a separately frozen capacity experiment. Reserved IDs are refused. The planned follow-up in `artifacts/m5-literal-anchor-capacity-v2` selects only PL05-ar/PL05-ar-JO/PL05-en, a 30-second provider timeout and normal reasoning; successful contact cases are not repeated. A preparation variable-name collision was corrected and regression-tested before dispatch; its failed v1 attempt is preserved with zero provider calls. No automatic retry, gold revision or hidden semantic repair is allowed.

The follow-up executed at `c27f854`: three HTTP 200 strict/literal-valid plans, two targeted semantic passes and one failure. Root individually reviewed all three plans/10 parts against 21 relevant saved official chunks with 140 verified DOM references. Jordanian Arabic split a dependent before-starting fee notice and scoped it to the Telescope Experience page, excluding the actual FAQ witness. English retains the correct FAQ but also selects related Patient Rights context; broader candidate scope remains a retrieval tradeoff. Combined with the first screen: nine actual requests over six unique cases, six complete plans/13 parts reviewed, five distinct-case targeted passes, one semantic failure and three earlier unassessable truncated attempts. These are development observations, not held-out accuracy. Evidence: `artifacts/m5-literal-anchor-capacity-v2/root-semantic-review.json`. At that checkpoint the separately versioned v4 dependent-context prompt was prepared offline and had no live result or acceptance. The 18 reserved cases remained undispatched.

Offline tests prove literal handling and control flow with authored mock outputs, not that Luna will choose good anchors, preserve a negation or split semantic purposes correctly. The six prior reviewed fixtures can be explicitly adapted to the new schema for structural replay; record that conversion and any query adaptation, never call it a model result or rewrite frozen gold. Actual new responses still require individual language/source review. Full original-query coverage, source ownership, explicit unknown/partial outcomes and retained clinical boundaries remain mandatory; no character heuristic is used as semantic judgment.

V4 subsequently ran once at `8dbf56d`: all six development plans complete and pass literal validation. Root source-based review accepts four targeted cases and withholds two Arabic mixed-purpose plans because an independent eligibility question is duplicated into a fee part under a broader use. The prior Jordanian source/notice error is corrected, but that does not establish one-purpose policy binding. No draft answer was generated; the policy replay establishes a representation risk, not an observed unsupported answer. All 18 reserved cases remain undispatched. Details, exact review evidence and the anti-overfitting protocol are in [PLANNER_GENERALIZATION.md](PLANNER_GENERALIZATION.md) and `artifacts/m5-context-generalization-audit-v1`. Do not turn six correlated development cases or authored reserved fixtures into an unseen-data accuracy claim.

The opt-in `answer_targets` correction uses the existing anchor/reference schema, a separate v5 prompt and explicit target/context drafting metadata. Eighteen new authored wording/contrast cases were frozen before candidate changes in `artifacts/m5-target-context-cases-v1` (manifest SHA-256 `5c2e81917da4e4174de99452953641329bea2735a250db4023f9e69aa6fdf6d1`). Each actual output needs language/source review; no exact expected-plan or keyword scoring is used. The original six-case runner supports this profile. [run_target_context_screen.py](../scripts/run_target_context_screen.py) separately prepares the fresh 18 questions, exports only requests/history/source manifest, and requires a six-pass manual review bound to the exact original development outputs and same candidate code before execution. It is create-exclusive, has zero retries/fallbacks and cannot dispatch the original reserved set. Its 600-second outer screen deadline covers 18 separately bounded requests; graph/API timeouts remain unchanged. Fresh fixtures are development/transfer checks, not a statistical holdout or independent review.

V5 ran at `a1bd01a`: the six original plans/13 parts were admitted only to continuing the fresh screen, with recorded fragmentation, scope, language and unused-label cautions. No exact expected shape was required where both fee/notice targets retain the same native FAQ and compatible policy. All 18 fresh outputs then passed schema/literal checks, but root language/source review of their 25 parts found five failures: two false public-offer exclusions and three unnecessary clarifications for explicitly named same-specialty doctors. Thirteen fresh cases pass with recorded cautions. No prompt or code changed between fresh cases; no failure was repaired or retried. Evidence: `artifacts/m5-answer-target-fresh-v1/root-semantic-review.json`, source evidence, original captures and seals. The 18 original reserved cases remain untouched, and the fresh set is now exposed development evidence for later candidates. No retrieval/answer accuracy or generalization guarantee follows from these results.

Separate live provider compatibility from source completeness and final production acceptance. A single minimal synthetic Luna JSON screen passed on 2026-10-16 through the actual adapter, with 70 reported input/16 output tokens and no local counter or retry. This is not the prepared bilingual planner/draft screen. Detailed receipts and limitations are in `artifacts/m5-reported-usage-v1`; Qwen's earlier screens and corpus/query runs are recorded separately in [PROVIDERS.md](PROVIDERS.md) and [PROJECT_STATUS.md](../PROJECT_STATUS.md).

The first actual six-development-case planner screen subsequently ran at `ef504b7`: five responses truncated and the sole schema-valid plan selected a block filter that removes the answerable source. Root reviewed that actual plan as a semantic failure; the five absent plans remain unassessable. Results and full accounting are in `artifacts/m5-luna-planner-development-v1/REPORT.md`. Schema success, offline regression success and basic model access are not evidence of successful planning. Preserve these baseline failures before preparing any development correction; do not tune on the 18 reserved cases.

The opt-in combined candidate ran once on the same six cases at `e6a4916`: six complete strict-JSON plans, zero reported reasoning tokens, but zero literal coverage/admission passes. Root reviewed all six actual plans/13 proposed parts; incorrect character spans, negated-action representation and merged public purposes remain. Median observed attempt time fell from 11.680 to 2.648 seconds while input usage rose; this is not a causal single-variable result, retrieval gain or answer-quality acceptance. Current corrected judgments, including retraction of an erroneous draft CTA-type claim, are in `artifacts/m5-luna-planner-development-v3/REPORT.md` and `root-semantic-review-v2.json`. Keep this candidate opt-in. Repair literal request anchoring and purpose/negation preservation offline before another model screen or retrieval integration.
