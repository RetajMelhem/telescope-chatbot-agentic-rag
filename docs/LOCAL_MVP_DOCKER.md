# Run the local Docker MVP

From PowerShell in `C:\CLINIC\clinic_agentic_rag`, with Docker Desktop running:

```powershell
.\run-mvp.ps1
```

Open [the chatbot](http://127.0.0.1:8000/), [API docs](http://127.0.0.1:8000/docs),
or [readiness](http://127.0.0.1:8000/health/ready). Each submitted question can spend
OpenRouter credit. Startup, health, static pages and preparation make no inference
calls. The API runs in the background after the launcher exits.

```powershell
.\run-mvp.ps1 -Action Status
.\run-mvp.ps1 -Action Stop
.\run-mvp.ps1 -Action Restart
```

Stop affects only the API, preserving Qdrant, its volume, data and keys. Restart
recreates the API from its existing image and current mounted resources/secrets.
Start builds current code and recreates the API. Use Start after code changes. Either Start or
Restart recreates secret mounts after key rotation. If port 8000 is busy, use
`-Port 8001` consistently and open `http://127.0.0.1:8001/`. This project manages
one API container. Stop it before running the earlier `run-local.ps1` host launcher
on the same port. The default/production factory remains unavailable; this image
explicitly selects `telescope_rag.api.container:create_container_app`.

## Required local resources

This is a runnable delivery for the existing reviewed installation. Cloning Git
alone does not supply excluded data, tokenizer, credentials or database. Another
machine must receive the reviewed resources separately:

- The project `.env` with its designated OpenRouter key; the launcher never changes it.
- `.tools/qdrant-m3/read.key`, the server-enforced read-only database key.
- The approved `data/processed/m3-execution-approved-v6-v2/` bundle and metadata.
- `source-admission-plan.json` and `primary-directory.json` under
  `data/processed/m3-llm-semantic-token-validated-v6/metadata/`.
- `artifacts/m5-public-hours-v1/reviewed-hours-plan.json`.
- `artifacts/public-website-links-v1/reviewed-links-plan.json`.
- The exact tokenizer under `.tools/qwen-tokenizer/1d8ad4ca9b3dd8059ad90a75d4983776a23d44af/`.
- The existing `data/processed/m4-query-cache-v1/` directory.
- Existing `telescope-m3-qdrant` and gateway containers, their private
  `telescope-m3-local` network and persistent database volume.

The host Python/locked uv environment validates resources before startup. The API
itself runs with locked dependencies inside the image. No crawl, corpus embedding,
index replacement, alias publication or automatic source refresh occurs. Missing
or incompatible resources fail closed.

## Container boundaries

The Dockerfile pins official Python 3.11.17/bookworm and uv 0.13.1 images by registry
digest. It packages only the application, HTML page and locked dependencies. Real
keys, dotenv, source bundles, tokenizer bytes, caches and audits stay outside the
image. Runtime resources are mounted read-only; the tokenizer is hash/library
checked and never downloaded at startup.

`scripts/prepare_local_mvp_runtime.py` stages the designated project key in ignored
`runtime-data/local-mvp/openrouter.key`, idempotently and without printing it. It
rejects inherited-key substitution when the project dotenv key is absent. Compose
uses nonsecret `deploy/local-mvp.env` for interpolation. Only OpenRouter and Qdrant
read keys are supplied as secret files; no admin key, Docker socket or host dotenv
is mounted. Local Compose secrets are file mounts, not an encrypted production
secret manager.

The API runs as UID/GID 10001 with read-only root, dropped capabilities,
`no-new-privileges`, bounded temporary storage and resource limits. Its host port
binds to `127.0.0.1`. It reaches the fixed DNS target
`http://telescope-m3-qdrant:6333/` over the existing private network and uses a
separate bridge for OpenRouter egress. The host reader keeps its loopback default;
no arbitrary database URL or write method is added.

## Verification and recovery

Real build, startup, inference and API recreation/readiness checks passed on Docker
Desktop/Linux amd64. Data, 955-point inventory, aliases and dotenv stayed unchanged.
A read-key PATCH to a confirmed absent collection was denied with HTTP 403 and
cannot create data. Starting the image without secrets exits before inference.
Image inspection confirms packaged HTML and absent runtime data/secrets.

Inspect operational logs with `docker logs telescope-local-mvp-api`. Default logs
exclude questions, histories, provider payloads and credentials. Check Docker
Desktop, the selected port and prerequisites if startup fails; do not recreate
Qdrant or change source digests to bypass failures. Stop the API, restore the
intended reviewed resources/image and start again. The host launcher is a fallback.

Database backup/restore, new-machine data transfer, HTTPS, public hosting, source
refresh and website integration remain separate. See [acceptance](LOCAL_MVP_ACCEPTANCE.md).

Implementation references: [FastAPI containers](https://fastapi.tiangolo.com/deployment/docker/),
[uv Docker](https://docs.astral.sh/uv/guides/integration/docker/) and
[Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).
