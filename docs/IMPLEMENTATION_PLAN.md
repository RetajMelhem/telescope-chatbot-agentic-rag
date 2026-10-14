# Implementation plan

Status: roadmap. M0 foundation and M1 API/configuration shell are complete. Track actual verification and next actions in [PROJECT_STATUS.md](../PROJECT_STATUS.md).

## M0 — Specification and scaffold

Deliver the folder structure, product specification, architecture, pipeline, ingestion policy, API contract, Docker design, evaluation plan, Codex instructions, living progress file, configuration templates, and secret exclusions.

Verify document links, folder inventory, configuration consistency, and absence of a redundant `agent.md`. Do not call provider APIs or claim a deployable application. Foundation completion does not imply any later milestone is authorized or achieved.

## M1 — FastAPI shell and validated configuration

Create `pyproject.toml`, a verified dependency lockfile, package entry points, Pydantic settings, safe errors/logging, the API application factory/lifespan, and health routes. Use injected provider and retrieval interfaces; provider-backed chat remains unavailable until later milestones.

Validate settings and missing-secret handling with offline checks. `/health/live` can succeed; `/health/ready` must fail when no approved index exists. Verify no key is logged, no network inference occurs at startup, and configuration cannot be overridden by chat input.

Implemented with injected fake knowledge probes and a default unavailable adapter. Provider interfaces/adapters are the next M2 task. Chat currently validates input and returns a safe unavailable result.

## M2 — Provider contracts

Implement asynchronous Luna chat and Qwen embedding adapters against OpenRouter, validated structured outputs, batch/index mapping, usage accounting, deadlines, and bounded retry handling. Preserve the chosen models; do not silently switch models when a parameter fails.

Offline fixtures cover successful responses, malformed output, unsupported schema behavior, reordered embedding items, mismatched dimensions, and transient failures. A later explicitly authorized compatibility screen validates account/model/endpoint behavior with minimal paid requests; adding a key does not start that screen.

## M3 — Public website ingestion

Implement allowlisted discovery, robots-aware collection, redirect/address checks, immutable snapshots, structural extraction, deterministic cleaning and formatting, variable-length chunks by source format/ownership, pre-embedding validation, directory coverage, hours records, candidate indexing, and audit manifests. Follow [INGESTION.md](INGESTION.md); token limits are overflow guards, not fixed-size targets or default overlap windows.

Validate local HTML/block fixtures first, including adjacent doctors, FAQ pairings, tables/footnotes, Arabic normalization, oversized units, and preserved source mappings. Then run the authorized public-site collection. Review extraction, cleaning, formatting, chunk coverage, and rejected-input manifests before paid embedding. Publish the first approved index only after dimensions, provenance, exclusions, and coverage checks pass. Compare structural chunking with a bounded fixed-window evaluation baseline on the same inputs during M3/M4; a baseline is an experiment, not the default serving policy.

## M4 — Retrieval and deterministic knowledge operations

Implement Qdrant reads, snapshot pinning, per-question evidence association, a bounded full-directory path, admitted hours records, and pure time comparison logic. Enforce read-only serving permissions separately from the ingestion writer.

Verify missing evidence, similar doctor names, unrelated service attribution, partial coverage, stale/conflicting hours, AM/PM ambiguity, overnight intervals, exact closing time, and a concurrent snapshot switch.

## M5 — LangGraph chat flow

Implement the graph in [PIPELINE.md](PIPELINE.md), versioned prompts, per-part scope/outcome handling, final structured responses, citation validation, and the chat route. Keep current questions and unresolved meaning intact across budgets.

Run offline end-to-end cases in English, Arabic, and Jordanian Arabic. Validate mixed public/private questions, missing doctor hours, fabricated history, injection, provider failure, and deadline termination. Live source-based evaluation remains a separate step.

## M6 — Docker and deployment verification

Implement the Dockerfile, Compose services, secret injection, persistent Qdrant volume, independent ingestion profile, read/write separation, health probes, and a concrete runbook. Validate image exclusions and restart/rollback behavior.

Build and test locally before deployment. Select the hosting environment and HTTPS/proxy arrangement. Public deployment is a distinct action; preparation alone does not authorize it.

## M7 — Source-based acceptance and website integration

Run the approved bounded live compatibility screen and bilingual evaluation against the published snapshot. Have clinic reviewers confirm factual support, hours, and content gaps. Record failures and resolve them without benchmark-specific routing.

Implement the website widget/integration once the backend contract is stable. Verify no secret reaches the browser, citations work, RTL text displays properly, rate limits work, and record/booking boundaries are clear. Launch only after the release criteria in [EVALUATION.md](EVALUATION.md) and [DEPLOYMENT.md](DEPLOYMENT.md) pass.

## Deferred capabilities

Server-side conversation storage, streaming, scheduled refresh jobs, JavaScript/PDF/OCR ingestion, hybrid search, reranking, and additional model stages need demonstrated requirements. Patient files, private schedules, and booking actions remain outside scope even after launch.
