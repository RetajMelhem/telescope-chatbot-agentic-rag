# LangGraph pipeline

Status: an initial offline LangGraph prototype is implemented and tested on 2026-10-16. Actual Luna planner development screens have run and exposed coverage/semantic failures. Planner acceptance, draft execution, semantic admission, serving retrieval, time calculations and API integration remain pending; see [PROVIDERS.md](PROVIDERS.md). The serving graph below remains the target design.

LangGraph can express both fixed workflows and dynamic agents. This MVP is a bounded adaptive RAG workflow: Luna plans the questions and the graph chooses answer, partial-answer, clarification, or refusal paths. It is not an unrestricted tool-selection loop. See [LangGraph's workflow and agent guide](https://docs.langchain.com/oss/python/langgraph/workflows-agents).

The latest offline preparation adds the opt-in [dependency-context candidate](DEPENDENCY_CONTEXT.md), carrying a dependent target's subject/group and governing source context while preserving explicit overrides and genuine ambiguity. It replaces v9's append on unchanged v8 instructions, with the same schema, source restrictions and draft instructions. Sixty frozen development pairs produce 120 unexecuted packets; 240 historical payloads reproduce exactly and all 96 saved-plan traces remain unchanged. All 1,486 guarded offline tests pass (24 new). This verifies wiring and representability, not improved Luna understanding or retrieval quality. V10 remains unadopted; default serving stays unavailable. Next: a separately authorized, budget-checked bounded comparison and individual semantic review before actual retrieval/draft acceptance. No provider, embedding, index or source-fetch request ran in this preparation.

That bounded [v9/v10 comparison](DEPENDENCY_COMPARISON.md) has now executed at `f805ff9`: 120 exact Luna/OpenAI HTTP-200 one-attempt requests, all strict-valid, 51/60 versus 54/60 literal-valid. Primary language reasoning reviewed 120 plans/182 parts against 34 whole saved Telescope chunks/201 DOM references; the same primary agent reread 40 high-risk plans/76 parts. Admission is 45/60 versus 47/60, with seven gains, five regressions and eight shared failures. **V10 remains unadopted.** Informal page-alias uncertainty is retained separately from confirmed source/context and structural failures. All 1,507 guarded tests pass; source/cache/default preservation is verified. Reported-usage uncached estimate is $0.2185875, while the final observed key allowance is $1.189567745 and billing remains unreconciled. Next is an offline contract clarification for target-local constraint quotes versus inherited reference context, preserving existing fields and all validators. No automatic repair, new judge, further paid comparison, retrieval/draft acceptance or serving adoption follows from these results.

The subsequent [local-constraint clarification](LOCAL_CONSTRAINTS.md) is now prepared as opt-in v11: v10 plus one general append distinguishing target-local constraint quotations from inherited literal reference/query context. Existing schema, complete original coverage, source restrictions, validators and draft instructions are unchanged. Before edits, froze 66 cases and ten explicitly authored alternatives; 132 unexecuted packets differ only in the system append and version. All 66 controls, 360 historical payloads and 120 saved traces reproduce exactly. All ten alternatives pass existing validators while original failures remain rejected. Thirty new offline tests exercise bilingual context, history, overrides, coverage/refusal and owner/private-scope boundaries. This establishes representability and wiring, not Luna semantic improvement. V11 is unadopted; source-selection/ambiguity failures remain. No paid/provider/embedding/index/source-fetch call or default serving change. Next is a separately authorized bounded comparison with a fresh budget observation and individual review, retaining regressions and unresolved cases.

## Ingestion, before serving

```text
Approved public pages -> collect snapshots -> parse source structure
  -> clean -> normalize and format typed blocks with provenance
  -> form variable-length chunks by format and ownership -> validate inputs
  -> Qwen document embeddings -> candidate Qdrant collection
  -> validate coverage and sources -> publish approved snapshot
```

Document embeddings are computed once per changed content/configuration, not on every chat request. The online pipeline embeds only the retrieval queries.

Clean and format before document embedding. Retain doctor profiles, FAQ pairs, section hierarchies, lists, table headers/rows, and time qualifiers as meaningful units. Token counts provide a safety ceiling; they do not dictate default boundaries. See [INGESTION.md](INGESTION.md) for the format-specific policy, oversized-unit handling, and pre-embedding validation gate.

## Implemented offline prototype

[OfflineRagWorkflow](../src/telescope_rag/graph/workflow.py) uses pinned `langgraph==1.2.15` and an acyclic `StateGraph` with explicit conditional edges:

```text
validate_request -> plan_query -> validate_plan
  -> retrieve_evidence -> assemble_evidence -> generate_draft -> validate_draft -> END
  -> finalize_safe -> END (excluded, clarification, unavailable operation or no eligible evidence)
```

The safe branch can follow plan validation or assembly. There is no graph retry/repair loop, durable checkpointer, streaming interface or default live dependency. One request-owned `ExecutionBudget` stays in runtime context outside serializable state and is shared with injected chat/retrieval services. The wrapper disables inherited LangSmith tracing and accepts no caller `RunnableConfig` or callbacks. Its deadline covers async stages; cancellation propagates. Assembly runs in a bounded worker: cancelling the await cannot forcibly terminate a counter already running in that thread.

The [closed planner and draft schemas](../src/telescope_rag/graph/contracts.py) have required nullable properties and forbid extras. The app issues part IDs after validating original character-span coverage, literal history links and source handles. The planner receives the unchanged question/history and a bounded server manifest; source handles are resolved only against the supplied pinned catalog. These literal/schema checks do not establish that the proposed semantic decomposition or intended use is correct. Graph tests use authored synthetic plans; actual development screens found numeric-span, negation and purpose-separation failures, so natural-language planning is not accepted. The metadata/reasoning candidate remains opt-in outside the default graph.

Search parts use one injected batch retrieval interface with exact snapshot/digest/part membership checks. Dense remains the provisional algorithm for later real adapter integration; graph tests use fakes, not live Qdrant or a newly connected dense/embedding service. `read_source` parts read exact complete admitted membership through `EvidenceCatalog`, without arbitrary URL fetching or a search call. Source restrictions apply to declared intended uses and per-part occurrence subsets. Time comparisons currently return `operation_unavailable`, preserving public siblings.

The opt-in `planner_profile="literal_anchors"` uses [AnchoredPlannerReply](../src/telescope_rag/graph/anchoring.py) and [a versioned prompt](../src/telescope_rag/prompts/planner_anchors_v4.py). Each part copies contiguous `original_text` and optional `constraint_quotes` from the original request. The app derives coordinates only from a unique exact match, detecting even overlapping repetitions. It does not normalize text, choose an ambiguous occurrence or repair a model's state/query/source choices. Constraint quotes must be unique and inside their own part; the full original part must remain in a public search query. Existing source/history/nonpublic/full-coverage validation then applies. Longer literal queries are a deliberate input-preservation tradeoff that still needs retrieval evaluation.

Trusted offline construction can explicitly supply `planner_output_tokens` and `draft_output_tokens`; both default to 1,000. The actual allowance remains bounded by the same request's output ledger and settings. This permits a declared reasoning-capacity experiment without disabling reasoning or silently retrying incomplete output. The initial live anchor screen completed and passed targeted review for three contact cases; three mixed questions truncated at 1,000. A separate three-case screen declares 4,096 output tokens and a 30-second provider timeout. These experimental allowances do not change API serving defaults or establish answer acceptance.

That follow-up completed all three plans: Arabic and English pass targeted review, while Jordanian Arabic splits a dependent fee notice into an incorrectly scoped sibling. All three pass literal checks, demonstrating that those checks cannot certify meaning. The v4 experimental prompt adds general dependent-qualifier and explicit-source-attribution instructions; the executed v3 prompt and failures remain preserved. At that preparation checkpoint v4 had not run live and was not an accepted correction. No runtime heuristic reassigns a source or merges model parts.

The later v4 development screen completed all six plans, corrected the Jordanian source assignment and retained the notice, but two Arabic plans also copy an independent eligibility question into a fee-purpose part under broader use. Four targeted cases pass review; the two purpose/context ambiguities remain unaccepted. No draft was generated or reserved case dispatched. The existing schema does not separately expose an answer focus and quoted shared context; original spans and declared uses remain model proposals. [PLANNER_GENERALIZATION.md](PLANNER_GENERALIZATION.md) records the next general correction and experiment; neither literal validation nor the new prompt certifies semantic grounding. Baseline runtime remains unchanged.

The separate opt-in `planner_profile="answer_targets"` reuses the same closed anchor wire schema. Its [v5 prompt](../src/telescope_rag/prompts/planner_targets_v5.py) defines `original_text` as one answer target and existing `reference_text`/`history_indices` as literal interpretation context. The [target binding](../src/telescope_rag/graph/target_context.py) requires a public search to retain the selected reference, without appending or rewriting it; ordinary source/history validation still applies. Draft input exposes `answer_target` separately from `reference_context` with an interpretation-only role, plus the same per-target use, constraints and source-policy eligibility. A versioned draft instruction append asks for only that target to be addressed. `WorkflowRun.answer_targets` preserves request-owned literal receipts. This is explicit representation, not a semantic validator or proof that the model chose the correct target. No new provider schema, judge, source classifier or retrieval loop is added; baseline/v4 behavior remains intact.

The v5 planning screens completed, but semantic acceptance remains pending: five fresh cases fail through false public exclusions or unnecessary doctor clarification. Contiguous targets and inside-target constraints can induce over-restrictive decomposition; the model's stated reasons identify this as a design concern, not an isolated causal proof. Keep owner-specific evidence and shared qualifications explicit without assuming every multi-owner comparison needs separate contiguous questions. No runtime or prompt change was made during the frozen screen, and the candidate is not adopted for serving. The modified draft instructions have no live verification.

The later v6 `policy_targets` experiment corrects public-unknown/excluded and coherent multi-owner state distinctions, but retains two source-selection failures in 36 plans. The opt-in `source_scoped`/v7 profile adds [reviewed directory-role metadata](../src/telescope_rag/knowledge/source_authority.py) through an explicit trusted constructor dependency. Exact primary membership comes from the sealed admission plan and matching directory manifest; derivative title limitations come from existing admitted issue codes. Unclassified sources remain unclassified. This is source metadata, not semantic question routing or factual support. [V7 instructions](../src/telescope_rag/prompts/planner_sources_v7.py) constrain source selection to each target and preserve explicitly requested source authority. Existing `reason` carries a proposed source-selection explanation, not a proof. The output schema, source-policy rules, model/accounting and default graph are unchanged; no app-side source repair or new judge/loop is introduced. New contrasts cover explicitly requested derivative wording as well as main directories and mixed/standalone fee questions. The preparation is superseded by the executed v7 audit below; draft compatibility remains unverified.

Actual v7 execution at `00276f9` corrected the two observed source substitutions/expansions, but was not accepted: 48 attempts, 45 available plans/68 individually reviewed parts, 43 admissions with cautions, three unavailable timeout outputs, one literal-copy/reference failure and one fee-reporting/eligibility classification failure. The latter makes supported fee evidence context-only under the existing policy; literal source membership is insufficient. Same-exposed admission falls 34/36 to 33/36. No source/default graph/retrieval/answer adoption follows. A subsequent unexecuted comparison proposal isolates source-role metadata under the byte-identical v6 instructions; it is a wire preparation, not an implemented serving profile or measured improvement. [PROJECT_STATUS.md](../PROJECT_STATUS.md) records the current gate and exact artifacts.

The separately authorized [paired comparison runner](../scripts/run_metadata_comparison.py) authenticates all 96 frozen packets before dispatch. It uses unchanged v6 instructions/schema/model/reasoning/caps in both arms; reviewed `source_manifest` metadata is the sole input difference. The 48 cases are already exposed development cases, with fixed alternating arm order. Each arm/case has an exclusive result path; a once-only marker prevents replay and fatal protocol/account/model failures stop both arms. Existing provider and literal-validation code is reused without semantic repair or retries. Manual language review remains required for every available proposal, and missing responses remain unassessable. No serving profile, source/index change or reserved-case dispatch is introduced.

The opt-in `planner_profile="purpose_contract"`/v8 addresses two confirmed interface gaps from the offline diagnosis. [Versioned purpose definitions](../src/telescope_rag/graph/purpose_contract.py) describe all eight existing intended uses by the relationship the target asks to establish. [V8 instructions](../src/telescope_rag/prompts/planner_contract_v8.py) distinguish attributed reporting from applicability, specialty, biography, procedure scope, category membership and explanatory service claims. The app does not classify wording or choose a more permissive label. Existing admitted-source restrictions remain authoritative; a wrong label can still cause a semantic failure and requires actual model review. V8 derives from v6 with explicit contract/source instructions, rather than adopting the rejected v7 profile. All older prompt files and the closed wire schema remain intact.

V8 requires explicit reviewed `DirectoryAuthority`, just as v7 does, and matching `SourceBindings(..., purpose_contract=True)`. Its manifest adds `available_source_languages` from actual admitted chunk languages for each document; this is distinct from response language, URL and title. Binding validation rejects a public part whose explicitly selected documents and declared owner/type/language filters have an empty combined catalog intersection. It reports `planner_source_filters_have_empty_intersection` before retrieval/drafting, without removing a filter, changing the query, selecting another source or retrying. Document selections form a union, so compatible subsets remain valid; filters without explicit documents retain existing behavior. Nonempty membership proves neither relevance nor source-policy eligibility nor complete answer support. Older profiles retain their previous validation and byte-identical messages.

The v8 draft receives the same purpose definitions and target/context distinction. It remains an extractive review-only prototype; no semantic judge or automatic relevance guarantee was added. Offline verification froze 24 English/Arabic/Jordanian Arabic development contrasts before edits, reconstructed 96 historical request payloads, and replayed 96 unchanged saved proposals. Exactly one newly rejected combination is the previously diagnosed Arabic filter on a named English page; the prior anchor rejection remains. All 1,364 guarded tests passed, including 39 new checks. Forty-eight comparison packets are prepared locally in `artifacts/m5-purpose-contract-preparation-v1/final/prepared-packets.json` and have not been sent. The live runner allowlist, default graph, API inference boundary, providers, budgets, sources, caches and index are unchanged. This verifies contract mechanics and preservation, not improved Luna semantics or retrieval accuracy. Next: separately authorize a bounded comparison using these frozen packets, review every available plan by meaning against source evidence, and retain unknown/missing outcomes before retrieval/draft acceptance.

That separately authorized comparison has now executed through the [dedicated runner](../scripts/run_purpose_comparison.py) at `6c50998`: 48 one-attempt complete Luna/OpenAI responses, all schema/literal-valid. Primary language reasoning reviewed all 48 plans/60 parts against 43 complete saved Telescope chunks/364 exact DOM references. Conservative admission is 16/24 control versus 22/24 v8, with seven gains, one regression and one shared failure; additional relevance/antecedent findings and noncanonical naming labels are explicit. These exposed-development planning results do not measure retrieval/answer accuracy or generalized robustness. **V8 remains withheld:** C06 English/Jordanian follow-up queries omit the specific service referent while retaining only the page. English regresses relative to control; Jordanian fails both. Source-policy checks cannot infer the missing relationship or prove that a structurally valid quote answers the target.

[Execution details](PURPOSE_COMPARISON.md) cover sealed payload reconstruction, alternating arms, whole-list authentication, no retries and replay refusal. The shared screen functions support v8 while the generic CLI's old fixture/profile allowlist remains unchanged. All 1,385 guarded offline tests pass, including 21 new dispatch tests. Source data/caches, providers/budgets, default graph/API and index remain unchanged; actual draft/serving compatibility is unverified. Next is an offline, general correction retaining the necessary entity/service antecedent in each independent query's literal context, without app-side semantic routing or plan repair, before any further authorized live check or retrieval/draft acceptance.

The opt-in `referent_context`/v9 [instruction append](../src/telescope_rag/prompts/planner_referents_v9.py) now implements that offline contract correction. It asks the planner to read each retrieval query independently and retain its necessary literal entity/service/group antecedent using existing reference/history fields. A page handle identifies where; it may not identify which subject within the page is meant. Self-contained targets need no redundant reference, page-only references remain valid when the page itself is the subject, and genuine singular ambiguity requires clarification without dropping clear public siblings. Negated/unrelated neighbors cannot supply a positive referent. This is model guidance, not a new semantic classifier or application-side repair. All literal anchors, fields, source-policy/authority/language checks and v8 draft instructions remain intact; default/earlier profiles remain unchanged.

Offline verification passed 1,410 guarded tests (25 new), reconstructed 144 prior request payloads and replayed all 48 previous outputs. Explicitly authored alternatives for the two observed failures preserve scopes/purposes/unknown method information and restore literal service context; they are not new model responses. Twenty-four broader pre-edit contrasts join the 24 prior cases, producing 96 unexecuted comparison packets with identical non-message fields/source manifests; only system append and prompt_version differ. No provider/index/source/default change or new budget guard occurred. A separately authorized live v8/v9 comparison and individual semantic review remain necessary before adoption; no retrieval/answer accuracy gain is claimed. Full evidence is `artifacts/m5-referent-context-preparation-v1/REPORT.md`.

The authorized v8/v9 comparison subsequently executed at `8c6726d`: **96 exact Luna/OpenAI HTTP-200 attempts**, all strict-valid, 47/48 literal-valid per arm, zero retries. Primary language reasoning reviewed all **96 actual proposals / 136 parts**, with 47 whole saved Telescope chunks and 382 DOM-reference checks. Whole-plan admission is **40/48 v8 versus 42/48 v9**, with three gains, one structural regression and five shared failures. V9 still drops the pore-refinement service from C06 English/Jordanian independent queries; both arms also substitute sparse profiles for inherited main-directory training evidence and fail a Jordanian ambiguous singular history case. **Do not adopt v9 or open reserved evaluation.** The report distinguishes semantic judgments, structural refusal, purpose-label cautions and unmeasured retrieval/answer quality. See [comparison contract](REFERENT_COMPARISON.md) and `artifacts/m5-referent-comparison-v1/REPORT.md`. All 1,431 guarded offline tests pass; sources/caches/executed code/default serving are preserved. Current-price reported-usage estimate is $0.1659257; aggregate billing initially lagged. No local input-budget guard or further paid step follows automatically. Next is offline consumer-path diagnosis of source/context inheritance and referent ambiguity using saved failures, before choosing a general correction.

The subsequent [offline consumer diagnosis](REFERENT_DIAGNOSIS.md) replays all 96 actual plans and reviews 62 explicit local fixture outcomes, including all 14 withheld plans. It confirms that full request/history context reaches drafting, while missing independent-query context and wrong profile scopes are not repaired. Training cards remain available in the main source; sparse profile scopes exclude them. Authentic but irrelevant service/footer quotes can pass structural checks; exact quotation is not entailment. Drafting cannot borrow sibling citation capabilities or reclassify a supported public part as clarification. Keep these boundaries and semantic-unverified flags intact. Existing fields represent the 14 authored alternatives without changing policies or owners. All 1,462 guarded tests pass (31 new), with no provider, embedding, ranking or index request. The next step is an offline dependency-context correction using exact subject/group plus governing source context and explicit unresolved ambiguity, before any separately bounded live check. V9 and serving remain withheld; no data deletion or source invention is justified by these probes.

The earlier metadata-only comparison completed at `935743d`: 96 strict-valid plans, 95 literal-valid, all 96 proposals/148 parts individually reviewed against saved source evidence. Admissions with cautions are 43/48 control and 44/48 metadata, with only one admission-discordant pair; four treatment plans remain withheld. Unrelated sibling-source scope, source-policy/use mismatch for explicit derivative reporting, an incompatible source-language filter and out-of-target constraints remain. Metadata adds 911 reported input tokens per request. The arm remains unadopted and reserved evaluation stays closed. The next offline correction must clarify the planner/retrieval meaning contract and actual source-language availability while preserving source restrictions; the observed gaps do not establish a causal diagnosis or permit silent source/use repair. See [PROJECT_STATUS.md](../PROJECT_STATUS.md) and the local comparison report for exact evidence and limits.

`WorkflowRun.request_anchors` records app-issued part IDs and exact original/constraint spans after successful plan validation; receipts are request-owned, outside model state and default representations. The draft input additionally exposes each part's original text, state, intended use and literal constraints. A correctly bound quotation still does not establish correct meaning. The prompt asks the model to distinguish actual requested actions from prohibitions and separate independently answerable purposes; scripts do not classify those meanings. Baseline prompts/payloads, normal provider reasoning, source policy and API availability remain unchanged until reviewed adoption.

[Versioned offline prompts](../src/telescope_rag/prompts/offline_v1.py) ask for review-only extractive drafts. Each candidate quotation must equal the complete source `retrieval_text`; shortened qualifiers, invented IDs, hidden sidecar occurrences and sibling citations fail validation. Only the per-part citation IDs actually offered in the counted rendering are accepted; all other exact occurrences remain provenance. A complete-source candidate draft must reference every eligible rendered group. Coverage and source identity are checked, but relevance/entailment remain unverified.

Outputs use `draft_ready`, `not_found`, `out_of_scope`, `clarification_required` or `failed`, with each original part explicit. They never use `answered` or declare supported clinical claims. `offline_only=true`, `semantic_grounding_verified=false` and `luna_compatibility_verified=false` remain mandatory. The full provenance sidecar, stage events and content-free budget receipts accompany the offline result. Construction refuses production settings. Trusted injected services retain their own capabilities; dependency injection alone does not prove an arbitrary service is offline.

The normal path has one planning and one draft logical chat stage; all-nonpublic/no-eligible-evidence paths stop earlier. Normal Luna chat records provider usage after dispatch without requiring a local count. Explicit strict chat still requires complete messages/schema/history/render/metadata counting; the assembler's Qwen count is only a retrieval-render ceiling. No synthetic count is presented as Luna usage. FastAPI still returns `503`; mock successes do not enable chat or establish production readiness.

## Planned serving request graph

```mermaid
flowchart TD
    Start([START]) --> Validate[Validate input and local privacy boundary]
    Validate -->|Invalid or sensitive blocked request| Early[Validation or scope response]
    Validate -->|Accepted| Plan[Luna: scope, references, question plan]
    Plan -->|Ambiguous| Clarify[Ask one clarification]
    Plan -->|Entirely outside scope| Refuse[Scope response]
    Plan -->|Valid public parts| Retrieve[Embed queries and retrieve each part]
    Retrieve --> Evidence[Admit evidence and preserve question ownership]
    Evidence -->|No support| Unknown[State what was not found]
    Evidence -->|Some support| Compute[Resolve evidenced directory and time operations]
    Compute --> Generate[Luna: answer original question with evidence]
    Generate --> Check[Validate structure, coverage and citation references]
    Check -->|Accepted| Result[Return complete or partial result]
    Check -->|Invalid| Safe[Return safe failure or supported deterministic response]
    Early --> End([END])
    Clarify --> End
    Refuse --> End
    Unknown --> End
    Result --> End
    Safe --> End
```

## Node contracts

| Node | Input, responsibility, and result |
| --- | --- |
| `validate_request` | Enforce text/history limits and deadlines; reject unsupported payloads; apply conservative local privacy checks before external calls. |
| `plan_query` | One Luna structured-output call returns language, scope for each part, standalone questions, preserved entity/time constraints, ambiguities, and operation hints. |
| `retrieve_evidence` | Batch-embed eligible queries with Qwen. Read bounded candidates for each question from one pinned approved snapshot. Preserve query IDs and source ownership. |
| `admit_evidence` | Reject disallowed sources, stale time-sensitive data, mismatched identities, or unrelated sections. Mark parts supported, unresolved, conflicting, or excluded. Retrieval similarity alone is not support. |
| `resolve_operations` | For exhaustive listings, read the bounded approved directory manifest. For opening-hour comparisons, compute from evidenced structured intervals; retain source IDs. |
| `generate_answer` | Second Luna call receives the original question, bounded context, all planned parts, admitted evidence, computed results, and missing/excluded parts. Return structured answers and source IDs. |
| `validate_response` | Validate fields, source IDs, supplied quotations where used, citation URLs, question coverage, budgets, and outcome consistency. Render only validated references. |

No separate complexity classifier is needed: a simple question produces one planned question; a compound request produces several. The planner must not answer clinic facts from its own knowledge.

## Planning and decomposition

Each subquestion has an application-issued ID, original request span, standalone retrieval text, explicit entity constraints, scope, requested operation, and ambiguity information. Validate Luna's output with Pydantic and retain the original question unchanged.

Resolve pronouns from supplied context only when the identity is clear. Do not use fuzzy name matching to silently choose between doctors. Preserve comparisons and dependencies: "Which of these doctors performs X?" needs evidence connecting the stated doctors to X, not a generic services page.

If a request cannot fit four subquestions without losing meaning, ask the visitor to narrow it. Never truncate the question list and claim a full answer. Mixed public/private questions may continue with public parts while the excluded parts remain explicit.

## Retrieval and evidence assembly

Use cosine similarity over Qwen vectors, bounded per-question reads, and metadata filtering where the source establishes an identity. Merge repeat hits by chunk ID, then collapse exact repeated formatted evidence within the same literal owner/language/configuration while retaining every source occurrence, citation and question-to-evidence relationship. Shared footer or responsive copies must not consume multiple answer-context slots. Do not merge near matches or let a sibling question's doctor or treatment attribution migrate into another question. This retrieval behavior is M4 work, not implemented by the draft embedding-input manifest.

A complete directory listing uses its validated manifest, not just top-k vector hits. Retrieval can suggest relevant material; completeness and doctor ownership come from the source snapshot and its manifest. Do not claim that absent retrieved evidence proves the website contains no answer.

No paid reranker, query-rewrite retry, or extra answer judge is part of the initial flow. Diagnose observed recall failures through evaluation before adding these dependencies.

The initial offline assembly contract is now implemented in [assembly.py](../src/telescope_rag/retrieval/assembly.py). It accepts already-authored parts and exact admitted source scopes; it does not parse a question or authenticate a caller's intended-use classification. Every original non-whitespace character must belong to a retained request span. Source limitations apply to explicit uses, and output remains candidate evidence with semantic support unassessed. Exact coalescing preserves all occurrence records and per-part source subsets. Full admitted-source membership is separately reported from answer completeness or full-website coverage. Only the returned, fully counted rendering is within its Qwen retrieval budget; serializing its larger provenance sidecar for a model would require a new complete count. The planned online graph, semantic admission and Luna counting are still unimplemented.

## Opening-hours calculations

Clinic hours and public doctor working hours are separate facts. Use `Asia/Amman`; keep UTC timestamps for collection metadata. Use the server clock for "now," not a model's guessed current time.

An admitted hours record contains the source URL/span, applicable clinic or doctor identity, weekday or explicit date, intervals, timezone, publication qualifiers, and any evidenced exceptions. Missing hours are `unknown`, not `closed`. "Friday closed" requires explicit evidence.

When an interval is unambiguous, evaluate `open <= requested_time < close`. Model split shifts and overnight intervals explicitly. An ambiguous "7" requires AM/PM clarification when the answer changes. Explicit dated exceptions take precedence over general weekly hours; do not fabricate holiday exceptions. For date-specific questions, describe what posted general hours establish and whether exceptions are known.

Attribute answers to posted hours, with the snapshot date. Posted hours do not prove actual attendance, that the doors are currently open, or that appointments are available.

## Planned graph state

Store `request_id`, `original_query`, bounded `history`, `language`, validated `subquestions`, `scope_decisions`, `ambiguities`, pinned `snapshot_id`, `evidence_by_question`, `computed_results`, `unresolved_questions`, `draft_answer`, validated `citations`, `outcome`, `usage`, and `deadline`.

Graph state excludes keys, provider client objects, private records, hidden reasoning, and persistent user identifiers. Do not log state wholesale.

## Initial budgets

| Bound | Design default |
| --- | --- |
| Query | 4,000 characters |
| History | Six messages, 8,000 total characters; trim old context before token reservation |
| Subquestions | Four maximum; preserve all accepted request parts |
| Luna stages | Two: planning and generation |
| Retrieval rounds | One |
| Query embeddings | One bounded batch, at most four eligible questions |
| Candidate chunks | Five per question |
| Final evidence | At most 16 chunks and 6,000 tokens |
| Cumulative Luna input | Reported after dispatch in normal chat; 16,000 counted tokens only in explicit strict mode |
| Cumulative output | 2,000 provider output tokens, including reasoning where billed/reported |
| Embedding input | 16,000 tokens across attempts, separately accounted from Luna input |
| Embedding batch | One logical batch of at most 32 texts; graph queries remain bounded to four |
| Overall request deadline | 30 seconds |
| Provider attempt timeout | At most 15 seconds and never beyond remaining deadline |
| Transient retries | Zero for normal chat; at most one for strict chat/embeddings within remaining budgets |

`MAX_LLM_CALLS=2` counts logical stages. Normal reported-usage chat permits at most two physical Luna attempts. Explicit strict chat permits at most four attempts with its counted retry policy; one embedding operation permits at most two attempts. Reserve output for every attempt and input for counted operations. Do not retry a potentially billed ambiguous timeout automatically. Schema-invalid output has no extra LLM repair stage in this phase.

Normal Luna chat uses provider-reported usage after each response and does not require local input-token counting. The 16,000-token input ceiling applies to explicit strict chat, not normal reported-usage chat. Embeddings retain verified counting. Reported-mode chat has no automatic retries; it retains bounded calls/output/deadlines and transport bytes. Missing usage remains unknown and does not stop an otherwise valid answer. Oversized evidence or history must not displace the current question or silently erase unresolved parts. Provider context/truncation errors remain explicit failures. These defaults need evaluation; they are not measured latency or cost guarantees.

M2 implements the provider budget/validation boundary in [PROVIDERS.md](PROVIDERS.md). Share one budget across graph stages; initialization is not permission to infer. Unavailable counting blocks explicit strict chat and embeddings; embedding formatting must be verified/versioned. Unknown normal-chat input remains null, while unknown output and counted operations retain their reservations. Client attempt receipts do not establish hidden upstream activity.

Citation/schema validation does not establish semantic entailment of arbitrary generated prose. See [EVALUATION.md](EVALUATION.md) for the source-grounding review requirement.
