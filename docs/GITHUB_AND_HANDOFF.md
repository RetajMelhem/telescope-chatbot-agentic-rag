# GitHub contents and local MVP handoff

Reviewed against the current checkout and Docker installation on 2026-10-18.
The local MVP is usable on this prepared computer. Git holds the software; the
running installation also depends on excluded resources and credentials.

## What goes in the repository

| Tracked item | Purpose |
| --- | --- |
| `src/telescope_rag/` | API, local browser UI, graph, providers, retrieval, knowledge logic, ingestion tools and versioned prompts |
| `tests/` | Unit/integration/evaluation tests and small checked-in fixtures; no real keys |
| `scripts/` | Explicit preparation, diagnostic and evaluation tools; their presence does not authorize live runs |
| `deploy/` | API Dockerfile, local API/gateway Compose definitions, Nginx configuration and a nonsecret Compose interpolation file |
| `run-mvp.ps1`, `run-local.ps1` | Docker launcher and alternative host-Python launcher |
| `pyproject.toml`, `uv.lock`, `.python-version` | Package, locked dependencies and host Python selection |
| `README.md`, `docs/`, `PROJECT_STATUS.md`, `AGENTS.md` | Run instructions, contracts, evidence summaries, progress and repository rules |
| `.env.example`, `.gitignore`, `.dockerignore`, `.gitattributes` | Secret-free template and repository/build conventions |
| `data/*/.gitkeep` | Empty directory placeholders, not the corpus |

`deploy/local-mvp.env` is a tracked, nonsecret interpolation file. It is distinct
from the ignored project `.env`, which contains the real provider credential.

## What stays outside GitHub and the API image

| Local resource | Current location / handling |
| --- | --- |
| Real provider configuration | Ignored project `.env`; never commit it |
| Database keys/configuration | Ignored `.tools/qdrant-m3/`; the API receives only the read key |
| Runtime provider secret | Ignored `runtime-data/local-mvp/openrouter.key`, staged by the launcher |
| Reviewed documents/chunks and metadata | Ignored `data/processed/` |
| Original webpages/manifests | Ignored `data/raw/` and `data/manifests/`, retained for provenance/review |
| Reviewed hours and website-link plans | Exact files under ignored `artifacts/`, mounted read-only |
| Verified tokenizer | Exact `tokenizer.json` under ignored `.tools/qwen-tokenizer/` |
| Query embedding cache | Ignored `data/processed/m4-query-cache-v1/`, mounted read-only |
| Qdrant vectors and payloads | Docker volume `telescope-m3-qdrant-storage`, separate from Git and the API image |
| Audit outputs/logs and local tooling | Ignored `artifacts/`, logs, `.tools/` and `.venv/` |

The complete required runtime paths are listed in
[the Docker runbook](LOCAL_MVP_DOCKER.md#required-local-resources).
Do not force-add ignored resources to make a clone appear runnable. Public origin
does not change this repository's rule excluding collected content from Git.

## What publishing the code means

The supplied GitHub destination is
[RetajMelhem/telescope-chatbot-agentic-rag](https://github.com/RetajMelhem/telescope-chatbot-agentic-rag).
The local `origin` remote is configured to its HTTPS Git URL. Local commits exist;
this documentation task does not push them. Inspect tracked files,
staged changes and history for secrets before the first push; an ignore rule does
not remove material already committed in history.

Useful local inspection commands:

```powershell
git status --short
git ls-files
git diff --cached --stat
git diff --cached
git remote
```

Keep code publication separate from Docker image publication and knowledge-data
transfer. Neither a Git push nor an API image contains the Qdrant volume. Publishing
this code does not deploy the chatbot or supply inference credit.

## Run on the existing prepared computer

1. Start Docker Desktop in Linux-container mode.
2. Open PowerShell in `C:\CLINIC\clinic_agentic_rag`.
3. Run `.\run-mvp.ps1` and wait for the API to become healthy.
4. Open [the chatbot](http://127.0.0.1:8000/) or
   [API documentation](http://127.0.0.1:8000/docs).

The launcher uses the workspace uv executable or `uv` on PATH to validate the
reviewed local resources, stages the project provider key, starts the existing
database/gateway if needed, then builds/recreates only the API service. It does
not collect pages, embed the corpus, publish an alias or initialize a new database.
Submitting a question can spend provider credit; opening the UI and health
checks make no inference calls.

Stop with `.\run-mvp.ps1 -Action Stop`. Qdrant, its data and the gateway remain.
See [the runbook](LOCAL_MVP_DOCKER.md) for Status, Restart and alternative ports.

## Another computer

A clone alone is incomplete. It needs compatible Docker/host tooling, the exact
reviewed files/tokenizer/plans, separately supplied credentials, and a restored
compatible Qdrant database plus the required fixed container/network names.
The checked-in gateway Compose file creates the gateway, not the database.
The API launcher requires the database/gateway containers to exist already.

There is no verified clean-machine provisioning or database backup/restore
procedure in this MVP. Preserve the current volume and source provenance. A
separate tested data-transfer/restore package is needed before claiming portable
installation. Do not rerun paid corpus embedding to compensate for missing files.
