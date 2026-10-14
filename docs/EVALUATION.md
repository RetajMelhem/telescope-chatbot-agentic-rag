# Evaluation and acceptance

Status: M1 configuration/API tests are implemented and verified offline. RAG, real-source, live provider, Qdrant, and deployment evaluation remain future work. Current results are recorded in [PROJECT_STATUS.md](../PROJECT_STATUS.md).

## Offline checks first

Unit tests use synthetic/source fixtures and verify pure behavior. Integration tests use mocked OpenRouter responses and a fake retrieval adapter unless a local database check is explicitly being exercised. No provider requests are implicit in `pytest` or the existence of an API key.

M1 tests use synthetic settings and fake knowledge probes, never the user's `.env`. External socket connections are blocked; loopback/Unix sockets remain available for event-loop internals on Windows and other platforms. No live local service is used by the test suite. The current tests cover configuration, startup/lifecycle, health readiness, chat schema rejection, bilingual input transport, body limits, deadlines, CORS, diagnostic exposure, and safe error/log behavior. They do not verify Arabic understanding or RAG answer quality.

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

Keep evaluation fixtures separate from live knowledge and prompts. Do not introduce case-specific runtime rules to pass a benchmark.

Before approving the chunking policy in M3/M4, compare structure-aware chunks with a bounded fixed-window baseline using the same source snapshot, embedding model, retrieval budget, and bilingual questions. Review retained facts, exact source mapping, doctor/FAQ/table integrity, relevant-evidence recall, supported answers, embedding input count, and cost. No strategy is the proven best for this corpus before that comparison. A semantic/LLM chunker is a later candidate only if a measured gap justifies its complexity.

## Metrics and release criteria

Track per-question retrieval recall against known source spans, attribution correctness, completeness of addressed request parts, citation validity, source support of generated claims, correct uncertainty, public/private boundary behavior, latency, physical provider attempts, and token usage.

All mandatory boundary, attribution, citation-reference, and deterministic-hours cases must pass. Every answer in the curated release set must be reviewed for source support, and all requested parts must be represented. Report failures rather than averaging a harmful attribution error into a favorable score.

Structural validators can check IDs, URLs, quotations, and coverage fields, but cannot prove the meaning of every paraphrase. Semantic grounding needs fixture-based review and clinic review of public facts. No second LLM judge is required for the initial design.

Performance targets need measurements on the chosen model/provider and deployment. The 30-second request deadline is a limit, not a success-time promise. Record latency and cost observations without treating documentation or mocked tests as live acceptance.

## Live compatibility screen

When live requests are explicitly authorized, run a small bounded screen for Luna structured planning, answer output, Qwen batch/index mapping, actual embedding dimensions, and Arabic/English retrieval. Record selected model/provider, configuration, schema, usage, errors, and the index snapshot. Do not send patient records or retain raw visitor conversations.

Separate live provider compatibility from source completeness and final production acceptance. No live screen has been executed in this foundation stage.
