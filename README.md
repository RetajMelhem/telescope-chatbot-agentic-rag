# Telescope clinic chatbot

A local public-information RAG chatbot for Telescope Medical Center, using Python,
FastAPI, LangGraph, GPT-6 Luna through OpenRouter, Qwen3 Embedding 8B and Qdrant.
It accepts English, Arabic and everyday Jordanian Arabic questions.

## License and permitted use

Copyright (c) 2026 Retaj Milhem. This project is available under the custom
[Telescope Evaluation-Only License](LICENSE). It is source-available for local,
noncommercial learning, experimentation and evaluation, including private
modifications for those purposes. It is not an open-source license.

**Selling, monetizing, publicly hosting or using the project in production or
routine organizational operations requires prior written permission.** This
includes use by Telescope Medical Center or any other clinic or company, even
when no fee is charged. An organization may evaluate it locally, but may not
use that evaluation to serve actual patients, customers or daily staff work.

Retain the license and attribution in permitted copies and forks. Third-party
libraries, models and website content retain their respective owners' rights
and terms; [GitHub's public-repository viewing/forking rights](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#5-license-grant-to-other-users)
remain unchanged.
For other permissions, contact **retajmelhem92004@gmail.com**. The full
[LICENSE](LICENSE) controls; these permissions apply only to rights the author
owns or is authorized to license and do not override existing agreements.

## Run the local MVP

For another Windows computer, use the versioned [portable installation](docs/PORTABLE_MVP.md):

```powershell
.\install-mvp.cmd -Version v0.3.0
```

Start Docker Desktop and extract the complete project ZIP first. You can also
double-click [install-mvp.cmd](install-mvp.cmd) to install v0.3.0. The launcher
uses a temporary PowerShell execution-policy bypass for its installer process;
it does not change the saved Windows policy or remove downloaded-file markers.

It downloads the reviewed data, existing Qdrant vectors and two ready-built images
from the matching GitHub Release. No corpus parsing/chunking/embedding is required.
Supply your own OpenRouter key for new questions. Release/restore verification is
recorded in [project status](PROJECT_STATUS.md).

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

The portable distribution runs only **API + Qdrant**. Nginx is excluded because
the API reads Qdrant directly. The table below describes the older development
installation, which is preserved:

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

**A fresh clone alone does not contain the knowledge/database.** The portable
installer supplies those through versioned Release assets, while keys remain
private. Historical raw crawls/audits and cached test queries are excluded.

## Answer behavior

The existing reviewed 107-page / 955-chunk snapshot supplies evidence. Answers
are written naturally from the retrieved evidence, with citations and retrieval timestamps.
Original source excerpts are available under expandable source details. Public hours are supported;
private records, private calendars, availability and booking actions are excluded.
Missing facts and ambiguous source choices remain explicit. Each submitted question
uses the project OpenRouter key; opening the page and health checks make no
inference calls. The browser does not store history.

With the v0.3.0 installer, inspect collections through the
[local Qdrant dashboard](http://127.0.0.1:6333/dashboard/). Use the installation's
read-only key; [dashboard login and custom ports](docs/PORTABLE_MVP.md#install-and-run)
are documented in the portable guide. Both services bind to localhost.

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
- [Portable installation, data assets and updates](docs/PORTABLE_MVP.md)
- [Project scope](docs/PROJECT_SPECIFICATION.md)
- [Architecture](docs/ARCHITECTURE.md) and [pipeline](docs/PIPELINE.md)
- [Provider contracts](docs/PROVIDERS.md)
- [Ingestion policy](docs/INGESTION.md) and [runbook](docs/INGESTION_RUNBOOK.md)
- [API contract](docs/API_CONTRACT.md)
- [Evaluation](docs/EVALUATION.md) and [deployment](docs/DEPLOYMENT.md)
- [Roadmap](docs/IMPLEMENTATION_PLAN.md) and [decisions](docs/DECISIONS.md)
- [Current progress](PROJECT_STATUS.md) and [repository instructions](AGENTS.md)
