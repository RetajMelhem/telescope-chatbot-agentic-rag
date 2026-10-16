# Telescope clinic chatbot

An Arabic and English chatbot project for public information on [Telescope Medical Center's website](https://telescopecenter.com/). The target stack is FastAPI, LangGraph, GPT-6 Luna through OpenRouter, Qwen3 Embedding 8B, and a Qdrant knowledge index.

## Current status

M0 foundation, M1 API shell, M2 provider adapters, M3 source preparation/unpublished candidate storage, M4's initial retrieval comparison and an initial offline M5 LangGraph workflow are implemented. Dense remains the provisional retrieval baseline. The API shell can run locally; public chat still returns `503` pending serving integration and answer acceptance.

The saved public corpus contains 107 pages/955 chunks, with embeddings in an unpublished local Qdrant candidate. No active alias has been published; HNSW construction, model-driven planner/draft acceptance, serving retrieval, time operations, chatbot answers, full application Docker packaging and website integration remain unfinished. [PROJECT_STATUS.md](PROJECT_STATUS.md) records actual verification and remaining gates.

Provider adapters support strict structured chat responses, validated embedding batches, shared call/output/deadline bounds, safe errors and usage receipts. Normal Luna chat uses provider-reported usage without a local input counter or automatic retries. Explicit strict chat and embeddings retain verified counting; Qwen also requires its pinned verified format. Provider adapters are not connected to public chat. See [PROVIDERS.md](docs/PROVIDERS.md).

## Run the API shell locally

From the repository root, with the prepared `.venv`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn telescope_rag.api.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Open [local API documentation](http://127.0.0.1:8000/docs) after starting it. `/health/live` returns `200`. `/health/ready` returns `503` until model credentials and a compatible approved knowledge snapshot are available; the current default adapter always reports knowledge unavailable. A valid `POST /api/v1/chat` returns `503` with `chat_not_available`; invalid input returns `422`.

The app factory reads `.env` from the working directory. Its OpenRouter key takes priority over a process key, as requested by the user; other settings accept process-environment overrides. Explicit injected test settings still take priority, and environment injection works when no dotenv key exists. It never rewrites `.env` or performs network inference at import/startup. Invalid configuration fails with a sanitized startup message. Adapter cleanup has a five-second default deadline; failure logs contain only fixed event names. The OpenRouter URL must be the approved HTTPS `/api/v1` base endpoint.

For a fresh checkout with `uv` installed, use `uv sync --locked`. On this workspace, `uv` was bootstrapped locally without changing the global Python installation:

```powershell
& .\.tools\uv\bin\uv.exe sync --locked
& .\.tools\uv\bin\uv.exe run --locked ruff check .
& .\.tools\uv\bin\uv.exe run --locked ruff format --check .
& .\.tools\uv\bin\uv.exe run --locked pytest
```

Tests isolate settings, use synthetic credentials and in-process/fake services, and block external socket connections. Loopback and Unix sockets are permitted for event-loop internals, including Windows asyncio. There is no live Qdrant/provider test in this milestone.

## Product boundary

Answer questions that have supporting public website content: doctors, specialties, services, treatment techniques, clinic opening times, publicly posted doctor working hours, contact information, and other published clinic facts. Support English, Arabic, and everyday Jordanian Arabic.

If information is missing, ambiguous, contradictory, or too old for the question, say so or ask a short clarification. Cite website pages for factual answers. Do not invent Friday opening times or imply that published working hours establish appointment availability.

Patient files, private calendars, appointment availability, bookings, edits to records, and submissions to website forms are outside the product scope.

## Proposed request flow

```text
User question + bounded conversation context
  -> validate request and privacy boundary
  -> Luna plans one or more questions, or asks for clarification
  -> Qwen embeds the retrieval queries
  -> retrieve pre-indexed website evidence per question
  -> check evidence and calculate time comparisons when supported
  -> Luna answers using the original question and evidence
  -> validate citations and return a complete, partial, or unknown answer
```

Website collection and document embedding run as a separate ingestion job. They do not run during a chat request. See [PIPELINE.md](docs/PIPELINE.md) for the graph and termination rules.

An initial offline LangGraph workflow now exists in `src/telescope_rag/graph/`, with strict planning/draft schemas, per-part retrieval/complete-source reads, evidence assembly and citation validation. It uses injected mocked services in tests and returns review-only full-passage drafts. Real Luna planning/counting, source-grounded answer acceptance and serving retrieval integration remain unverified; the public chat endpoint still returns `503`. [PROJECT_STATUS.md](PROJECT_STATUS.md) records the current milestone and exact checks.

Ingestion now collects immutable public snapshots, cleans/formats content, and forms chunks by doctor/FAQ/section/list/table boundaries with source mappings. The draft CLI refuses to claim token validation or embedding readiness without verified counting/format profiles. Token counts are a safety ceiling rather than a fixed chunk target. Run commands and the review/candidate gates are documented in [INGESTION_RUNBOOK.md](docs/INGESTION_RUNBOOK.md).

A full-page LLM review compared all 127 collected public pages with the original preparation and a fresh crawl. It found omitted heading-only facts and incorrect source relationships, which led to the version 2 extractor/formatter. The latest draft is `data/processed/m3-page-audit-final`; the per-page findings and checks are in `data/manifests/m3-page-by-page-review.json`. Clinical source acceptance and verified token/embedding preparation remain pending.

The project now has a local Git repository on `main` with a baseline checkpoint and a separate chunking-policy revision. Local secrets, tool environments, and generated data are ignored. `.gitattributes` keeps source line endings consistent for Windows development and Linux deployment. Use `git status` and `git diff` to review work; repository setup does not publish the project externally.

## Project documents

| Document | Purpose |
| --- | --- |
| [PROJECT_SPECIFICATION.md](docs/PROJECT_SPECIFICATION.md) | Product requirements and acceptance criteria |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Folder ownership and service boundaries |
| [PIPELINE.md](docs/PIPELINE.md) | LangGraph nodes, state, budgets, and answer behavior |
| [PROVIDERS.md](docs/PROVIDERS.md) | Implemented OpenRouter interfaces, accounting, retries, and live-use gates |
| [INGESTION.md](docs/INGESTION.md) | Website crawling, chunking, provenance, and index updates |
| [INGESTION_RUNBOOK.md](docs/INGESTION_RUNBOOK.md) | Implemented collection/preparation commands and review gates |
| [API_CONTRACT.md](docs/API_CONTRACT.md) | Planned FastAPI request and response contracts |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Docker design, runtime configuration, and operations |
| [EVALUATION.md](docs/EVALUATION.md) | Meaningful correctness and boundary checks |
| [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Ordered delivery milestones |
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | Completed work, verification, blockers, and the next step |
| [DECISIONS.md](docs/DECISIONS.md) | Confirmed requirements, design defaults, and open decisions |
| [SOURCES.md](docs/SOURCES.md) | Sources inspected and limits of the research |
| [AGENTS.md](AGENTS.md) | Canonical Codex repository instructions |

## Configuration preparation

`.env.example` lists validated settings and design defaults. The local `.env` is for the user to fill in and has been preserved during implementation. Both Git and Docker exclusions protect local environment files. Do not paste the key into documentation or chat. The new body/readiness limits have defaults, so an existing `.env` need not be rewritten to use them.

The model identifiers are `openai/gpt-6-luna` and `qwen/qwen3-embedding-8b`. The pinned Qwen tokenizer/OpenRouter/DeepInfra profile passed the authorized screens and corpus/query runs with 4,096 dimensions and matching counts. Luna minimal JSON and actual planner-schema screens ran on 2026-10-16; the larger planner cases exposed coverage and meaning failures. The opt-in candidate produces complete JSON but is not adopted. Draft-schema compatibility and bilingual answer quality remain unverified. See [provider contracts](docs/PROVIDERS.md) and [current progress](PROJECT_STATUS.md). The existing local `.env` was preserved.

The next step is a current-code-bound screen of the prepared bilingual planner schemas, followed by dense retrieval/graph integration and source-grounded answer evaluation. Keep source uncertainty explicit and the candidate unpublished until acceptance; do not repeat embeddings implicitly. See the implementation plan and progress file for the remaining milestones.
