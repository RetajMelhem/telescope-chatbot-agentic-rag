# Provider contracts and verified scope

Status: M2 contracts were implemented offline on 2026-10-14. M3's Qwen embedding preparation and the separately authorized 834-input corpus run passed on 2026-10-15; see the dated evidence below. Initial M5 offline stage schemas/prompts and LangGraph orchestration are now implemented. FastAPI chat still returns `503`; Luna compatibility/counting, actual model-driven planning/generation and serving integration remain pending.

## Interfaces and ownership

| Surface | Contract |
| --- | --- |
| `OpenRouterProviders` | Owns one async HTTPX2 client; exposes `chat` and `embeddings`; supports async context management and bounded `aclose()`. Construction/cleanup do not infer. |
| `ChatProvider.complete` | Accepts typed system/user/assistant messages, a required closed Pydantic output model, an explicit output cap, and the request's shared budget. Returns typed output plus attempt receipts. |
| `EmbeddingProvider.embed` | Accepts 1–32 original nonblank texts, query/document role, explicit verified formatting profile, and budget. Returns vectors ordered by input index and receipts. |
| `ExecutionBudget` | One instance for all request stages; new bounded instance per ingestion batch. Enforces logical calls, physical attempts, separate chat/embedding input totals, cumulative output, and deadline. |
| `TokenCounter` | Trusted injected dependency that returns a selected-model count, versioned profile, and `exact` or `upper_bound` basis for the complete effective input. Includes messages, schema, formatting/instruction, and model framing overhead. |
| `EmbeddingFormat` | Explicit version, query/document prefixes, verification flag and optional pinned provider/reported-model mapping. Formats original text once; does not guess instructions or detect/remove existing prefixes. |
| `ProviderError` | Stable code with optional status/retry timing. Contains no upstream body, key, input, or original exception message. |

Implementation lives in `src/telescope_rag/providers/`: `contracts.py`, `errors.py`, `budget.py`, `validation.py`, and `openrouter.py`. Clients and keys belong to service dependencies, not graph state or public API schemas. Caller-owned Pydantic schemas must forbid extra object fields and require every property, including nested objects. M5's `PlannerReply` and `AnswerDraft` in `graph/contracts.py` satisfy that local schema contract; `prompts/offline_v1.py` is versioned but not a hosted Luna compatibility or quality result.

`OfflineRagWorkflow` passes the same budget to both chat stages and the single injected retrieval batch. An integration test supplies the actual OpenRouter adapter with its default unavailable counter and a mocked transport: planning fails before any HTTP dispatch. Other graph tests charge explicit synthetic reservations through mocked services. Their character-based assembly counter and mock usage are clearly synthetic and never establish a model token profile. Source identity/quotation validation cannot replace semantic source grounding.

## Dispatch gates and live-use prerequisites

The default counter raises `token_count_unavailable` before HTTP dispatch. This is deliberate: byte/character lengths and an unverified tokenizer cannot establish model-token budgets. A test counter is not a production counter. Before live use, verify and pin a compatible local counting profile, including framing/schema overhead or a justified upper bound. Reported input above the reservation blocks the budget immediately; it cannot retroactively prevent that dispatch's upstream spend.

Embeddings additionally require a verified format profile. Hosted Qwen behavior may differ from local-model instructions; establish whether the endpoint adds an instruction or expects caller text, then pin query/document formatting and dimensions in the snapshot manifest. Prefixes are part of the counted input. Do not mark an assumed or synthetic profile verified for production.

Missing/invalid credentials, incompatible/unavailable counts, unverified formatting, invalid inputs/schemas, excessive request bytes, or exhausted reservations/deadlines prevent dispatch. Creating a client, setting a key, running health checks, or closing the client does not start inference. API integration remains M5 work; its future readiness contract must include approved compatible dependencies.

A separately authorized minimal live screen must establish account/model access, strict-schema behavior, reported model IDs, usage fields, actual dimensions, and formatting/count compatibility. Chat currently requires the reported model to exactly match `openai/gpt-6-luna`; a dated or different ID fails. Embeddings accept absent optional model metadata honestly, and otherwise require the requested identifier or the exact documented identifier bound to a verified provider profile. Other supplied model IDs fail. Never silently add aliases or switch models to get a passing screen.

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

The default provider constructor still refuses dispatch unless a counter is explicitly supplied. `candidate_qwen_format()` stays unverified. Luna counting/strict-schema verification, query embedding evaluation, Qdrant publication and API wiring remain separate work. Keep the local tokenizer outside Git/Docker; a later container build must supply this exact verified artifact explicitly rather than downloading at API startup.

## Wire and output validation

Chat uses `POST https://openrouter.ai/api/v1/chat/completions`, selected model, unchanged message text, `response_format.type=json_schema`, `strict=true`, `max_completion_tokens`, and `stream=false`. Embeddings use `POST /api/v1/embeddings`, selected Qwen model, a text array, configured dimensions, and `encoding_format=float`. Both require parameter support and disable provider fallbacks. There is no SDK retry, model fallback list, tool call, response-healing plugin, repair call, or extra judge. Injected transports are trusted test/dependency surfaces and must not implement hidden retries.

Responses must be JSON objects within the byte cap. Duplicate keys, malformed/nonfinite JSON, unexpected content types, embedded provider errors, and inconsistent usage fail. Chat requires one assistant choice with `finish_reason=stop`, nonempty JSON content, and strict local schema validation. Refusals, truncation, tool output, missing fields, extra fields, and type mismatches fail without repair/retry.

Embeddings require exactly one result for each submitted input, unique integer indices in range, the exact configured dimension, finite numeric values, and nonzero vectors. Booleans/strings are not numbers. Results may arrive out of order; indices restore original input order. Cleaning, structural chunking, provenance and per-chunk ceiling checks happen before this adapter in M3; batch protocol validation cannot prove source quality.

## Reservations and retry policy

Default request deadline is 30 seconds; each attempt receives the smaller of remaining time and the 15-second provider timeout. The budget is reserved before dispatch. Two logical chat stages permit at most four HTTP attempts; one embedding batch permits at most two. Setting retries to zero reduces these ceilings.

Luna input is capped at 16,000 tokens across all attempts, output at 2,000 including reported reasoning within completion tokens, and embedding input separately at 16,000. Each attempt reserves its complete counted input and requested output cap. Complete validated usage releases unused reservation; missing/partial/malformed usage, failed HTTP requests, timeout, and cancellation conservatively retain the full reservation. No receipt invents absent usage. Reasoning tokens are a subset of completion tokens and are not charged twice. A reported overrun blocks every subsequent operation on that budget.

At most one retry is eligible for connection establishment failures or HTTP `429`, `502`, and `503`, within the remaining deadline and fresh reservations. Other statuses, authentication/credit/model failures, schema/output errors, read/write timeouts, ambiguous transport failures, and HTTP `504` are not retried. An eligible response's numeric finite nonnegative `Retry-After` is respected; if it does not fit the deadline, no retry occurs. Unrecognized/date-form timing is not guessed or shortened. Without that header, delay defaults to 0.1 seconds. Cancellation propagates, closes an active response, and records the attempt; shutdown has a five-second default deadline.

Receipts contain operation/attempt ordinals, requested/reported model and provider metadata, HTTP status, outcome, reservation/count profile, and reported usage. They contain no messages, output text, vectors, key, upstream body, or hidden reasoning. They describe application-observed HTTP attempts, not unreported upstream routing, billing totals, or hidden provider work.

## Settings and verification

`httpx2` is a runtime dependency pinned in `uv.lock`. New settings have defaults, so the user's existing `.env` need not be changed:

| Setting | Default |
| --- | --- |
| `PROVIDER_MAX_REQUEST_BYTES` | 262,144 |
| `PROVIDER_MAX_RESPONSE_BYTES` | 2,000,000 |
| `PROVIDER_RETRY_DELAY_SECONDS` | 0.1 |
| `MAX_EMBEDDING_CALLS` | 1 |
| `MAX_EMBEDDING_INPUT_TOKENS` | 16,000 |
| `MAX_EMBEDDING_BATCH_SIZE` | 32 |

Offline tests exercise bilingual wire preservation, strict parsing, refusal/truncation, retry limits/statuses, transport ambiguity, reservations and unknown usage, model mismatch, batch/index/dimension/vector errors, deadlines, cancellation, response bounds, safe logs/errors, and bounded cleanup. They use synthetic keys/counts/formats and mocked HTTP; no account, corpus, latency, grounding, or deployment claim follows from their success. Exact checks and next steps are in [PROJECT_STATUS.md](../PROJECT_STATUS.md).
