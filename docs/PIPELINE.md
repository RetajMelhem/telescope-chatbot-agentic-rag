# LangGraph pipeline

Status: design only. The flow retains the user's original proposal and adds explicit boundaries, evidence ownership, uncertainty, and time calculations.

LangGraph can express both fixed workflows and dynamic agents. This MVP is a bounded adaptive RAG workflow: Luna plans the questions and the graph chooses answer, partial-answer, clarification, or refusal paths. It is not an unrestricted tool-selection loop. See [LangGraph's workflow and agent guide](https://docs.langchain.com/oss/python/langgraph/workflows-agents).

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

## Request graph

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
| Cumulative Luna input | 16,000 tokens including prompts, history, original question, and evidence |
| Cumulative output | 2,000 provider output tokens, including reasoning where billed/reported |
| Embedding input | 16,000 tokens across attempts, separately accounted from Luna input |
| Embedding batch | One logical batch of at most 32 texts; graph queries remain bounded to four |
| Overall request deadline | 30 seconds |
| Provider attempt timeout | At most 15 seconds and never beyond remaining deadline |
| Transient retries | At most one per provider operation, only within remaining budgets |

`MAX_LLM_CALLS=2` counts logical stages. A transport retry can add a physical request: at most four Luna attempts and two embedding attempts, including retries. Reserve tokens for every attempt; retries do not bypass cumulative limits. Do not retry a potentially billed ambiguous timeout automatically. Schema-invalid output has no extra LLM repair stage in this phase.

Use provider-compatible token accounting and fail conservatively if the tokenizer/count is uncertain. Oversized evidence or history must not displace the current question or silently erase unresolved parts. If sufficient context cannot fit, return clarification or an explicit partial/unknown result. These defaults need evaluation; they are not measured latency or cost guarantees.

M2 implements the provider budget/validation boundary in [PROVIDERS.md](PROVIDERS.md). Share one budget across graph stages; initialization is not permission to infer. Default counting refuses dispatch until a verified compatible profile is supplied, and embedding formatting must be explicitly verified/versioned. Unknown usage retains full attempt reservations; client attempt receipts do not establish hidden upstream activity.

Citation/schema validation does not establish semantic entailment of arbitrary generated prose. See [EVALUATION.md](EVALUATION.md) for the source-grounding review requirement.
