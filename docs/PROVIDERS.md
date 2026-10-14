# Provider contracts and verified scope

Status: M2 implemented with offline HTTP fixtures on 2026-10-14. No authenticated inference was performed. FastAPI chat still returns `503`; stage prompts, graph orchestration, and ingestion are later milestones.

## Interfaces and ownership

| Surface | Contract |
| --- | --- |
| `OpenRouterProviders` | Owns one async HTTPX2 client; exposes `chat` and `embeddings`; supports async context management and bounded `aclose()`. Construction/cleanup do not infer. |
| `ChatProvider.complete` | Accepts typed system/user/assistant messages, a required closed Pydantic output model, an explicit output cap, and the request's shared budget. Returns typed output plus attempt receipts. |
| `EmbeddingProvider.embed` | Accepts 1–32 original nonblank texts, query/document role, explicit verified formatting profile, and budget. Returns vectors ordered by input index and receipts. |
| `ExecutionBudget` | One instance for all request stages; new bounded instance per ingestion batch. Enforces logical calls, physical attempts, separate chat/embedding input totals, cumulative output, and deadline. |
| `TokenCounter` | Trusted injected dependency that returns a selected-model count, versioned profile, and `exact` or `upper_bound` basis for the complete effective input. Includes messages, schema, formatting/instruction, and model framing overhead. |
| `EmbeddingFormat` | Explicit version, query/document prefixes, and verification flag. Formats original text once; does not guess instructions or detect/remove existing prefixes. |
| `ProviderError` | Stable code with optional status/retry timing. Contains no upstream body, key, input, or original exception message. |

Implementation lives in `src/telescope_rag/providers/`: `contracts.py`, `errors.py`, `budget.py`, `validation.py`, and `openrouter.py`. Clients and keys belong to service dependencies, not graph state or public API schemas. Caller-owned Pydantic schemas must forbid extra object fields and require every property, including nested objects. Stage-specific schemas and prompts are M5 work.

## Dispatch gates and live-use prerequisites

The default counter raises `token_count_unavailable` before HTTP dispatch. This is deliberate: byte/character lengths and an unverified tokenizer cannot establish model-token budgets. A test counter is not a production counter. Before live use, verify and pin a compatible local counting profile, including framing/schema overhead or a justified upper bound. Reported input above the reservation blocks the budget immediately; it cannot retroactively prevent that dispatch's upstream spend.

Embeddings additionally require a verified format profile. Hosted Qwen behavior may differ from local-model instructions; establish whether the endpoint adds an instruction or expects caller text, then pin query/document formatting and dimensions in the snapshot manifest. Prefixes are part of the counted input. Do not mark an assumed or synthetic profile verified for production.

Missing/invalid credentials, incompatible/unavailable counts, unverified formatting, invalid inputs/schemas, excessive request bytes, or exhausted reservations/deadlines prevent dispatch. Creating a client, setting a key, running health checks, or closing the client does not start inference. API integration remains M5 work; its future readiness contract must include approved compatible dependencies.

A separately authorized minimal live screen must establish account/model access, strict-schema behavior, reported model IDs, usage fields, actual dimensions, and formatting/count compatibility. Chat currently requires the reported model to exactly match `openai/gpt-6-luna`; a dated or different ID fails. Embeddings accept absent optional model metadata honestly, but reject a supplied different model. Never silently add aliases or switch models to get a passing screen.

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
