# Documentation map

Current local MVP review: 2026-10-18. Start with the guides below. Earlier
experiments remain documented for traceability; their dated counts, balances and
"next" instructions are historical, not the current project status.

## Current user and operator guides

| Document | What it describes |
| --- | --- |
| [Project README](../README.md) | What is delivered and how to start |
| [Current status](../PROJECT_STATUS.md) | Current result, limits and next action; older entries follow |
| [Docker runbook](LOCAL_MVP_DOCKER.md) | Existing-installation Start/Stop/Status/Restart and exact prerequisites |
| [GitHub and handoff](GITHUB_AND_HANDOFF.md) | Code versus excluded data/secrets, containers and new-machine limitations |
| [Portable MVP](PORTABLE_MVP.md) | Minimal two-container release, saved vectors, installer, updates and rollback |
| [v0.2.0 release](RELEASE_V0_2_0.md) | Tested answer fixes, localhost Qdrant dashboard, and release limits |
| [Local API/host alternative](LOCAL_MVP.md) | API examples, response behavior and alternative host launcher |
| [Acceptance evidence](LOCAL_MVP_ACCEPTANCE.md) | Checks actually run, failures/fixes, spend observations and unverified areas |

## Current contracts and implementation

- [Scope](PROJECT_SPECIFICATION.md), [architecture](ARCHITECTURE.md),
  [pipeline](PIPELINE.md) and [API contract](API_CONTRACT.md).
- [Provider contracts](PROVIDERS.md), [conversational answers](CONVERSATIONAL_ANSWERS.md),
  [hours data/math](PUBLIC_HOURS.md), [hours graph](HOURS_GRAPH.md) and
  [website-link provenance](PUBLIC_WEBSITE_LINKS.md).
- [Source preparation](INGESTION.md), [ingestion runbook](INGESTION_RUNBOOK.md),
  [retrieval bridge](REQUEST_RETRIEVAL_BRIDGE.md) and
  [local service/context repair](SERVICE_RETRIEVAL_REPAIR.md).
- [Deployment](DEPLOYMENT.md), [roadmap](IMPLEMENTATION_PLAN.md),
  [evaluation plan](EVALUATION.md) and [completion/budget policy](COMPLETION_BUDGET.md).
- [50 approved everyday user questions](NATURAL_QUESTIONS_50_DRAFT.md) and
  [source-backed evaluation runbook](NATURAL_EVALUATION_50.md): 25 Jordanian Arabic /
  English pairs; installed v0.1.0 HTTP execution, source review and metric limits.
- [Targeted diagnosis and fixes](NATURAL_EVALUATION_FIXES.md): seven problem cases,
  preserved baseline, local candidate verification and unconfirmed historical 502 causes.
- [Offline saved-answer remeasurement](NATURAL_EVALUATION_50.md#offline-remeasurement-of-saved-responses):
  original 50-case scores versus 43 carried baseline replies plus seven saved R1
  replies; zero new requests, with mixed-version and review limits explicit.

These documents may retain dated development sections. Current local serving is
the explicit Docker/host factory; the default `api.main:create_app` still fails
closed. A successful local response is not production acceptance. The current
wire is `local-mvp-response-v1`, not the planned `answered` response envelope.

## Historical experiments and component profiles

The following are evidence or opt-in component descriptions, not alternative
current run instructions. Their prepared/live distinction and failures remain
important; no result implies a global retrieval or semantic guarantee.

- [Initial source inspection](SOURCES.md) and [decision record](DECISIONS.md).
- [Retrieval diagnosis](RETRIEVAL_DIAGNOSIS.md),
  [assembly comparison](EVIDENCE_ASSEMBLY_RESULTS.md) and
  [planner generalization](PLANNER_GENERALIZATION.md).
- [Purpose comparison](PURPOSE_COMPARISON.md),
  [referent comparison](REFERENT_COMPARISON.md),
  [referent diagnosis](REFERENT_DIAGNOSIS.md),
  [dependency preparation](DEPENDENCY_CONTEXT.md),
  [dependency comparison](DEPENDENCY_COMPARISON.md) and
  [local-constraint preparation](LOCAL_CONSTRAINTS.md).
- [Injected offline service](OFFLINE_SERVICE.md) and
  [extractive offline response](OFFLINE_RESPONSE.md). Their response flags and
  provider-injection requirements describe those profiles, not the local
  conversational factory.

Public hosting, a website widget, scheduled refresh and
broad independent quality acceptance remain separate work. The local MVP does
not need another prerequisite architecture milestone before ordinary use.
