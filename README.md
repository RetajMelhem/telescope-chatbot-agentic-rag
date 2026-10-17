# Telescope clinic chatbot

A local public-information RAG chatbot for Telescope Medical Center, using Python,
FastAPI, LangGraph, GPT-6 Luna through OpenRouter, Qwen3 Embedding 8B and Qdrant.
It accepts English, Arabic and everyday Jordanian Arabic questions.

## Run the local MVP

From PowerShell in this repository:

```powershell
.\run-local.ps1
```

Open [local chat](http://127.0.0.1:8000/) or
[API documentation](http://127.0.0.1:8000/docs). Docker Desktop must be running;
the launcher starts the two existing Qdrant containers if stopped. The API runs
on this computer at `127.0.0.1:8000`. Ctrl+C stops it.

The existing reviewed 107-page / 955-chunk snapshot supplies evidence. Answers
contain source excerpts, URLs and retrieval timestamps. Public hours are supported;
private records, private calendars, availability and booking actions are excluded.
Missing facts and ambiguous source choices remain explicit. Each submitted question
uses the project OpenRouter key; opening the page and health checks make no
inference calls. The browser does not store history.

See [LOCAL_MVP.md](docs/LOCAL_MVP.md) for prerequisites, direct API queries, budgets,
response behavior and limits. Local source files, tokenizer and credentials are
excluded from Git; cloning the code alone does not reproduce this installation.

## Verified scope

The local MVP is usable for development. The full offline suite passes, and real
Luna/Qdrant/API development questions have been reviewed against saved official
webpages. The diagnostic failures, targeted fixes, counts, cost and remaining
limitations are recorded in [PROJECT_STATUS.md](PROJECT_STATUS.md) and
[LOCAL_MVP_ACCEPTANCE.md](docs/LOCAL_MVP_ACCEPTANCE.md).

Dense retrieval remains provisional. The system presents literal excerpts rather
than polished generated narrative. A source may use a different language from the
question. The saved snapshot is not a live website refresh. Broad independent
accuracy acceptance, portable API Docker packaging, public deployment and website
integration remain future work. The original default `api.main:create_app` still
returns unavailable; use the explicit local launcher above.

## Project documents

- [Project scope](docs/PROJECT_SPECIFICATION.md)
- [Architecture](docs/ARCHITECTURE.md) and [pipeline](docs/PIPELINE.md)
- [Provider contracts](docs/PROVIDERS.md)
- [Ingestion policy](docs/INGESTION.md) and [runbook](docs/INGESTION_RUNBOOK.md)
- [API contract](docs/API_CONTRACT.md)
- [Evaluation](docs/EVALUATION.md) and [deployment](docs/DEPLOYMENT.md)
- [Roadmap](docs/IMPLEMENTATION_PLAN.md) and [decisions](docs/DECISIONS.md)
- [Current progress](PROJECT_STATUS.md) and [repository instructions](AGENTS.md)
