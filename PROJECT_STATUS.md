# Project status

Last updated: 2026-10-14 (Asia/Amman).

Current milestone: **M1 — FastAPI/configuration shell complete. M2 provider contracts are next.**

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
| M1 — FastAPI/configuration shell | Complete; 56 offline checks and local server smoke passed |
| M2 — provider contracts | Not started |
| M3 — public website ingestion | Not started |
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

No provider inference, embeddings, full crawl, index creation, live Qdrant request, Docker build, public deployment, Git initialization, or commit has run. The API shell works locally; there is no working RAG chatbot yet. Existing `.env` was not rewritten or printed.

## Known gaps and blockers

- No implementation blocker for M2's mocked provider-contract work.
- Friday/clinic opening hours are not verified by the limited website inspection. Never invent them; complete ingestion must establish what is actually published.
- Provider account access, structured-output behavior, actual vector dimensions, and provider conventions remain unverified.
- Hosting, widget integration, refresh cadence, and content-review ownership remain decisions for later milestones.

## Next concrete step

The next implementation task is **M2: implement async OpenRouter chat/embedding interfaces and adapters, validated structured-output parsing, embedding batch/index mapping, usage accounting, deadlines, and bounded retries with mocked protocol tests**. Preserve `openai/gpt-6-luna` and `qwen/qwen3-embedding-8b`; do not silently substitute models. Read the [M2 plan](docs/IMPLEMENTATION_PLAN.md), [pipeline](docs/PIPELINE.md), and [API contract](docs/API_CONTRACT.md).

The user can put the OpenRouter key in the ignored local `.env`. A key's presence does not authorize or start inference. M2's initial adapter work can remain offline; live compatibility checks require their own authorized, bounded screen.

## Latest handoff

2026-10-14: Completed M1 after the user requested the next step. API/configuration implementation, 56 offline checks, lint/format/lock verification, and a temporary localhost smoke check passed. Updated the roadmap and instructions. M2 is next; RAG answers and Docker deployment remain unimplemented.
