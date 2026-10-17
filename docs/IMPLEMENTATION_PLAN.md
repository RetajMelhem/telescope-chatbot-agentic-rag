# Implementation plan

Current local MVP: [runbook](LOCAL_MVP.md) and [acceptance evidence](LOCAL_MVP_ACCEPTANCE.md).
The explicit loopback entry point now serves live development queries. The default
application and production acceptance remain separate; earlier checkpoints below
describe their original scope.

Status: roadmap. M0 foundation, M1 API/configuration shell, and the initial offline M2 implementation are complete. M3 collection, source admission, Qwen/token preparation and authorized corpus embeddings/unpublished candidate verification are complete for their scoped gates; Qdrant publication and retrieval comparison remain pending. Luna compatibility remains unverified. Track actual verification and next actions in [PROJECT_STATUS.md](../PROJECT_STATUS.md).

## M0 — Specification and scaffold

Deliver the folder structure, product specification, architecture, pipeline, ingestion policy, API contract, Docker design, evaluation plan, Codex instructions, living progress file, configuration templates, and secret exclusions.

Verify document links, folder inventory, configuration consistency, and absence of a redundant `agent.md`. Do not call provider APIs or claim a deployable application. Foundation completion does not imply any later milestone is authorized or achieved.

## M1 — FastAPI shell and validated configuration

Create `pyproject.toml`, a verified dependency lockfile, package entry points, Pydantic settings, safe errors/logging, the API application factory/lifespan, and health routes. Use injected provider and retrieval interfaces; provider-backed chat remains unavailable until later milestones.

Validate settings and missing-secret handling with offline checks. `/health/live` can succeed; `/health/ready` must fail when no approved index exists. Verify no key is logged, no network inference occurs at startup, and configuration cannot be overridden by chat input.

Implemented with injected fake knowledge probes and a default unavailable adapter. Provider interfaces/adapters are the next M2 task. Chat currently validates input and returns a safe unavailable result.

## M2 — Provider contracts

Implemented and verified offline on 2026-10-14. See [PROVIDERS.md](PROVIDERS.md) for actual behavior and the counter/format/live-compatibility gates. The deliverables below remain the acceptance contract; mocked success does not establish account or hosted-model compatibility.

Implement asynchronous Luna chat and Qwen embedding adapters against OpenRouter, validated structured outputs, batch/index mapping, usage accounting, deadlines, and bounded retry handling. Preserve the chosen models; do not silently switch models when a parameter fails.

Offline fixtures cover successful responses, malformed output, unsupported schema behavior, reordered embedding items, mismatched dimensions, and transient failures. A later explicitly authorized compatibility screen validates account/model/endpoint behavior with minimal paid requests; adding a key does not start that screen.

### Next task deliverables

1. Add typed request/result/error contracts under `src/telescope_rag/providers/`, keeping messages, structured data, vector batches, usage receipts, and safe errors separate from provider SDK objects and HTTP transport responses.
2. Implement injected asynchronous chat and embedding HTTP adapters with runtime dependency/lockfile updates if needed. The base URL and chosen model IDs come from validated settings; public chat input cannot override them. Verify wire parameters against current primary OpenRouter documentation before implementation.
3. Validate structured JSON without silently relaxing the schema, changing models, inventing missing values, or making a second repair/judge call. Preserve the original query/message content; planner/answer prompts and graph orchestration remain M5 work.
4. Validate embedding batch indexes for missing, duplicate, reordered, or unexpected items; restore original input order and enforce nonempty finite vectors with consistent expected dimensions. Query instruction formatting must be explicit/versioned and independently verified for the hosted endpoint.
5. Add a shared execution budget/deadline and usage receipts: reserve input/output capacity before dispatch, count the application's HTTP attempts and retries, track model/provider IDs and reported usage, and bound response/body sizes. Separate chat token usage from embedding usage and record unavailable/uncertain usage honestly. Client receipts cannot establish unreported upstream routing attempts or hidden provider processing.
6. Implement at most one eligible transient retry within remaining deadline/token reservations. Disable hidden SDK/transport retries and model fallback so they cannot bypass that limit. Do not automatically retry ambiguous potentially billed timeouts, authentication errors, unsupported parameters, malformed output, or schema failures. Keep cancellation and bounded lifecycle cleanup intact.
7. Write mocked transport tests and update the API/architecture/progress documentation. M2 does not enable successful clinic chat, crawl the website, create an index, or deploy Docker.

### Definition of done

Mocked tests verify success, refusals/truncated completions, malformed/missing JSON, schema mismatch, authentication errors, rate limits, eligible server failures, ambiguous timeout handling, retry exhaustion, cancellation, token/deadline exhaustion, missing usage, embedding index/order/dimension errors, nonfinite values, and safe logs/errors. Prove that exhausted budgets or missing credentials dispatch no HTTP request, and initialization/health/shutdown make no inference request. Both English and Arabic text must pass unchanged through adapter input construction.

Run the existing regression suite plus the new mocked cases, lint, format, lockfile, package, and documentation checks. Record exact results in `PROJECT_STATUS.md`. Provider compatibility remains unverified until a separately authorized minimal live screen; mocked completion is sufficient to finish the initial M2 implementation.

## M3 — Public website ingestion

M3 collection/preparation/review implementation has started and runs independently of inference. [INGESTION_RUNBOOK.md](INGESTION_RUNBOOK.md) records implemented commands, drafts, and gates. Completion of collection/preparation does not complete paid embedding, live candidate/index publication, source acceptance, or the retrieval comparison below.

Implement allowlisted discovery, robots-aware collection, redirect/address checks, immutable snapshots, structural extraction, deterministic cleaning and formatting, variable-length chunks by source format/ownership, pre-embedding validation, directory coverage, hours records, candidate indexing, and audit manifests. Follow [INGESTION.md](INGESTION.md); token limits are overflow guards, not fixed-size targets or default overlap windows.

Validate local HTML/block fixtures first, including adjacent doctors, FAQ pairings, tables/footnotes, Arabic normalization, oversized units, and preserved source mappings. Then run the authorized public-site collection. Review extraction, cleaning, formatting, chunk coverage, and rejected-input manifests before paid embedding. Publish the first approved index only after dimensions, provenance, exclusions, and coverage checks pass. Compare structural chunking with a bounded fixed-window evaluation baseline on the same inputs during M3/M4; a baseline is an experiment, not the default serving policy.

## M4 — Retrieval and deterministic knowledge operations

Implement Qdrant reads, snapshot pinning, per-question evidence association, a bounded full-directory path, admitted hours records, and pure time comparison logic. Enforce read-only serving permissions separately from the ingestion writer.

Verify missing evidence, similar doctor names, unrelated service attribution, partial coverage, stale/conflicting hours, AM/PM ambiguity, overnight intervals, exact closing time, and a concurrent snapshot switch.

## M5 — LangGraph chat flow

Current checkpoint (2026-10-17): the offline mixed-path substep passed, followed
by a bounded live three-language development screen. Two actual extractive drafts
preserve their source claims, including a separately recorded Jordanian audit-failure
continuation. That earlier English doctor-role plan missed available evidence by
choosing name-only profiles; its safe unknown is not retrieval acceptance. The audit
recorder was fixed and verified. The opt-in v14 source view exposes existing
name-only limitations at exact occurrence scope. Its six-pair live screen now has
12 actual plans / 14 individually reviewed parts: useful general-role source scopes
1/3 control versus 3/3 treatment, with 5/6 versus 6/6 literal/source-valid plans.
All explicit profile-only limits hold; two material individual-page choices remain
unresolved. A prior profile-sample overgeneralization is corrected using informative
Odaibat/Rihab pages already in the admitted corpus; no source or identity change.
The planner screen's $0.04229628 exactly reconciles to key usage; its source-scope
results alone do not establish ranking/answer acceptance.

The subsequent P01/P03/P05 downstream continuation now passes with three actual
drafts, two request-local Qwen query embeddings (77 tokens) and three authenticated
exact read-only Qdrant queries. No new paid planning or index write occurred.
Primary Codex reviewed every actual draft / four final question parts: all four
role witnesses and the public-hours part are represented with correct ownership.
Scoped witness Recall@5/nDCG@5 are 1.0, conditional on 11 English cards and one card
per Arabic scope; this is not global recall or holdout acceptance. Exact replay,
92 original DOM spans / 15 chunks / four pages and 76 focused guarded tests pass.
The prior full 2,075-test result remains bound to unchanged runtime/tests.
New $0.001569545 reconciles exactly; $0.954834715 remained at October 17 15:32:57
Asia/Amman. No default adoption, retry, deployment or source/cache change.

The next cohort is now frozen: 12 new English/Arabic/Jordanian compositions / 27
information units, with 52 source chunks / eight pages / 402 exact DOM witnesses.
Twelve authored controls execute offline; primary review accepts 24 units but finds
three profile-choice clarifications too generic to request the needed page/URL.
All 12 planner inputs reconstruct without gold; 135 focused guarded tests pass.
No new actual model decision, live ranking, external request or spend occurred.
This is known-source visible preparation, not an unseen holdout or M5 acceptance.

The opt-in source-page clarification is now implemented: a separate nullable typed
choice field binds admitted document handles independently of retrieval filters,
and the presenter asks for a page URL without merging owners or trusting free-form
model reasons. Thirty-three new / 2,108 full guarded tests pass. All 12 baseline
responses replay exactly; candidate changes only three clarification messages.
No new actual model decision, provider request, source/cache/index change or spend.

**Next:** bounded live Luna schema and end-to-end acceptance after authenticated
candidate/key/route preflight, using the separate candidate plan and frozen original
questions/source expectations. Keep opt-in choices and P02/P04 intended pages
unresolved until the user chooses; actual model semantics remain unverified.
No further fixture-preparation milestone is required before this live screen.
M5 acceptance remains incomplete;
do not proceed to production adoption or M6 deployment from this development screen.
See [current status](../PROJECT_STATUS.md) and
[hours graph verification](HOURS_GRAPH.md).

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
