# Project status

Last updated: 2026-10-14 (Asia/Amman).

Current milestone: **M2 provider contracts/adapters implemented and verified offline. M3 public website ingestion is next.**

This is the continuity entry point for Codex. Read it before substantive work and update it after each completed task. The full roadmap is [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md); repository rules are in [AGENTS.md](AGENTS.md).

## Confirmed project scope

FastAPI + LangGraph; GPT-6 Luna through OpenRouter; Qwen3 Embedding 8B; Arabic, English, and everyday Jordanian Arabic; answers supported by public clinic website content. Public doctor working hours are in scope when published. Patient files, record edits, private calendars, appointment availability, and bookings are excluded. Docker deployment is required in a later milestone.

## Completed foundation work

- [x] Product specification and representative answer behavior.
- [x] Folder architecture and empty implementation directories.
- [x] LangGraph request pipeline, ingestion pipeline, budgets, citations, and uncertainty behavior.
- [x] Website ingestion, provenance, directory coverage, hours records, and index lifecycle design.
- [x] FastAPI request/response and health contract.
- [x] Docker deployment design and future runbook.
- [x] Offline evaluation cases and release criteria.
- [x] Milestone roadmap and decision/open-item records.
- [x] Canonical `AGENTS.md`; redundant `agent.md` removed.
- [x] Living progress file with required Codex updates.
- [x] `.env.example`, local `.env` with empty key fields, Git exclusions, and Docker exclusions.
- [x] Final document, directory, example-schema, and configuration consistency checks.

## Milestones

| Milestone | Actual status |
| --- | --- |
| M0 — specification/scaffold | Complete; foundation consistency checks passed |
| M1 — FastAPI/configuration shell | Complete; offline checks and local server smoke passed |
| M2 — provider contracts | Complete for initial offline implementation; live compatibility remains gated |
| M3 — public website ingestion | Implementation not started; structural cleaning/chunking policy revised |
| M4 — retrieval and deterministic operations | Not started |
| M5 — LangGraph chat flow | Not started |
| M6 — Docker implementation/verification | Not started |
| M7 — source acceptance/widget integration | Not started |

## Completed M1 implementation

- [x] Python package metadata, `uv.lock`, local `.venv`, and supported app factory entry point.
- [x] Validated environment/dotenv settings with masked secrets, consistent bounds, and process-environment precedence.
- [x] `/health/live` and bounded `/health/ready`, with injected knowledge probe and unavailable default adapter.
- [x] Chat request schemas that reject runtime configuration, invalid roles/types, and oversized input; valid requests return `503` until M5.
- [x] Application-issued request IDs, body-size limits, deadline cancellation, CORS, safe error envelopes, and content-free application logs.
- [x] Lifecycle cleanup and production diagnostic-doc suppression.
- [x] Synthetic-settings and fake-probe tests; local loopback-only Uvicorn startup check; updated run instructions.

## Verification and evidence

Completed: current target/parent folder inspection, confirmation that the target did not exist before this task, limited public website inspection, current primary technology references, and creation of the scaffold.

Foundation consistency verification passed on 2026-10-14:

- 13 Markdown files and 16 implementation/data directories with placeholders match the inventory.
- All 30 local document links resolve after the final status update; code fences are balanced; both JSON contract examples parse.
- 27 example configuration values match the planned models, timezone, and budgets; example secret fields are empty.
- Git/Docker environment exclusions are present; tracked examples contain no detected OpenRouter key pattern. Local `.env` values were not read or printed by verification.
- `AGENTS.md` references this progress file; redundant `agent.md` is absent.
- At M0 completion, runtime Python files, Dockerfile, and application tests were absent; M1 subsequently implemented the API shell and tests.

M1 verification on 2026-10-14:

- `uv lock --check`: passed; Python 3.11.9 and 30 locked packages.
- `uv run --locked ruff check .`: passed.
- `uv run --locked ruff format --check .`: passed.
- `uv run --locked pytest`: 56 passed. External connections are blocked; loopback/Unix sockets are allowed for Windows/event-loop internals. Tests use no live local services, real provider keys, or the user's `.env`.
- Temporary Uvicorn server on `127.0.0.1` with an ephemeral port: liveness `200`, readiness `503`, valid chat `503`; request IDs matched JSON/headers. Server shut down after the check.
- Configuration example and documentation consistency checks: completed during handoff verification.

The first test run exposed Starlette's HTTPX2 requirement and Windows asyncio's need for a local socketpair; both were resolved before the final passing suite. Dependency versions are recorded in `uv.lock`, not inferred from older notes.

No provider inference, embeddings, full crawl, index creation, live Qdrant request, Docker build, or public deployment has run. The API shell works locally; there is no working RAG chatbot yet. Existing `.env` was not rewritten or printed.

## Latest revision: data preparation and Git

- [x] Replaced the fixed token-target/overlap design with variable-length chunks that follow doctor/FAQ/section/list/table structure and source ownership.
- [x] Made the mandatory pre-embedding sequence explicit: snapshot, structural parsing, cleaning, normalization/formatting, structural chunking, provenance/input validation, then embedding.
- [x] Retained a 1,200-token safety ceiling, including context, with recursive splitting inside a unit and recorded gaps for unsegmentable inputs. This is a design default, not a proven optimal size.
- [x] Added `CHUNKING_STRATEGY=structure_aware` and `CHUNK_MAX_TOKENS`; existing target/overlap settings are accepted only for compatibility and excluded from active serialized settings. Local `.env` was preserved.
- [x] Added M3/M4 structural-integrity checks and a controlled comparison against a fixed-window baseline. The baseline is for evaluation, not the default serving policy.
- [x] Initialized a local Git repository on `main`; baseline checkpoint is `e940884`. The revision is kept as a separate local checkpoint; use `git log -2 --oneline` and scoped diffs to inspect it. No remote is configured.
- [x] Added `.gitattributes` for consistent source line endings and verified Git ignores `.env`, local environments/tools, and generated data.

Revision verification on 2026-10-14: 60 offline tests passed; Ruff lint/format, lockfile validation, staged-source/secret-exclusion review, documentation/configuration consistency, and Git whitespace checks passed. This verifies settings compatibility and the design handoff; it does not establish chunk quality or real-source retrieval performance. The cleaner/chunker and corpus comparison remain unimplemented.

## Known gaps and blockers

- No implementation blocker for M3's local extraction/cleaning/chunking fixtures.
- Friday/clinic opening hours are not verified by the limited website inspection. Never invent them; complete ingestion must establish what is actually published.
- Provider account access, hosted structured-output behavior, returned model IDs/dimensions, token-count compatibility, and Qwen formatting remain unverified. Default counting refuses dispatch; synthetic test profiles are not production profiles.
- Hosting, widget integration, refresh cadence, and content-review ownership remain decisions for later milestones.

## Completion audit and M2 readiness

Audit date: 2026-10-14. Reviewed the current tracked implementation, settings, tests, specifications, milestone boundaries, Git exclusions, and package output. The initial tree was clean at `b6a0e0e` and the existing 60 tests passed. This audit does not rely on older project readiness notes.

Concrete issues fixed and regression-tested:

- Middleware-generated body-limit, timeout, and unexpected-error responses now retain CORS headers only for configured allowed origins.
- API `405` errors preserve the `Allow` header. The API contract now explicitly distinguishes standard plain-text CORS preflight transport responses from JSON application errors.
- Adapter cleanup now has a configurable five-second default deadline and fixed, content-free timeout/failure warning events.
- Settings reject incorrect OpenRouter API paths and ports; the approved HTTPS `/api/v1` base accepts an optional trailing slash.

Verified audit results:

- 74 offline tests passed, including new boundary/shutdown/URL cases; Ruff lint and formatting passed.
- `uv lock --check` passed; 30 locked packages remain unchanged. A wheel built successfully and includes the app factory/configuration, with no local `.env`, tests, generated corpus, or tool environment.
- Current local configuration validated without displaying its values. Existing `.env` was preserved; the new shutdown setting has a default and does not require rewriting it.
- Temporary localhost Uvicorn smoke passed: liveness `200`, knowledge readiness `503`, valid chat placeholder `503`; issued request IDs match headers/JSON. The server shut down after the check.
- All 38 local documentation links resolved at final handoff, including the M2 deliverables anchor; JSON examples/fences, 44 active example settings, deprecated-setting exclusions, and secret-free example values checked.
- Git ignores secrets, environments/tools, generated corpus, and distribution artifacts; Docker exclusions now also include build/distribution artifacts. No remote or paid provider request was involved.

Decision: **no remaining blocker found for M2's offline provider-contract implementation**. M0/M1 and the revised ingestion specification are ready inputs. Provider account compatibility, actual returned embedding dimensions, source coverage, cleaner/chunker quality, Qdrant enforcement, RAG answers, and Docker release remain unverified future milestones; they are not claimed complete by this audit.

## Completed M2 implementation

- [x] Typed chat/embedding interfaces, safe errors, explicit count/format profiles, and content-free attempt receipts.
- [x] Async OpenRouter HTTP adapters using runtime HTTPX2, injected mock transport, fixed selected models, strict JSON schemas, parameter-support routing, and disabled fallbacks/hidden retries.
- [x] Strict local JSON/schema/usage validation; refusal/truncation handling without repair; exact embedding batch/index/dimension checks and finite nonzero vectors restored to input order.
- [x] Shared logical-call/HTTP-attempt/input/output/deadline budget; fresh reservation before every attempt; unknown/partial usage keeps full reservations; reasoning is not double charged; usage overrun blocks further dispatch.
- [x] At most one eligible retry, no retry for ambiguous read/write timeout, cancellation propagation, response byte limits, and bounded client cleanup.
- [x] Default unavailable token counter and unverified embedding format prevent dispatch. Production counting/format verification is explicitly deferred to the authorized compatibility screen, not guessed.
- [x] Provider settings/defaults, dependency lock, architecture/pipeline/ingestion/Codex instructions, and [provider contract documentation](docs/PROVIDERS.md) synchronized.

M2 offline verification on 2026-10-14: **180 tests passed**, including all 74 API/configuration regressions and 106 new provider cases. Ruff lint/format and `uv lock --check` passed; HTTPX2 was promoted from development to runtime without changing the 30-package lock inventory. Synthetic credentials/counts/formats and HTTP fixtures were used; no paid request or user's key was used by tests. The first provider run had two invalid synthetic settings fixtures; those were corrected without relaxing application settings validation.

`uv build --offline` built the source distribution and wheel successfully. The wheel includes provider modules and runtime HTTPX2 metadata, with no local secrets, tests, data, or tools. All 46 local document links/anchors, 14 Markdown files' fences, and two JSON examples validated; all 50 active example settings match defaults, and local configuration validates without disclosure. Git whitespace/exclusion and scoped staged-source checks passed. Existing `.env` was preserved. No remote was configured or used.

The API remains a shell: readiness is unavailable by default and valid chat returns `503`. No complete crawl, cleaner/chunker, Qdrant index, graph, Docker build, or deployment has run. Existing `.env` was preserved. Mock results establish local protocol/budget behavior, not live compatibility, token accuracy, source quality, or chatbot grounding.

## Next concrete step

Implement **M3 public website ingestion**, starting with typed source/block/chunk models and local HTML fixtures. Build the sequence: immutable snapshot -> structural extraction -> cleaning -> normalization/formatting -> variable-length structural chunks -> provenance/ownership/coverage/token validation. Preserve doctor profiles, FAQ pairs, heading context, table labels/footnotes, Arabic text, and source spans. A token ceiling is an overflow guard, not a chunk target.

Then implement robots-aware allowlisted public collection and audit manifests, recording failures/gaps. Review extracted/formatted/chunked content before paid embedding or index publication; these need verified provider counting/format/dimensions and explicit authorization. Follow [M3](docs/IMPLEMENTATION_PLAN.md#m3--public-website-ingestion), [INGESTION.md](docs/INGESTION.md), and [PROVIDERS.md](docs/PROVIDERS.md). Clinic chat stays unavailable until M5.

## Latest handoff

2026-10-14: Implemented M2's initial offline adapters and acceptance cases; 180 tests passed. Provider contracts document exact behavior and remaining live-use gates. M3 extraction/cleaning/structural chunking is the next milestone; a working RAG chatbot, live compatibility, source index, and Docker deployment remain later work.
