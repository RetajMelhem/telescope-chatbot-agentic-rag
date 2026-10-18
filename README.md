# Telescope clinic chatbot

A local public-information RAG chatbot for Telescope Medical Center, using Python,
FastAPI, LangGraph, GPT-6 Luna through OpenRouter, Qwen3 Embedding 8B and Qdrant.
It accepts English, Arabic and everyday Jordanian Arabic questions.

## Run the local MVP

On the existing prepared computer, open Docker Desktop, then run in PowerShell:

```powershell
cd C:\CLINIC\clinic_agentic_rag
.\run-mvp.ps1
```

Open [local chat](http://127.0.0.1:8000/) or
[API documentation](http://127.0.0.1:8000/docs). Docker Desktop must be running;
the launcher starts the existing Qdrant containers if stopped, builds the API
image and starts it at `127.0.0.1:8000` in the background. Stop the API with
`.\run-mvp.ps1 -Action Stop`. See [the Docker runbook](docs/LOCAL_MVP_DOCKER.md).
The previous host-Python launcher `.\run-local.ps1` remains available.

Useful controls:

```powershell
.\run-mvp.ps1 -Action Status
.\run-mvp.ps1 -Action Stop
.\run-mvp.ps1 -Action Restart
```

Start builds current code; Restart uses the existing image. Both recreate the API
with current mounted resources/secrets. Stop leaves the database intact.

## What Docker runs

| Container | Current responsibility | Host access |
| --- | --- | --- |
| `telescope-local-mvp-api` | Python/FastAPI, browser UI, LangGraph, prompts, retrieval and OpenRouter adapters | `127.0.0.1:8000` |
| `telescope-m3-qdrant` | Existing vectors and payloads in the persistent `telescope-m3-qdrant-storage` volume | Private Docker network |
| `telescope-m3-qdrant-gateway` | Nginx forwarding for authenticated local Qdrant/dashboard access | `127.0.0.1:6333` |

Luna and Qwen run through OpenRouter, not as local model containers. The API image
contains application code and locked runtime dependencies. Reviewed source data,
metadata, tokenizer, query cache and secret files are mounted read-only at runtime.
The API talks directly to Qdrant on the private network; the gateway is the host's
local access path. See [container details](docs/LOCAL_MVP_DOCKER.md).

## What belongs on GitHub

Commit source code, prompts, tests/fixtures, scripts, Docker/Compose definitions,
the lockfile, documentation and the secret-free `.env.example`. Real `.env`/keys,
collected pages/chunks, embeddings, database storage, tokenizer, local environments
and generated audit results remain excluded. Docker images/volumes are separate
from the Git repository. See [GitHub and handoff](docs/GITHUB_AND_HANDOFF.md).

**A fresh clone cannot run the chatbot by itself.** The current launcher requires
the existing reviewed resources, keys, Qdrant container/volume and networks. It
does not provision a new database or recreate the reviewed corpus. New-machine
transfer and database restoration remain unverified.

## Answer behavior

The existing reviewed 107-page / 955-chunk snapshot supplies evidence. Answers
are written naturally from the retrieved evidence, with citations and retrieval timestamps.
Original source excerpts are available under expandable source details. Public hours are supported;
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

Dense retrieval remains provisional. The local flow now writes conversational answers in the requested language. Source
quotations remain unchanged, including when an English source supports an Arabic reply.
Broader answer quality and semantic robustness remain unproven. The saved snapshot is not a live website refresh. Broad independent
accuracy acceptance, public deployment and website
integration remain future work. The original default `api.main:create_app` still
returns unavailable; use the explicit local launcher above.

## Project documents

- [Documentation map: current guides and historical experiments](docs/README.md)
- [Docker startup](docs/LOCAL_MVP_DOCKER.md) and [GitHub/handoff](docs/GITHUB_AND_HANDOFF.md)
- [Project scope](docs/PROJECT_SPECIFICATION.md)
- [Architecture](docs/ARCHITECTURE.md) and [pipeline](docs/PIPELINE.md)
- [Provider contracts](docs/PROVIDERS.md)
- [Ingestion policy](docs/INGESTION.md) and [runbook](docs/INGESTION_RUNBOOK.md)
- [API contract](docs/API_CONTRACT.md)
- [Evaluation](docs/EVALUATION.md) and [deployment](docs/DEPLOYMENT.md)
- [Roadmap](docs/IMPLEMENTATION_PLAN.md) and [decisions](docs/DECISIONS.md)
- [Current progress](PROJECT_STATUS.md) and [repository instructions](AGENTS.md)
