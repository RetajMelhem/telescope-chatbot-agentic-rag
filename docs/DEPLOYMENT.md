# Local Docker deployment and production design

The [portable release](PORTABLE_MVP.md) adds an isolated API/Qdrant installation
with saved corpus vectors and no Nginx gateway. The existing development runtime
below remains unchanged. Check current restore verification in `PROJECT_STATUS.md`.

The local API image/Compose/launcher are now implemented and verified; use
[LOCAL_MVP_DOCKER.md](LOCAL_MVP_DOCKER.md). They reuse the existing reviewed database
and mount required data/tokenizer/secrets read-only. The broader production design
below is not a record of production deployment or acceptance.

Current local MVP: [runbook](LOCAL_MVP.md) and [acceptance evidence](LOCAL_MVP_ACCEPTANCE.md).
The explicit loopback entry point now serves live development queries. The default
application and production acceptance remain separate; earlier checkpoints below
describe their original scope.

Status: bounded local API packaging is delivered. Full M6 production deployment,
ingestion-service packaging and public hosting remain separate.
The local M3 Qdrant gateway remains unchanged; no index is published by this delivery.

## Current runtime

| Container | Content/storage | Access |
| --- | --- | --- |
| `telescope-local-mvp-api` | Application, browser UI, LangGraph, provider/retrieval adapters and locked dependencies; reviewed files and two secret files mounted read-only | Loopback `8000`; direct private-network Qdrant reads and OpenRouter egress |
| `telescope-m3-qdrant` | Existing vector collection and payloads in `telescope-m3-qdrant-storage` | Private `telescope-m3-local` network |
| `telescope-m3-qdrant-gateway` | Nginx forwarding with a read-only config mount | Loopback `6333` for host tools/dashboard |

`telescope-m3-local` also appears as a Compose project/group in Docker Desktop;
the group is not an extra running container. Luna/Qwen weights are not present:
both inference services are accessed through OpenRouter. Start builds/recreates
the API and starts already-existing database/gateway containers as needed. Stop
stops only the API.
See [GitHub and handoff](GITHUB_AND_HANDOFF.md) for the code/data boundary.

## Current local M3 Qdrant access

The existing `telescope-m3-qdrant` container (Qdrant 1.19.2) retains its original storage volume, key/config files and sole internal network `telescope-m3-local`. Its attempted host publication was ineffective on that network. [compose.qdrant-local.yaml](../deploy/compose.qdrant-local.yaml) adds a separate gateway on the private network and `telescope-m3-loopback`; only the gateway publishes `127.0.0.1:6333`. [qdrant-gateway.conf](../deploy/qdrant-gateway.conf) forwards client authentication to the fixed Qdrant upstream without embedding a key, access logging, caching or upstream retries.

The gateway uses a digest-pinned official Nginx image (observed 1.30.6), non-root identity, read-only root, dropped capabilities, `no-new-privileges`, bounded resources and temporary storage. Its only bind mount is the read-only gateway configuration; it receives no data volume, key or Docker socket. These gateway properties do not describe the unchanged Qdrant container's own privilege configuration. Host-local processes and containers on the gateway network can reach it but still need Qdrant credentials; this is PC-only access, not public deployment.

The following was executed against the existing dedicated environment, followed by configuration, authentication, restart and empty-inventory checks:

```powershell
docker start telescope-m3-qdrant
docker compose -f deploy/compose.qdrant-local.yaml --project-name telescope-m3-local config --quiet
docker compose -f deploy/compose.qdrant-local.yaml --project-name telescope-m3-local up -d
```

Both containers now use `unless-stopped`. The authenticated checker and its explicit non-creating permission-probe flag are documented in [INGESTION_RUNBOOK.md](INGESTION_RUNBOOK.md). Evidence: `artifacts/m3-local-preflight-repair-v1/REPORT.md`. To withdraw host access, stop `telescope-m3-qdrant-gateway`; this leaves the private database, volume and keys intact. Do not delete/reinitialize the existing database or volume as a connectivity repair.

## Future production services

The following is a broader design, not an alternative command to run the local
MVP. Ingestion/TLS profiles are not delivered; the portable installer provisions
the fixed local snapshot only.

| Service | Responsibility and exposure |
| --- | --- |
| `api` | FastAPI + LangGraph, one Uvicorn process per container; reads approved knowledge and calls OpenRouter. |
| `qdrant` | Persistent public knowledge index; private container-network access only. |
| `ingest` | Same application image, separate command and opt-in Compose profile; collects pages and publishes candidate snapshots. |
| TLS proxy | Production HTTPS, body/rate limits, and routing; use the host's proxy or add a managed proxy service. |

Hosted embeddings avoid packaging the 8B model or GPU runtime in the API image. The ingestion job is not started automatically with the API and does not run per chat.

The implemented local files are `deploy/Dockerfile` and
`deploy/compose.local-mvp.yaml`, with repository-root build context. A standalone
production `deploy/compose.yaml` and ingestion profile remain planned.

## Image requirements

- Use an official supported Python slim base, pinned to an evaluated version/digest at release time.
- Install locked runtime dependencies before copying source, for a reusable build cache.
- Package only the application and versioned prompts. Exclude `.env`, keys, collected website data, local results, and development caches.
- Run as a non-root user with an exec-form command. The implemented local image selects `telescope_rag.api.container:create_container_app`. The fail-closed `api.main:create_app` is not a working chatbot entry point.
- Use container limits and graceful shutdown. Production images do not use `--reload`.
- Run the ingestion CLI through a separate command once implemented; never perform a crawl or paid warmup during image build or API startup.

The local API factory and image exist; standalone production and ingestion
packaging remain future work. [FastAPI's Docker documentation](https://fastapi.tiangolo.com/deployment/docker/)
describes the underlying container pattern.

## Networks, secrets, and storage

The current local factory pins `http://telescope-m3-qdrant:6333` in the container
and `http://127.0.0.1:6333` for host Python. A future standalone production Compose
may use a different fixed service name after implementation/verification; do not
substitute the generic `http://qdrant:6333` design URL into this local reader.

Keep Qdrant off public host ports. For development, bind the API to `127.0.0.1:8000:8000`. For production, expose HTTPS through the proxy and keep the application/database ports private. Optional local Qdrant inspection must bind only to loopback.

Use separate Qdrant read and ingestion write credentials with server-enforced permissions, verified for the pinned release. The API's read-only methods alone are insufficient if its credential permits writes. Configure the supported read-only key or equivalent enforced policy; the ingestion process receives the write credential separately. Never give the public API the ingestion secret.

Mount Qdrant storage on a named persistent volume. Give ingestion persistent snapshot/manifest storage; the API receives only required approved manifest data read-only. Store backups outside the application image and test restoration.

Host development loads the project `.env`. The local Docker launcher validates it
and stages its provider key into an ignored file; the container reads that file
and the existing database read key through `/run/secrets`. This is implemented,
not an encrypted production secret store. Future production should inject secrets
through the deployment platform. `.env.example` is only a template. Do not bake
keys into build arguments or image layers.

Compose's `.env` interpolation does not automatically put values inside containers: map settings explicitly with `environment` or `env_file`. Select only the secrets each service needs. See [Docker's environment configuration guidance](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/).

## Startup and health

On this prepared installation run `.\run-mvp.ps1`; it validates required local
resources, starts the existing authenticated database/gateway if stopped, and
builds/recreates the API. It requires those database/gateway containers and the
reviewed corpus to exist already. It does not run ingestion, create an index or
publish an alias. A future production installation needs its own approved-index
publication and restore procedure.

Use `/health/live` for process liveness and `/health/ready` for approved knowledge readiness. Health probes must not consume paid inference. Record provider failures through actual request telemetry; a green health endpoint is not a provider compatibility test.

Set timeouts and rate limits at both API and proxy layers. Trust forwarded headers only from the known proxy. Keep external tracing disabled by default and exclude raw visitor text from logs.

## Planned developer commands

After the referenced files and entry points exist:

```powershell
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml up -d qdrant
docker compose -f deploy/compose.yaml --profile ingestion run --rm ingest
docker compose -f deploy/compose.yaml up -d api
```

These commands are a future runbook and were not executed. The exact ingestion command/profile must be verified with the implemented Compose file.

## Refresh, rollback, and release gates

Choose a refresh cadence before release. Refresh into a candidate collection, validate it, and switch the active alias atomically. Keep the previous approved index and manifests for rollback. Deploy application images by immutable tag/digest and preserve a known compatible previous image.

Release requires a passing container build, health behavior with missing and valid indexes, restart persistence, enforced read/write separation, secret exclusion, bilingual source-based evaluation, an authorized provider compatibility check, and a documented rollback/restore exercise. Choose the hosting destination and website widget integration before public launch.
