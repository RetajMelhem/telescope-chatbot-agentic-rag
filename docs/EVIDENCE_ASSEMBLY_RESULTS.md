# Offline evidence assembly and grouping results

On 2026-10-16 (Asia/Amman), the cache-only comparison completed all 90 frozen bilingual/Jordanian Arabic requests. Exact grouping before the candidate limit repairs the observed contact-information crowding in three development cases. **Eligible evaluation recall does not improve.** Dense remains the provisional retrieval baseline; no production adoption or data/answer readiness is established.

The verified implementation is checkpoint `4fff7f9`. It adds an offline evidence catalog, bounded assembly contracts, an exact cached cosine ranker, and a reproducible comparison runner. It leaves corpus chunks, original sources, approved source decisions, cached embeddings, Qdrant, the public API and frozen gold unchanged. There were zero provider/index calls and no incremental external API charge from this experiment. Local computation has a resource cost that was not monetized.

## What changed

The catalog verifies the supplied prepared digest and exact source membership. Caller-authored request parts retain original spans and public/excluded/clarification states. Literal or explicitly canonical owner, document and language filters apply before grouping. Complete admitted-source scopes derive members from the catalog rather than accepting a caller's expected count. Such membership is not proof of full webpage coverage or an answer's completeness.

Exact presentation groups preserve text, owner, language, section, source-policy and preparation/configuration identity. They retain every supplied occurrence and per-part source binding; two doctors sharing a specialty remain separate. All source records stay in the corpus. Round-robin packing keeps passages whole, counts the complete returned rendering and records omitted groups/missing scoped members. The larger provenance sidecar would require its own count if serialized into model input.

Known source flags restrict the explicitly declared intended use; unknown flags remain context only. Request-part scope and use are assertions supplied by a caller, whose semantic correctness is still unverified. The kernel never declares factual support, and Qwen retrieval counts never authorize Luna input. These contracts are available offline; they are not wired into a serving planner or answer generator.

## Frozen comparison

The experiment uses the original 955 occurrences, 834 document vectors and 90 query vectors, the same exact local float64 cosine engine and raw queries, and a common 6,000-Qwen-token/16-rendered-unit ceiling. Each entire raw query is one opaque public retrieval probe; there is no semantic decomposition, history resolution, private operation or query-dependent source-scope inference. Gold is only used to score after selections are persisted.

Every cache file must match the independently recorded SHA-256 from its original hosted run, in addition to the cache's vector/configuration validation. Historical inventories and the original corpus configuration plan are pinned. Missing, rewritten or corrupt caches stop without dispatch. The first unexecuted preparation in `artifacts/m4-evidence-assembly-v1` is preserved; execution used [v2's frozen plan](../artifacts/m4-evidence-assembly-v2/experiment-plan.json).

| Arm | Candidate/presentation behavior |
| --- | --- |
| `cached_occurrence20` | Top 20 physical occurrences; separate presentation |
| `cached_pool20_coalesced` | Identical top 20 occurrence pool; exact coalescing only |
| `cached_distinct20` | Score the same whole corpus, then select 20 distinct exact groups; retain their occurrence members |

Scoring measures frozen selected-witness membership after K rendered units. A group can carry several source occurrences. It is not ordinary occurrence recall with an unchanged K definition, nor semantic answer coverage. Attached membership also does not prove that a single displayed representative citation satisfies an explicit source constraint. A source-constrained caller must supply and validate that scope before assembly.

## Measured results

All cutoffs below refer to rendered units after packing. At most 16 units are rendered, so K=20 reads all available units without padding. Eligible selection excludes six raw-history and three exhaustive-directory cases; those nine remain scored individually. Evaluation support has 51 cases, evaluation context 15, development support 15 and development context three. The 90 cases were already exposed; these are regression results, not fresh holdout acceptance.

| Arm | Development support @10 | Evaluation support @5 / @10 / @20 | Evaluation context @10 | Mean Qwen tokens |
| --- | ---: | ---: | ---: | ---: |
| Separate occurrences | 54.44% | 73.53% / 84.31% / 88.24% | 56.67% | 5,510.04 |
| Coalesce within same pool | 54.44% | 73.53% / 84.31% / 88.24% | 56.67% | 5,333.94 |
| Group before limit | 70.00% | 73.53% / 84.31% / 88.24% | 56.67% | 5,538.97 |

All three evaluation language cells also remain unchanged at K=10: English support 85.29%, Arabic 82.35%, Jordanian Arabic 85.29% (17 support cases each); context 70%, 50%, 50% (five cases each). Evaluation context at K=5/20 is 56.67%/76.67% for every arm. There are no selected-witness regressions at K=5, 10 or 20 across the 90 cases. This limited metric does not establish semantic nonregression of every context or answer.

All score improvements concern D07's published contact channels. Before-limit grouping changes D07-en support from 0/3 to 3/3 at K=10 and both Arabic variants from 1/3 to 3/3. At K=5 it recovers 2/3 English and 1/3 in each Arabic variant. Within-pool coalescing recovers 1/3 for both Arabic variants at K=5, but cannot retrieve absent evidence. The original English-query top 20 is entirely one repeated Arabic footer group. That footer already contains a street address, email and a number labeled mobile; a 0/3 selected-witness score does not mean zero contact facts. It does not explicitly supply the requested WhatsApp channel or the FAQ's location qualifier. Displaying it once saves room but cannot supply those missing meanings from outside the pool.

Independent cutoff verification also found 15 case/arm/cutoff witness matches that rely on an attached footer occurrence rather than the first displayed representative citation; all concern D07. These are valid membership counts under the stated scoring rule, but not 15 independently established cited-URL support gains. The [cutoff supplement](../artifacts/m4-evidence-assembly-review-v1/postexecution-cutoff-supplement.json) preserves that distinction and the later ancillary-file hash change.

Within-pool coalescing reduces average rendered tokens by 176.10 (3.20%) without changing evaluation scores. Before-limit grouping instead uses 28.92 more average tokens (0.52%) than separate occurrences while providing broader contact evidence. Maximum token counts are 5,959, 5,999 and 5,999 respectively, all below the shared ceiling. Mean rendered units are 15.51, 14.91 and 15.51. No Luna price, answer-token saving or production cost improvement is inferred.

The saved local CPU pass observes plain-search p50/p95 220.38/348.97 ms, grouped-search 228.34/359.66 ms, and assembly p50 approximately 62–63 ms per arm. These are fixed-order observations with no provider latency, not a controlled deployment latency or speedup result. This Python whole-corpus replay is an evaluation tool. It is not proposed as the serving database replacement. Its raw top 20 order equals the historical Qdrant result on 81/90 cases and membership on 83/90; numeric precision/ties differ. Every new arm comparison uses the same local engine, and no universal float32/float64 identity is claimed.

## Verification and limits

The full guarded offline suite passes **917 tests**, including 131 new assembly, ownership, Arabic/English, qualifier, budget, ranker, scoring and historical-cache tamper cases. Ruff lint/format, the 43-package lock, Git whitespace, local documentation links and secret/generated-data exclusions pass. All 122 original source-input hashes remain unchanged.

Independent pre-execution review found a cache-integrity gap in the first draft: internal vector hashes alone did not bind vectors to the original hosted runs. The correction and seven tamper/binding tests passed an independent closure review. That reviewer verified all 834 document and 90 query historical hashes before execution. Both the original finding and its closure remain preserved.

The [independent post-run record](../artifacts/m4-evidence-assembly-review-v1/postexecution-independent-review.json) independently reconstructs 810 score rows, 72 split/language/cutoff cells, all 270 complete renderings and their actual pinned Qwen counts, and 924 historical cache hashes. It checks exact member/owner/policy/provenance bindings for 511 distinct selected payload IDs. This is mechanical verification, not 511 new semantic judgments. The full 955-vector cosine ranking was not independently recomputed; the ranker was reviewed and unit-tested. Exact coverage of targeted semantic rereads is recorded separately in the local review ledgers.

The ancillary cached-versus-historical comparison file was later enriched with per-case exact-group-key comparisons. Its earlier and later hashes are explicitly recorded; the original independent review is preserved. Core case records, frozen plan, scores, timings, result and vectors were unchanged by that enrichment.

The [targeted service semantic ledger](../artifacts/m4-evidence-assembly-v2/semantic-service-postreview.json) records actual GPT-6.1 Sol language judgments for six cases and 18 arm comparisons: 12 unique complete rendered-text readings plus six byte-identical counterparts. The agent reread original saved HTML units for 26 critical chunks on 15 pages, attaching 230 per-chunk source/context elements. Although 73 source occurrences appear in those rendered contexts, only those 26 critical chunks received a new original-HTML reread; this is not a blanket 73/511-chunk semantic review. No factual distortion, owner mismatch, qualifier loss or excluded-content restoration was found in the inspected units.

That review confirms the English active-acne and Arabic acne-scar services remain distinct; the damaged English Pore description remains excluded; and PRK doctor-evaluation/longer-recovery qualifiers remain intact. It also confirms grouping cannot resolve consultation eligibility or turn a generic recovery FAQ into a Botox-specific timeline. The opaque public probe does not implement personal-suitability handling. These are scoped preservation findings, not new answer-quality or retrieval-gain claims.

The [doctor/contact semantic ledger](../artifacts/m4-evidence-assembly-review-v1/semantic-doctor-postreview.json) records 21 different cases and all 63 arm packets, with transparent reuse of repeated source bodies: 944 displayed positions and 176 distinct displayed bodies read. It separately identifies 269 attached/referenced occurrences as mechanical bindings, not 269 independent semantic readings. Original saved DOM checks cover 11 chunk records on nine URLs plus the Arabic main-directory main element. That reviewer also implemented the cached ranker, a contribution disclosed in the ledger; the post-run mechanical reconstruction was performed by a separate agent. Across both semantic ledgers, 27 distinct cases and 81 arm packets have new scoped language judgments; all 90 have mechanical verification, not a new exhaustive semantic rereview.

The contact review confirms D07's gain is genuinely useful: contact pages and FAQs now supply the requested published channels and location qualifiers. It also distinguishes genuine gaps from label gaps. B03 still lacks its telephone subquestion in every rendered arm; B06 does contain valid public telephone alternatives despite missing the selected footer witness. For D04-en, both authoritative main-directory doctor cards are already in the candidate pool at ranks 17/19, but the 16-unit rendering limit omits them. Derivative cards cannot replace the approved specialty authority. Exhaustive directories remain incomplete, history-dependent references remain unresolved, and a sparse nested profile must not be used to deny a biography on a separate rich official path. These observed failures motivate per-part retrieval and source-aware context allocation.

No fresh full-site/corpus semantic audit, generated-answer test, relevance-complete nDCG, fresh holdout, serving integration or production readiness is established. Source flags remain diagnostic unless a semantically validated request use activates the relevant restriction. In particular, an opaque `general_excerpt` probe is not proof of consultation eligibility, authoritative doctor-role selection, procedure-specific FAQ scope or correct classification of a mixed private/public request.

Full local execution evidence: [result](../artifacts/m4-evidence-assembly-v2/result.json), [scores](../artifacts/m4-evidence-assembly-v2/scores.json), [timings](../artifacts/m4-evidence-assembly-v2/timings.json), and 90 per-case source/render/omission records in that directory. Generated artifacts and vectors remain ignored by Git; tracked code/docs identify and interpret them.

## Next concrete retrieval step

Retain dense provisionally and the new offline assembly kernel. Use grouping as a candidate crowding repair to test further, not an evaluation-confirmed ranking winner. The next experiment should test **explicit per-part retrieval planning and exact admitted-source reads**, preserving conversation references, doctor identity, negations, qualifiers and excluded/unsupported question parts. Compound phone-plus-treatment/private questions, authoritative directory-plus-profile questions and exhaustive lists are the observed motivation.

First prepare independently reviewed bilingual request-part/source-scope fixtures and a fresh evaluation set with broader relevance judgments. Validate that every original question part is accounted for, source restrictions are enforced by the intended use, and directory completeness comes from the admitted catalog rather than top-K. Use a reproducible offline replay where existing vectors suffice; any new embedding/model request needs its own authorization and exact budget. Luna compatibility/counting remains a prerequisite for model-driven planning or answers. Compare against the unchanged dense baseline before serving adoption. HNSW construction, alias publication and broad child/parent re-chunking remain separate later decisions.
