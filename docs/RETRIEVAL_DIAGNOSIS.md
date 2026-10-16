# Retrieval diagnosis and proposed chunking experiment

Date: 2026-10-16, Asia/Amman. Baseline checkout: `6afe486`. Scope: read-only implementation/source/evaluation diagnosis, fresh offline regression tests, and an experiment design. No production code, source bundle, frozen gold, collection or provider configuration was changed. No provider or index request ran. Technical documentation was consulted on the web; clinic evidence remains exclusively the saved Telescope website sources. This is a historical diagnosis: the local Luna counting gate described below was subsequently removed for normal chat under the user's authorization; see [current provider contracts](PROVIDERS.md).

**Recommendation:** implement bounded evidence assembly and source-scope handling first, keeping dense retrieval provisional. The user's independent semantic audit and controlled chunking comparison is a good experiment. Treat selective boundary changes as candidates, rather than assuming a replacement chunker will solve the observed failures.

## Current implementation and evidence

The repository has an evaluation-only [dense candidate reader](../src/telescope_rag/retrieval/candidate.py), [literal BM25/RRF baseline](../src/telescope_rag/retrieval/lexical.py) and [comparison harness](../scripts/compare_retrieval.py). Dense queries use exact cosine search, a fixed top 20 candidate pool and full payload validation. The harness embeds the raw current query; it does not interpret conversation history, decompose compound questions, select complete source scopes or enforce source issue codes. The public [chat endpoint](../src/telescope_rag/api/routes/chat.py) returns 503; `graph/` and `knowledge/` contain placeholders. Proposed pipeline behavior is not a serving implementation.

The prior run's sealed artifacts, source files and code passed all 389 hash comparisons at this diagnosis's start. The saved candidate observation records 955 points, no active alias and zero indexed vectors. This task did not contact Qdrant, so these are last-run observations, not a fresh service-health check. Since the benchmark explicitly used exact search, missing HNSW construction does not explain its semantic relevance failures. ANN tuning is a separate later scale/latency experiment.

Current source inventory: 107 pages, 955 occurrence chunks and 834 distinct embedding inputs. Recorded Qwen counts are 10–490 tokens, median 64; none reaches the 1,200-token ceiling. Counts are descriptive, not semantic usefulness judgments or proof of optimal boundaries. Current chunking already follows native doctor/FAQ/section/list/table structure and preserves source spans, owners, aliases, qualifiers and diagnostic uncertainty.

Prior measured evaluation results remain unchanged:

| Method | Selected support witness recall@10 | Context witness recall@10 |
| --- | ---: | ---: |
| Dense | 84.31% | 56.67% |
| Local BM25 | 53.92% | 33.33% |
| Dense + BM25 RRF | 76.47% | 60.00% |

Denominators: 51 support-bearing and 15 context-bearing eligible evaluation cases, with overlapping roles. The frozen rule excluded six raw-query history and three exhaustive-directory cases from selection while scoring all 90. These are selected exact witness-group scores, not answer accuracy or exhaustive relevance. The prior [comparison report](../artifacts/m4-retrieval-comparison-v1/REPORT.md) preserves all splits/cutoffs, valid alternate evidence and independent reporting qualifications.

## Independent semantic diagnosis actually performed

Two independent GPT-6.1 Sol agents read complete chunks and the relevant original HTML sections, including literal DOM text/attributes and ownership. A third independently audited retrieval/evaluation code and saved measurements. Scripts checked hashes, source identity and coverage; scripts did not decide coherence, relevance or usefulness.

| Audit | Complete chunks read | Saved source pages containing the reviewed sections | Evidence record |
| --- | ---: | ---: | --- |
| Doctor/logistics | 39 | 19 | [Individual judgments and original source evidence](../artifacts/m4-retrieval-diagnosis-v1/doctor-coherence-review.json) |
| Services/scope | 24 | 16 | [Individual judgments and original source evidence](../artifacts/m4-retrieval-diagnosis-v1/service-coherence-review.json) |
| Retrieval/evaluation design | Implementation, previous scores and 90 saved timing records | Existing sealed artifacts | [Independent diagnosis and experiment design](../artifacts/m4-retrieval-diagnosis-v1/evaluation-design-review.json) |

There is one overlapping chunk: **62 distinct chunks across 32 source URLs** received new source-based semantic judgments. Doctor review includes all 11 English directory cards and six complete sparse-profile main texts. Relevant source/context evidence counts are 224 and 256 per-audit occurrences; these are not globally unique DOM nodes. This purposive sample covers known failures and additional doctor/service units. It is not a new semantic review of all 955 retained chunks or every word of 32 whole webpages, and it cannot estimate corpus-wide defect prevalence.

Neither source reviewer found confirmed unrelated factual content or harmful semantic fragmentation inside the inspected chunks. No deletion was justified. Several broader, coherent units contain multiple answerable subtopics and support a focused granularity experiment. Weak/awkward image labels merit individual classification; informative labels must not be removed by a blanket rule. A repeated source label or sparse name-only page does not justify inventing missing clinical detail.

## Improvements ranked by current evidence

| Priority | Finding and evidence | Proposed improvement and limit |
| --- | --- | --- |
| 1 | Whole-query retrieval drops supported parts. B03 retrieves surgery content without the separately requested phone, although complete contact sources exist. B07/B08 omit history by design. | Preserve original request spans and per-part evidence obligations; use a bounded planner contract for clear historical identities and clarification for ambiguity. Pure offline fixtures can test the contract first; live Luna compatibility is a separate gate. Chunk changes alone do not supply the missing query scope. |
| 1 | Source authority and uncertainty are recorded but unenforced. Generic recovery/consultation text and rich versus sparse profile paths have distinct admissible uses. | Carry literal owner, exact source scope, approved alias authority and uncertainty into evidence assembly and validation. Do not infer procedure ownership, offer eligibility or a specialty from similarity or a derivative heading. |
| 1 | Explicit directory questions need all 11 independently owned cards. Top 10 generic passages cannot supply 11 separate cards. | Read complete admitted directory membership through a bounded source manifest, retaining each owner. Apply the same principle to an explicitly requested page/section; keep source-path ambiguity explicit. |
| 2 | Repetition consumes candidate slots. Root verification found **all 20 saved D07-en dense hits belong to one exact text/owner/language/policy/configuration/snapshot group**. The source auditors confirmed coherent footer content, not 20 unrelated chunks. | Group equivalent evidence for presentation with every original occurrence/URL/span attached. Supply enough distinct candidates before grouping, using an independently bounded pooling design. Coalescing the existing 20 hits yields one group and cannot recover details absent from that pool. Never deduplicate different doctors because their specialty matches. |
| 2 | The tested hybrid loses the distinct English active-acne claim for two Arabic comparison queries. Both original language-specific service chunks remain complete. | Retain dense provisionally. Test candidate depth, lexical analysis or fusion separately on development evidence. One literal BM25/RRF result does not establish that every hybrid configuration is inferior. |
| 2 | Current gold names 65 selected chunks, and valid alternate phone/location/profile evidence was previously found. Changed boundaries change chunk IDs. | Create treatment-neutral source evidence obligations and pooled, independently reviewed relevance labels before comparing new representations. Preserve the original benchmark unchanged. |
| 3 | Some units are coherent but broad: a doctor expertise list plus several paragraphs, a four-card service section and three complete technique tables. | Test native child passages linked to complete source parents. No measurable benefit from splitting these units has been established; ordinary complete FAQ/card chunks should remain intact. |

Qdrant documents grouping as a way to diversify results and explains why deduplicating a truncated hit list cannot refill missing slots. Our grouping key must respect literal evidence and owners: grouping only by webpage could hide several different doctors/services on one directory page, while footer copies across different pages would remain separate. [Qdrant grouping documentation](https://qdrant.tech/course/beginners/module-6/grouping/).

## Source-faithful strategy to test

Keep the approved structural policy and immutable original parents. Propose changes only for individually reviewed residual units:

1. Define a retrieval child as one complete native paragraph/card or coherent list/table row group with its explicit subject, necessary question/header, governing qualifier, comparison labels and negations. Preserve complete FAQs, short cards, meaningful heading-only facts and lists whose items require shared context.
2. Use exact original slices and literal headings. Store parent/source IDs and spans. If a child depends on its parent's introduction or qualifier, include the necessary literal context or require bounded parent expansion before using it as evidence. A source-less generated summary is not a substitute.
3. Keep different doctors, language-specific claims and source URLs separately owned. Confirmed identity aliases link metadata; they do not merge bodies or make translations equivalent. Keep published source uncertainty and all six approved source decisions.
4. Retain a before/after accounting ledger for every changed span, retained fact, repeated context, affected removal and experimental exclusion. Independently review high-risk changes. Any full replacement would require genuine complete coverage of its affected content, beyond this 62-chunk diagnosis.
5. Present repeated equivalent evidence once while retaining all occurrence provenance and question-to-evidence links. Apply no similarity-based doctor/text deletion. An asset label may be moved out of an experimental embedding projection only after an explicit occurrence-specific usefulness decision; preserve its original source and decision.
6. Reuse cached vectors only for byte/configuration-identical formatted inputs. Split/merged text needs actual new embeddings; averaging old vectors or assigning a parent vector to a new child would not test the proposed representation.

Concrete candidate parents and full source evidence are recorded in the two semantic ledgers: doctor chunk `057dba6f…`, service chunk `8c51efe0…`, and three complete comparison tables. These are candidates for a small ablation, not findings that their current content is wrong. No candidate corpus or new vectors were created here.

## Fair comparison and measurements

Separate causes rather than changing chunking, query handling, fusion and assembly at once:

| Arm | Representation | Retrieval/assembly | What the comparison establishes |
| --- | --- | --- | --- |
| A | Frozen v6 | Fixed dense retrieval and one shared bounded assembly policy | Control |
| B | Only approved, source-accounted child-boundary changes | Same queries, dense profile, candidate cap, assembly/parent-expansion rule and evidence budget as A | Chunk representation effect |
| C, separate ablation | Unchanged v6 | Assembly/presentation change versus baseline using identical cached candidate pools | Assembly effect within those pools; no claim of recovering unseen candidates |
| D, later if justified | Fixed representation | One preregistered hybrid/depth/analyzer candidate | Retrieval configuration effect, separate from chunk boundaries |

Freeze source snapshot/inclusion, approved decisions, exact query/history text, model/route/query prefix, vector dimensions, exact search/tie policy, hardware and global request/candidate budgets. Use identical English/Arabic/Jordanian Arabic tests within each comparison; keep intent/language siblings together. The 90 exposed cases remain useful regressions. Acceptance needs a new independently authored/reviewed intent-grouped holdout; new paraphrases of those same exposed intents alone are not independent acceptance evidence.

Define gold as original source-span evidence obligations with explicit owner, language-claim distinction, qualifiers, requested URL scope and separately reviewed alternatives. Do not require obsolete chunk IDs or count each new fragment as another recovered fact. Pool the union of each arm's candidate results plus known witnesses and hard ownership negatives; reviewers judge without arm labels. Mark unjudged results explicitly and report judged-pool coverage. Compare every arm against the same frozen judgments.

| Measure | Required definition |
| --- | --- |
| Recall@5/10/20 | Fraction of distinct required source evidence units completely supported by the retrieved union, with owner/qualifier/scope intact. Count each unit once; report support and uncertainty context separately, by language and intent. Preserve old selected-witness recall as a separately named regression metric. |
| nDCG@5/10/20 | Binary or graded passage relevance from the shared reviewed pool. Recommended grades distinguish complete support, partial support, useful context and reviewed unrelated/unusable content. Do not silently grade every unlisted source 0. Standard passage nDCG and a separately named novelty/group metric must not be conflated. |
| Evidence coverage | Supported request parts whose full evidence obligations fit the rendered context, plus all-parts success and clarification/unknown context coverage. Measure after packing under the same evidence-token budget; distinguish passage retrieval from actual generated-answer behavior. |
| Fidelity | Zero introduced facts, source/owner transfers, lost qualifiers, reinstated exclusions or fabricated provenance. These are hard gates; aggregate recall cannot compensate for them. |
| Latency | Paired repeated p50/p95 for embedding, retrieval, source expansion/packing and complete pipeline where implemented. Specify cache state, hardware, concurrency, payload budget, sample size and percentile convention; randomize arm order. |
| Cost | Changed-input embedding tokens/requests, unique inputs versus source occurrences, local CPU/memory/storage/build cost, per-query calls/tokens, and evidence-context volume. Separate price quotes from observed billing and one-time preparation from recurring query costs. |

Report fixed K results **and** fixed rendered-evidence-token-budget results. Declare the budget before scoring; use identical verified Qwen counting for a clearly labeled retrieval-only experiment if needed. This does not establish Luna input admission: compatible Luna counting is still unavailable. The planned 16-chunk/6,000-token serving limit is a design setting, not a validated optimization or a license to use Qwen counts as Luna counts.

nDCG supports binary as well as graded labels. It is mathematically possible to calculate a selected-positive proxy from v1, but this diagnosis withholds it because alternate sources remain unjudged and representation changes would make that proxy misleading. [Qdrant relevance evaluation](https://qdrant.tech/documentation/search-evaluation/retrieval-relevance/) explains qrels and metric choice; [NIST's graded passage judgments](https://trec.nist.gov/data/deep2021.html) distinguish related context from an answer and warn against comparing scores from different judgment sets. Full 955-wide judgments are not a prerequisite for a transparently reported pooled evaluation.

Predeclare minimum gain, per-language/owner/scope nonregression, fidelity gates and acceptable latency/cost bounds. Analyze paired differences at the intent-group level rather than treating 90 translations as independent samples. If the small experiment is inconclusive, retain baseline and report uncertainty.

## What is measured now

The independent evaluator recomputed saved timings from the previous 90-case run; this task made no new retrieval request. P50 is the median; p95 is nearest rank:

| Saved component | p50 | p95 |
| --- | ---: | ---: |
| Dense adapter, including local transport/payload checks | 12.49 ms | 17.61 ms |
| BM25 search only | 0.43 ms | 1.67 ms |
| Paired sum of dense + BM25 + fusion components | 13.85 ms | 18.74 ms |

This is one local sequential pass, not deployment latency or a separately dispatched hybrid service. BM25 construction and query embedding are excluded. Query embedding took 14.625 seconds across six batches; no per-query provider p95 can be derived. Historical query quote: $0.00004758 for 4,758 exact reported/reserved tokens, still unreconciled to saved key counters. Query vectors were shared, so no extra embedding charge difference was measured between dense/hybrid. No current price/balance check or new inference dispatch occurred here.

**No proposed chunking gain, nDCG or end-to-end evidence coverage has been measured.** Changed document inputs are not yet embedded; no treatment comparison was run. Existing cache/ranking replay can test unchanged representations or a bounded packer offline. New document/query embeddings, Luna calls and any index operation require separate explicit approval under the current request. A future run proposal must first provide the exact reviewed inputs, token counts, missing-cache count, budget/quote basis, target and rollback boundary. No approval is being requested for an undefined run.

## Verification and next action

Fresh current checks: 786 offline tests passed, Ruff lint/format passed (84 Python files), lock check passed (43 packages). All 389 prior sealed files matched before documentation updates; final verification permits only the explicitly documented status/ingestion-document changes. New audit records bind to exact source payloads, original HTML and hashes. See [verified facts and coverage](../artifacts/m4-retrieval-diagnosis-v1/verified-diagnosis-facts.json) and the local artifact directory for the final hash/commit seal. Source/evaluation data and secrets remain outside Git.

**Next concrete step:** specify and implement the offline bounded evidence-assembly contract on existing development fixtures/cache, with source/owner uncertainty and complete-source membership explicit. Preserve the current raw-query experiment as baseline. Prepare a small, independently reviewed child/parent treatment only for remaining granularity hypotheses, then produce a concrete approval-gated embedding/comparison plan. Generated-answer, Luna compatibility, publication and full chatbot readiness remain unverified.
