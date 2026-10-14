# Telescope clinic chatbot

An Arabic and English chatbot project for public information on [Telescope Medical Center's website](https://telescopecenter.com/). The target stack is FastAPI, LangGraph, GPT-6 Luna through OpenRouter, Qwen3 Embedding 8B, and a Qdrant knowledge index.

## Current status

M0 foundation and M1 API shell are implemented. The repository includes specifications, Codex instructions, a progress file, a locked Python environment, validated settings, health endpoints, safe request/error handling, and a validated chat placeholder.

Provider calls, ingestion, Qdrant access, LangGraph orchestration, chatbot answers, Docker packaging, and website integration are not implemented yet. The API shell can run locally; it is not a functioning clinic chatbot. No paid model or embedding requests have been made. [PROJECT_STATUS.md](PROJECT_STATUS.md) records actual verification and the next milestone.

## Run the API shell locally

From the repository root, with the prepared `.venv`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn telescope_rag.api.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Open [local API documentation](http://127.0.0.1:8000/docs) after starting it. `/health/live` returns `200`. `/health/ready` returns `503` until model credentials and a compatible approved knowledge snapshot are available; the current default adapter always reports knowledge unavailable. A valid `POST /api/v1/chat` returns `503` with `chat_not_available`; invalid input returns `422`.

The app factory reads `.env` from the working directory and accepts process-environment overrides. It never rewrites `.env` or performs network inference at import/startup. Invalid configuration fails with a sanitized startup message. Adapter cleanup has a five-second default deadline; failure logs contain only fixed event names. The OpenRouter URL must be the approved HTTPS `/api/v1` base endpoint.

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

The ingestion design cleans and formats source content before embedding and chunks by its structure: doctor profiles, FAQ pairs, service sections, lists, and tables. Token counts are a safety ceiling rather than a fixed chunk-size target. This M3 design is specified in [INGESTION.md](docs/INGESTION.md); the cleaner/chunker is not implemented yet.

The project now has a local Git repository on `main` with a baseline checkpoint and a separate chunking-policy revision. Local secrets, tool environments, and generated data are ignored. `.gitattributes` keeps source line endings consistent for Windows development and Linux deployment. Use `git status` and `git diff` to review work; repository setup does not publish the project externally.

## Project documents

| Document | Purpose |
| --- | --- |
| [PROJECT_SPECIFICATION.md](docs/PROJECT_SPECIFICATION.md) | Product requirements and acceptance criteria |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Folder ownership and service boundaries |
| [PIPELINE.md](docs/PIPELINE.md) | LangGraph nodes, state, budgets, and answer behavior |
| [INGESTION.md](docs/INGESTION.md) | Website crawling, chunking, provenance, and index updates |
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

The model identifiers are `openai/gpt-6-luna` and `qwen/qwen3-embedding-8b`. Actual account access, endpoint behavior, structured-output support, and returned vector dimensions must be verified when the provider integration is implemented.

The next milestone is M2: implement OpenRouter provider adapters with mocked protocol tests. Live compatibility checks and ingestion come later; see the implementation plan.
