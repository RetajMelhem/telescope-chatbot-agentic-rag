# Provider contracts and verified scope

Status: M2 contracts were implemented offline on 2026-10-14. M3's Qwen embedding preparation and the separately authorized 834-input corpus run passed on 2026-10-15; see the dated evidence below. Initial M5 offline stage schemas/prompts and LangGraph orchestration are implemented. The user has now requested removing the local Luna count gate: normal chat uses provider-reported usage, while embeddings retain verified counting. FastAPI chat still returns `503`; actual model-driven planning/generation, answer acceptance and serving integration remain pending.

## Interfaces and ownership

| Surface | Contract |
| --- | --- |
| `OpenRouterProviders` | Owns one async HTTPX2 client; exposes `chat` and `embeddings`; supports async context management and bounded `aclose()`. Construction/cleanup do not infer. |
| `ChatProvider.complete` | Accepts typed system/user/assistant messages, a required closed Pydantic output model, an explicit output cap, and the request's shared budget. Returns typed output plus attempt receipts. |
| `EmbeddingProvider.embed` | Accepts 1–32 original nonblank texts, query/document role, explicit verified formatting profile, and budget. Returns vectors ordered by input index and receipts. |
| `ExecutionBudget` | One instance for all request stages; new bounded instance per ingestion batch. Enforces calls, attempts, output reservations and deadline. Normal chat records reported input without enforcing a local input-token ceiling; strict chat and embeddings retain counted input ceilings. |
| `TokenCounter` | Trusted injected dependency that returns a selected-model count, versioned profile, and `exact` or `upper_bound` basis for the complete effective input. Includes messages, schema, formatting/instruction, and model framing overhead. |
| `EmbeddingFormat` | Explicit version, query/document prefixes, verification flag and optional pinned provider/reported-model mapping. Formats original text once; does not guess instructions or detect/remove existing prefixes. |
| `ProviderError` | Stable code with optional status/retry timing. Contains no upstream body, key, input, or original exception message. |

Implementation lives in `src/telescope_rag/providers/`: `contracts.py`, `errors.py`, `budget.py`, `validation.py`, and `openrouter.py`. Clients and keys belong to service dependencies, not graph state or public API schemas. Caller-owned Pydantic schemas must forbid extra object fields and require every property, including nested objects. M5's `PlannerReply` and `AnswerDraft` in `graph/contracts.py` satisfy that local schema contract; `prompts/offline_v1.py` is versioned but not a hosted Luna compatibility or quality result.

`OfflineRagWorkflow` passes the same budget to both chat stages and the single injected retrieval batch. Integration tests supply the actual adapter without a local counter and mocked English/Arabic/Jordanian Arabic responses: both stages complete, including with missing usage, preserving exact source quotations. These are mock protocol checks, not hosted semantic acceptance. An explicit strict-mode test retains the old unavailable-counter refusal. Other graph tests charge explicit synthetic reservations through mocked services; their character-based assembly counter and mock usage never establish a model token profile. Source identity/quotation validation cannot replace semantic source grounding.

## Dispatch gates and live-use prerequisites

Normal Luna chat defaults to `CHAT_INPUT_ACCOUNTING=reported_usage`. It does not call a local counter, estimate tokens from characters/bytes, or claim an input reservation. Receipts use `input_reserved=null`, `count_basis=reported_usage_only` and `count_profile=luna-reported-usage-v1`. The adapter records actual reported input/output after the response. Missing input remains unknown in cumulative usage, even if a later stage reports a count; missing output conservatively retains the requested output reservation. Missing usage does not reject an otherwise valid answer or block the second stage. Valid reported input above `MAX_TOTAL_INPUT_TOKENS` is recorded without blocking normal chat; that setting is not an enforced chat-input limit in this mode. Reported totals are not independent billing verification.

`CHAT_INPUT_ACCOUNTING=strict` explicitly retains verified pre-dispatch input accounting, including complete framing/schema overhead or a justified upper bound. Its unavailable default counter refuses dispatch and its reported overruns block later operations. Embeddings always retain the verified counter/format requirements. Neither mode silently converts bytes into token counts.

Embeddings additionally require a verified format profile. Hosted Qwen behavior may differ from local-model instructions; establish whether the endpoint adds an instruction or expects caller text, then pin query/document formatting and dimensions in the snapshot manifest. Prefixes are part of the counted input. Do not mark an assumed or synthetic profile verified for production.

Missing/invalid credentials, invalid inputs/schemas, excessive request bytes, exhausted output/call reservations or deadlines prevent dispatch. Incompatible/unavailable counts block embeddings and explicit strict chat only. Creating a client, setting a key, running metadata checks, or closing the client does not start inference. API integration remains M5 work; its future readiness contract must include approved compatible dependencies.

A live screen must establish the relevant model access, schema behavior and usage contract; embeddings additionally need actual dimensions and formatting/count compatibility. Chat currently requires the reported model to exactly match `openai/gpt-6-luna`; a dated or different ID fails. Embeddings accept absent optional model metadata honestly, and otherwise require the requested identifier or the exact documented identifier bound to a verified provider profile. Other supplied model IDs fail. Never silently add aliases or switch models to get a passing screen.

On 2026-10-16, one authorized synthetic Luna request passed the actual adapter: HTTP 200, provider `OpenAI`, exact reported model, strict one-field JSON, 70 reported input tokens, 16 output tokens, no local counter and no retry. The project dotenv file was unchanged. This verifies that small wire contract only; the real planner/draft schemas, Arabic quality, source-grounded answers and production integration remain unverified. Evidence: `artifacts/m5-reported-usage-v1/live-screen-result.json` and `REPORT.md`. No embedding/index operation ran for this change.

## Verified Qwen embedding profile (2026-10-15)

The public upstream [Qwen model card](https://huggingface.co/Qwen/Qwen3-Embedding-8B) specifies instruction-bearing queries and plain documents. The pinned repository's `config_sentence_transformers.json` supplies this exact query prefix (there is no trailing space after `Query:`):

```text
Instruct: Given a web search query, retrieve relevant passages that answer the query
Query:
```

`qwen_tokenizer.py` pins repository revision `1d8ad4ca9b3dd8059ad90a75d4983776a23d44af`, tokenizer SHA-256 `83cdf8c3a34f68862319cb1810ee7b1e2c0a44e0864ae930194ddb76bb7feb8d`, and `tokenizers==0.22.2`. Loading is local and hash-checked, without model weights, Hub lookup or remote code. Counts include actual special-token post-processing (`<|endoftext|>`, ID 151643), with no padding/truncation. Do not use the tokenizer-config maximum as an endpoint budget. `QwenPreparationCounter` establishes exact upstream counts; its receipt alone makes no hosted claim.

`hosted_qwen_format()` selects `qwen3-8b-openrouter-deepinfra-v1`: empty document prefix, the exact query prefix above, `provider.only=["deepinfra/us"]`, 4,096 dimensions and float vectors. Parameter support remains required and fallbacks disabled. [OpenRouter routing](https://github.com/OpenRouterTeam/docs/blob/main/guides/routing/provider-selection.mdx) documents full endpoint slugs. [DeepInfra's API](https://deepinfra.com/Qwen/Qwen3-Embedding-8B/api) uses Qwen's official identifier, `Qwen/Qwen3-Embedding-8B`; the live response confirms it. This one exact identifier is admitted only on that pinned Qwen embedding route. Receipts retain both requested and reported IDs. Chat has no such mapping.

`QwenEmbeddingCounter` counts the complete already-formatted text array, including the prefix and per-input end token. It refuses chat, different models/dimensions/routes/encoding, added `input_type` or other fields, fallbacks and malformed batches. Its exact count matched hosted reported usage for the synthetic Arabic/English document batch (18 tokens) and query batch (59 tokens); all four returned vectors passed the adapter's dimension/index/finite/nonzero validation. This is a wire/profile compatibility screen, not evidence of clinical answer quality, optimal retrieval, future availability or the backend's undisclosed weight/tokenizer revision.

The first request used an inherited process key and returned 401. The user's explicit `.env` instruction led to a tested credential-priority fix, without editing the file. A subsequent HTTP 200 exposed the exact official model ID (77 reported tokens), then two final role-specific requests passed. Four physical requests were issued with no retries; three returned HTTP 200 with 154 reported input tokens in total. Unknown usage on the rejected request remains unknown. No corpus input or vector file was produced. Content-free receipts are under ignored `artifacts/m3-provider-preparation/`, notably `hosted-verification-v3.json`; the first receipt's local serialization failure was recovered without dispatch.

The separately authorized corpus run used this unchanged profile for 834 distinct document inputs: 53 successful requests, 71,804 reported tokens exactly matching each local reservation, provider `DeepInfra`, requested model `qwen/qwen3-embedding-8b` and reported model `Qwen/Qwen3-Embedding-8B`. No retry/fallback or extra query/chat call ran. All 955 occurrence payloads and normalized vectors were verified in an unpublished local candidate. Receipts: `artifacts/m3-candidate-execution-v6-v1`; authorization/preservation evidence: `artifacts/m3-candidate-authorization-v1`. This establishes that document batch16 responses fit the configured bounds in this run; future query batch32, retrieval quality and backend revision remain unverified. Pricing/accounting observations are point-in-time receipts, not a final invoice.

The embedding adapter still refuses dispatch unless a counter is explicitly supplied. `candidate_qwen_format()` stays unverified. Normal Luna chat no longer requires local counting. Hosted planner/answer acceptance, Qdrant publication and API wiring remain separate work. Keep the local Qwen tokenizer outside Git/Docker; a later container build must supply this exact verified artifact explicitly rather than downloading at API startup.

## Wire and output validation

Chat uses `POST https://openrouter.ai/api/v1/chat/completions`, selected model, unchanged message text, `response_format.type=json_schema`, `strict=true`, `max_completion_tokens`, and `stream=false`. Embeddings use `POST /api/v1/embeddings`, selected Qwen model, a text array, configured dimensions, and `encoding_format=float`. Both require parameter support and disable provider fallbacks. There is no SDK retry, model fallback list, tool call, response-healing plugin, repair call, or extra judge. Injected transports are trusted test/dependency surfaces and must not implement hidden retries.

Responses must be JSON objects within the byte cap. Duplicate keys, malformed/nonfinite JSON, unexpected content types, embedded provider errors, and inconsistent usage fail. Chat requires one assistant choice with `finish_reason=stop`, nonempty JSON content, and strict local schema validation. Refusals, truncation, tool output, missing fields, extra fields, and type mismatches fail without repair/retry.

Embeddings require exactly one result for each submitted input, unique integer indices in range, the exact configured dimension, finite numeric values, and nonzero vectors. Booleans/strings are not numbers. Results may arrive out of order; indices restore original input order. Cleaning, structural chunking, provenance and per-chunk ceiling checks happen before this adapter in M3; batch protocol validation cannot prove source quality.

## Reservations and retry policy

Default request deadline is 30 seconds; each attempt receives the smaller of remaining time and the 15-second provider timeout. Output/attempt capacity is reserved before dispatch. Two logical chat stages permit at most two HTTP attempts in normal reported-usage mode, or four in explicit strict mode with one retry. One embedding batch permits at most two attempts. Setting retries to zero reduces counted-mode ceilings too.

Output is capped at 2,000 requested tokens per request, including reasoning where reported; embedding input is separately capped at 16,000 counted tokens. Strict chat additionally enforces 16,000 counted input tokens across attempts. Normal chat makes no such pre-dispatch input-token guarantee and does not reserve input. Each attempt reserves its requested output cap; valid reported output releases unused capacity, while missing output retains the reservation. Failed/ambiguous normal-chat input remains unknown. Reasoning tokens are a subset of completion tokens, not charged twice. Output overruns still block further operations; strict counted-input overruns do too. Context overflow, refusal, truncation and malformed output remain explicit failures without silent evidence removal.

Normal reported-usage chat performs **zero automatic retries**, independently of the general retry setting. Strict chat and embeddings permit at most one retry for connection establishment failures or HTTP `429`, `502`, and `503`, within deadline/reservations. Other statuses, authentication/credit/model failures, schema/output errors, read/write timeouts, ambiguous transport failures, and HTTP `504` are not retried. An eligible retry respects numeric finite nonnegative `Retry-After`; it must fit the deadline. Without that header, delay defaults to 0.1 seconds. Cancellation propagates, closes an active response, and records the attempt; shutdown has a five-second default deadline. One request cannot mix strict and reported-only chat accounting reservations.

Receipts contain operation/attempt ordinals, requested/reported model and provider metadata, HTTP status, outcome, reservation/count profile, and reported usage. They contain no messages, output text, vectors, key, upstream body, or hidden reasoning. They describe application-observed HTTP attempts, not unreported upstream routing, billing totals, or hidden provider work.

## Settings and verification

`httpx2` is a runtime dependency pinned in `uv.lock`. New settings have defaults, so the user's existing `.env` need not be changed:

| Setting | Default |
| --- | --- |
| `CHAT_INPUT_ACCOUNTING` | `reported_usage` |
| `PROVIDER_MAX_REQUEST_BYTES` | 262,144 |
| `PROVIDER_MAX_RESPONSE_BYTES` | 2,000,000 |
| `PROVIDER_RETRY_DELAY_SECONDS` | 0.1 |
| `MAX_EMBEDDING_CALLS` | 1 |
| `MAX_EMBEDDING_INPUT_TOKENS` | 16,000 |
| `MAX_EMBEDDING_BATCH_SIZE` | 32 |

Offline tests exercise bilingual wire preservation, strict parsing, refusal/truncation, retry limits/statuses, transport ambiguity, reservations and unknown usage, model mismatch, batch/index/dimension/vector errors, deadlines, cancellation, response bounds, safe logs/errors, and bounded cleanup. They use synthetic keys/counts/formats and mocked HTTP; no account, corpus, latency, grounding, or deployment claim follows from their success. Exact checks and next steps are in [PROJECT_STATUS.md](../PROJECT_STATUS.md).

## Historical strict-counting preparation

The following captures and count-gate findings describe the earlier strict policy. They are preserved evidence, not a current normal-chat requirement. The capture utility now explicitly selects strict mode so that rerunning it can never become a live call after the default changes. Earlier manifests still bind their original code versions; changed runtime bindings require a new execution/preparation record, not editing an old frozen manifest.

[prepare_luna_screen.py](../scripts/prepare_luna_screen.py) captures the actual `openai/gpt-6-luna` Chat Completions payload, including both messages, the entire strict output schema, provider parameters and output cap. It uses explicit default settings, `_env_file=None`, a synthetic credential, retries zero, an always-rejecting full-input counter and an independently forbidden mock HTTP transport. It cannot execute a paid screen. Payload artifacts contain public evidence and synthetic questions; credentials and headers are absent.

After the planning adapter rejects counting, an explicitly labelled authored plan allows offline traversal into evidence assembly. Selected witness IDs are an oracle, not measured retrieval. Qwen counts only the full retrieval rendering. The draft adapter then rejects counting too, so no answer model runs. Oracle planning charges zero; actual planning usage may change the later output reservation. Captured draft input is a concrete compatibility fixture, not a token reservation or a future byte-identical live conversation.

```powershell
& .\.tools\uv\bin\uv.exe run --locked python -m scripts.prepare_luna_screen --cases artifacts/m5-planner-cases-v1/cases.jsonl --bundle data/processed/m3-llm-semantic-token-validated-v6 --prepared-digest a46be2d3fd18f11d46c79ff9bc992de22aab496836894a708bc57c1e8b48af88 --tokenizer .tools/qwen-tokenizer/1d8ad4ca9b3dd8059ad90a75d4983776a23d44af/tokenizer.json --output artifacts/NEW_LUNA_WIRE_PREPARATION
```

The dated run captured 48 payloads across 24 cases, with zero HTTP attempts and unknown Luna input counts/cost. Serialized byte bounds are transport checks, not tokens. Source bundle digest and exact case inputs are bound; output directories must be new. No credential, endpoint, model or execute option is exposed by this script.

As checked on 2026-10-16, [OpenAI's Luna model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna) lists structured-output support, while [OpenAI's counting guide](https://developers.openai.com/api/docs/guides/token-counting) describes counting the complete Responses input through `/v1/responses/input_tokens`. The project's [OpenRouter Chat Completions route](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion) is a separate wire contract. These documents do not establish a compatible counter for the project's exact messages/schema/route. No Responses-to-Chat equivalence, tokenizer mapping, character-based upper bound, model substitution or provider compatibility has been assumed. The default unavailable counter remains unchanged.

That earlier counting gate is superseded for normal chat by the user's reported-usage policy change. Local exact counting is optional future strict-mode work. Next is hosted Luna compatibility and model-driven bilingual planner evaluation, followed by source-faithful answer acceptance and actual retrieval integration. Normal chat still rejects refusal, truncation, incorrect model/schema and mismatched citations without a repair loop. Published key limits and request/output bounds are separate controls; reported usage is not a pre-dispatch spending quote or a new per-run dollar cap.
