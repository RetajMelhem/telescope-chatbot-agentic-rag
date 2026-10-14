# Project status

Last updated: 2026-10-15 (Asia/Amman).

Current milestone: **M3 page-by-page review and subsequent data-quality repairs complete. The latest draft uses version 3 extraction/formatting with an exact-input occurrence plan. Source admission/conflict handling, verified counting/formatting, paid embedding, and live index publication remain pending.**

This is the continuity entry point for Codex. Read it before substantive work and update it after each completed task. The full roadmap is [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md); repository rules are in [AGENTS.md](AGENTS.md).

## Confirmed project scope

FastAPI + LangGraph; GPT-6 Luna through OpenRouter; Qwen3 Embedding 8B; Arabic, English, and everyday Jordanian Arabic; answers supported by public clinic website content. Public doctor working hours are in scope when published. Patient files, record edits, private calendars, appointment availability, and bookings are excluded. Docker deployment is required in a later milestone.

## Completed foundation work

- [x] Product specification and representative answer behavior.
- [x] Folder architecture and empty implementation directories.
- [x] LangGraph request pipeline, ingestion pipeline, budgets, citations, and uncertainty behavior.
- [x] Website ingestion, provenance, directory coverage, hours records, and index lifecycle design.
- [x] FastAPI request/response and health contract.
- [x] Docker deployment design and future runbook.
- [x] Offline evaluation cases and release criteria.
- [x] Milestone roadmap and decision/open-item records.
- [x] Canonical `AGENTS.md`; redundant `agent.md` removed.
- [x] Living progress file with required Codex updates.
- [x] `.env.example`, local `.env` with empty key fields, Git exclusions, and Docker exclusions.
- [x] Final document, directory, example-schema, and configuration consistency checks.

## Milestones

| Milestone | Actual status |
| --- | --- |
| M0 — specification/scaffold | Complete; foundation consistency checks passed |
| M1 — FastAPI/configuration shell | Complete; offline checks and local server smoke passed |
| M2 — provider contracts | Complete for initial offline implementation; live compatibility remains gated |
| M3 — public website ingestion | Collection/preparation implemented; source acceptance, embeddings, live index, and retrieval comparison pending |
| M4 — retrieval and deterministic operations | Not started |
| M5 — LangGraph chat flow | Not started |
| M6 — Docker implementation/verification | Not started |
| M7 — source acceptance/widget integration | Not started |

## Completed M1 implementation

- [x] Python package metadata, `uv.lock`, local `.venv`, and supported app factory entry point.
- [x] Validated environment/dotenv settings with masked secrets, consistent bounds, and process-environment precedence.
- [x] `/health/live` and bounded `/health/ready`, with injected knowledge probe and unavailable default adapter.
- [x] Chat request schemas that reject runtime configuration, invalid roles/types, and oversized input; valid requests return `503` until M5.
- [x] Application-issued request IDs, body-size limits, deadline cancellation, CORS, safe error envelopes, and content-free application logs.
- [x] Lifecycle cleanup and production diagnostic-doc suppression.
- [x] Synthetic-settings and fake-probe tests; local loopback-only Uvicorn startup check; updated run instructions.

## Verification and evidence

Completed: current target/parent folder inspection, confirmation that the target did not exist before this task, limited public website inspection, current primary technology references, and creation of the scaffold.

Foundation consistency verification passed on 2026-10-14:

- 13 Markdown files and 16 implementation/data directories with placeholders match the inventory.
- All 30 local document links resolve after the final status update; code fences are balanced; both JSON contract examples parse.
- 27 example configuration values match the planned models, timezone, and budgets; example secret fields are empty.
- Git/Docker environment exclusions are present; tracked examples contain no detected OpenRouter key pattern. Local `.env` values were not read or printed by verification.
- `AGENTS.md` references this progress file; redundant `agent.md` is absent.
- At M0 completion, runtime Python files, Dockerfile, and application tests were absent; M1 subsequently implemented the API shell and tests.

M1 verification on 2026-10-14:

- `uv lock --check`: passed; Python 3.11.9 and 30 locked packages.
- `uv run --locked ruff check .`: passed.
- `uv run --locked ruff format --check .`: passed.
- `uv run --locked pytest`: 56 passed. External connections are blocked; loopback/Unix sockets are allowed for Windows/event-loop internals. Tests use no live local services, real provider keys, or the user's `.env`.
- Temporary Uvicorn server on `127.0.0.1` with an ephemeral port: liveness `200`, readiness `503`, valid chat `503`; request IDs matched JSON/headers. Server shut down after the check.
- Configuration example and documentation consistency checks: completed during handoff verification.

The first test run exposed Starlette's HTTPX2 requirement and Windows asyncio's need for a local socketpair; both were resolved before the final passing suite. Dependency versions are recorded in `uv.lock`, not inferred from older notes.

No provider inference, embeddings, full crawl, index creation, live Qdrant request, Docker build, or public deployment has run. The API shell works locally; there is no working RAG chatbot yet. Existing `.env` was not rewritten or printed.

## Latest revision: data preparation and Git

- [x] Replaced the fixed token-target/overlap design with variable-length chunks that follow doctor/FAQ/section/list/table structure and source ownership.
- [x] Made the mandatory pre-embedding sequence explicit: snapshot, structural parsing, cleaning, normalization/formatting, structural chunking, provenance/input validation, then embedding.
- [x] Retained a 1,200-token safety ceiling, including context, with recursive splitting inside a unit and recorded gaps for unsegmentable inputs. This is a design default, not a proven optimal size.
- [x] Added `CHUNKING_STRATEGY=structure_aware` and `CHUNK_MAX_TOKENS`; existing target/overlap settings are accepted only for compatibility and excluded from active serialized settings. Local `.env` was preserved.
- [x] Added M3/M4 structural-integrity checks and a controlled comparison against a fixed-window baseline. The baseline is for evaluation, not the default serving policy.
- [x] Initialized a local Git repository on `main`; baseline checkpoint is `e940884`. The revision is kept as a separate local checkpoint; use `git log -2 --oneline` and scoped diffs to inspect it. No remote is configured.
- [x] Added `.gitattributes` for consistent source line endings and verified Git ignores `.env`, local environments/tools, and generated data.

Revision verification on 2026-10-14: 60 offline tests passed; Ruff lint/format, lockfile validation, staged-source/secret-exclusion review, documentation/configuration consistency, and Git whitespace checks passed. This verifies settings compatibility and the design handoff; it does not establish chunk quality or real-source retrieval performance. The cleaner/chunker and corpus comparison remain unimplemented.

## Known gaps and blockers

- Collection/preparation fixtures and public collection run successfully; source-quality and format/count gates remain before embedding.
- Working-hours evidence is now retained from English/Arabic FAQ pages. Clinic, pharmacy, and optical-center wording remains raw/unresolved until reviewed and interpreted; no availability claim is established.
- Provider account access, hosted structured-output behavior, returned model IDs/dimensions, token-count compatibility, and Qwen formatting remain unverified. Default counting refuses dispatch; synthetic test profiles are not production profiles.
- Hosting, widget integration, refresh cadence, and content-review ownership remain decisions for later milestones.

## Completion audit and M2 readiness

Audit date: 2026-10-14. Reviewed the current tracked implementation, settings, tests, specifications, milestone boundaries, Git exclusions, and package output. The initial tree was clean at `b6a0e0e` and the existing 60 tests passed. This audit does not rely on older project readiness notes.

Concrete issues fixed and regression-tested:

- Middleware-generated body-limit, timeout, and unexpected-error responses now retain CORS headers only for configured allowed origins.
- API `405` errors preserve the `Allow` header. The API contract now explicitly distinguishes standard plain-text CORS preflight transport responses from JSON application errors.
- Adapter cleanup now has a configurable five-second default deadline and fixed, content-free timeout/failure warning events.
- Settings reject incorrect OpenRouter API paths and ports; the approved HTTPS `/api/v1` base accepts an optional trailing slash.

Verified audit results:

- 74 offline tests passed, including new boundary/shutdown/URL cases; Ruff lint and formatting passed.
- `uv lock --check` passed; 30 locked packages remain unchanged. A wheel built successfully and includes the app factory/configuration, with no local `.env`, tests, generated corpus, or tool environment.
- Current local configuration validated without displaying its values. Existing `.env` was preserved; the new shutdown setting has a default and does not require rewriting it.
- Temporary localhost Uvicorn smoke passed: liveness `200`, knowledge readiness `503`, valid chat placeholder `503`; issued request IDs match headers/JSON. The server shut down after the check.
- All 38 local documentation links resolved at final handoff, including the M2 deliverables anchor; JSON examples/fences, 44 active example settings, deprecated-setting exclusions, and secret-free example values checked.
- Git ignores secrets, environments/tools, generated corpus, and distribution artifacts; Docker exclusions now also include build/distribution artifacts. No remote or paid provider request was involved.

Decision: **no remaining blocker found for M2's offline provider-contract implementation**. M0/M1 and the revised ingestion specification are ready inputs. Provider account compatibility, actual returned embedding dimensions, source coverage, cleaner/chunker quality, Qdrant enforcement, RAG answers, and Docker release remain unverified future milestones; they are not claimed complete by this audit.

## Completed M2 implementation

- [x] Typed chat/embedding interfaces, safe errors, explicit count/format profiles, and content-free attempt receipts.
- [x] Async OpenRouter HTTP adapters using runtime HTTPX2, injected mock transport, fixed selected models, strict JSON schemas, parameter-support routing, and disabled fallbacks/hidden retries.
- [x] Strict local JSON/schema/usage validation; refusal/truncation handling without repair; exact embedding batch/index/dimension checks and finite nonzero vectors restored to input order.
- [x] Shared logical-call/HTTP-attempt/input/output/deadline budget; fresh reservation before every attempt; unknown/partial usage keeps full reservations; reasoning is not double charged; usage overrun blocks further dispatch.
- [x] At most one eligible retry, no retry for ambiguous read/write timeout, cancellation propagation, response byte limits, and bounded client cleanup.
- [x] Default unavailable token counter and unverified embedding format prevent dispatch. Production counting/format verification is explicitly deferred to the authorized compatibility screen, not guessed.
- [x] Provider settings/defaults, dependency lock, architecture/pipeline/ingestion/Codex instructions, and [provider contract documentation](docs/PROVIDERS.md) synchronized.

M2 offline verification on 2026-10-14: **180 tests passed**, including all 74 API/configuration regressions and 106 new provider cases. Ruff lint/format and `uv lock --check` passed; HTTPX2 was promoted from development to runtime without changing the 30-package lock inventory. Synthetic credentials/counts/formats and HTTP fixtures were used; no paid request or user's key was used by tests. The first provider run had two invalid synthetic settings fixtures; those were corrected without relaxing application settings validation.

`uv build --offline` built the source distribution and wheel successfully. The wheel includes provider modules and runtime HTTPX2 metadata, with no local secrets, tests, data, or tools. All 46 local document links/anchors, 14 Markdown files' fences, and two JSON examples validated; all 50 active example settings match defaults, and local configuration validates without disclosure. Git whitespace/exclusion and scoped staged-source checks passed. Existing `.env` was preserved. No remote was configured or used.

The API remains a shell: readiness is unavailable by default and valid chat returns `503`. No complete crawl, cleaner/chunker, Qdrant index, graph, Docker build, or deployment has run. Existing `.env` was preserved. Mock results establish local protocol/budget behavior, not live compatibility, token accuracy, source quality, or chatbot grounding.

## M3 implementation and collection

- [x] Separate ingestion models and CLI; exclusive immutable snapshots and draft bundles; no API chat/network inference integration.
- [x] Robots-aware HTTPS GET collector, public-IP validation with DNS-pinned connections and TLS hostname verification, safe redirect/path handling, allowlisted discovery/sitemaps, and bounded link/request/time/page/body/record accounting.
- [x] Structural HTML extraction, deterministic cleaning/NFC formatting, doctor/FAQ/section/list/table boundaries, meaningful footer retention, and source spans into original extracted text/DOM.
- [x] Variable-length chunker with source-backed repeated context, verified-count ceiling/overflow quarantine, reproducible IDs, and explicit draft mode when counting/format is unavailable.
- [x] Collection/prepared-digest-bound review artifacts, source-backed doctor occurrences/raw hours candidates, and provenance/ownership checks.
- [x] Gated embedding batches, immutable configuration/content cache retaining every occurrence, and candidate-only Qdrant write contracts; no alias/delete path. These are tested offline, not executed against OpenRouter/Qdrant.

The initial snapshot `data/raw/m3-20261014` contains 97 pages and hit a repeated-navigation discovery limit. Its draft bundle `data/processed/m3-20261014-initial` remains retained for audit and is superseded for further work. Real-source review exposed shared-footer source mismatches and placeholder contamination; those were corrected with regression cases, without modifying the old artifacts.

The corrected `public-static-pinned-v2` collector produced `data/raw/m3-20261014-v2`: **127 pages**, 20,095 recorded outcomes, six sitemaps, all English seed pages and Arabic doctor/FAQ variants, and no crawl-budget gaps. This establishes bounded discovered static-HTML traversal, not all-site semantic completeness. Final policy excludes medical-report actions and testimonial routes. Source content includes placeholders, template pages, and inconsistent derivative doctor directories; collection alone does not admit them as clinic knowledge.

Latest prepared bundle: `data/processed/m3-20261014-v4` (raw snapshot ID remains `m3-20261014-v2`). It contains **2,239 draft chunks**, 128 doctor occurrences across pages, and two raw hours candidates. Independent review matched all **9,854 source/context spans** to stored raw DOM text/offsets/IDs and verified raw/page/collection/prepared digest bindings. No placeholder retrieval contamination or invalid source mappings were detected. Main English/Arabic directories retain 11 names each; FAQ pages retain all 27 native pairs each plus one source-backed CTA question unit. The two Arabic name-only profiles are preserved without invented biographies/specialties.

Remaining source gaps are explicit: 20 placeholder documents, 106 quarantined placeholder-content occurrences, seven pages without admitted main content, and unsupported merged CSS-grid/direct text on `/extra/` and `/ar/extra/`. Derivative doctor directories also need source acceptance rather than specialty inference from their titles/URLs. The technical audit is recorded in ignored `data/manifests/m3-20261014-source-review.json`. Older prepared v2/v3 bundles remain immutable and superseded by v4. All latest chunks have `token_count=null`, `embedding_ready=false`; source approval remains false and directory completeness requires review.

M3 verification passes **338 offline tests** (all 180 existing regressions plus 65 collection, 56 preparation, 27 review/candidate, and 10 CLI cases), Ruff lint/format, lock validation, and offline distribution/wheel build. Runtime Beautiful Soup and HTTPcore2 dependencies are explicit; 33 packages are locked across supported Python branches. All 15 Markdown files, 54 local links/anchors, two JSON examples, and 50 active example settings validated. Wheel/sdist include the new implementation/dependencies and exclude local secrets/generated source content. Git whitespace, staged source, and generated-data/secret exclusions were checked. No paid model call, embedding, live Qdrant write/read, active-alias change, retrieval comparison, Docker build, or deployment ran. Local `.env` was preserved.

## Next concrete step

Complete **M3 source admission and provider preparation** using raw snapshot `m3-page-audit-live`, latest prepared bundle `m3-quality-final`, quality ledger `data/manifests/m3-quality-review.json`, and earlier semantic ledger `data/manifests/m3-page-by-page-review.json`. Review remaining website copy/identity conflicts, sparse profiles, template/prototype source decisions, and hours ownership/wording. Extra-page LASIK/PRK recovery values differ across published rows; exclude conflicting prototype material or retain explicit conflict handling. Confirm an admitted source scope and directory manifest; repeated source occurrences are not unique doctors.

Establish verified Qwen-compatible counting, hosted document/query formatting and dimensions, rebuild token-validated chunks, then perform an explicitly authorized bounded embedding/candidate run. Source approval must bind exact collection/preparation digests; the generated template remains unapproved. Live publication and structural-versus-fixed-window retrieval evaluation remain pending. Follow [M3](docs/IMPLEMENTATION_PLAN.md#m3--public-website-ingestion), [INGESTION_RUNBOOK.md](docs/INGESTION_RUNBOOK.md), and [PROVIDERS.md](docs/PROVIDERS.md). M4 retrieval follows approved knowledge; clinic chat stays unavailable until M5.

## Page-by-page review handoff (superseded prepared bundle)

2026-10-15: Completed the user's full-page comparison and repair task. Three LLM reviewers read complete source/chunk packets for all 127 allowed public pages (43+42+42), with raw DOM inspection for ambiguous layouts. Their original judgments were 90 pages with collection defects, 24 with source-only problems, and 13 initially faithful. A fresh 127-page crawl had the same URL inventory and no meaningful text, heading, image-alt, footer, or description-metadata changes; this ties the semantic review to the refreshed static content. Private/action routes and unsupported external content remain outside collection scope.

Confirmed defects repaired in `html-structure-v2` / `structure-nfc-v2`: missing heading-only services/facilities/qualifications/warnings, qualification degrees mistaken for person identities, unowned founder biography/message, stale sibling section ancestry, comparison-field and recovery-timeline misassociation, detached list qualifiers, missing insurance categories/image labels, footer context leakage, incomplete placeholder/testimonial cleanup, and unsupported explicit CSS grid rows. Public coming-soon status is retained; all-viewport hidden prototypes are excluded without removing animated/responsive public content. Direct text nodes and image-alt source mappings are supported; bilingual title boilerplate no longer determines a unit's language.

Latest retained artifacts:

- Raw snapshot: `data/raw/m3-page-audit-live` (127 pages; no bounded-traversal gaps).
- Prepared bundle: `data/processed/m3-page-audit-final` (**2,092 draft chunks**; older snapshots/bundles unchanged).
- Complete semantic ledger: `data/manifests/m3-page-by-page-review.json` (all 127 URL-specific rationales/findings and post-fix checks).
- Readable report: `artifacts/m3-page-audit/REPORT.md`; original reviewer evidence and fresh-comparison receipts remain alongside it.
- Final independent retention/mapping receipt: `artifacts/m3-page-audit/final-validation.json`.

Verified all **9,749 source/context spans** against saved raw DOM text/attributes, IDs and offsets, plus raw/decoded/page/manifest/prepared digests. No non-excluded selected heading, paragraph, list item or table cell was unrepresented. Native FAQ answers remained under their own questions; contamination and fake-degree-identity checks found no defects. **389 offline tests passed** with Ruff lint/format; package/lock/document/Git checks passed. These mapping/retention results are separate from clinical/semantic acceptance and are not proof of every hidden/unlinked/JavaScript-only fact or future retrieval quality.

Website-origin limitations remain explicit: name-only profiles, inconsistent literal spellings, derivative dermatologist directory titles over ophthalmology/anesthesia copy, malformed/unequal translations and inconsistent prototype copy. The collection preserves or quarantines these source cases; it does not medically rewrite them or silently merge identities. All chunks remain uncounted, unapproved, and unavailable for embedding. No OpenRouter/embedding/Qdrant call, active-alias change, Docker build or deployment ran; `.env` was preserved. The next task is the source/provider acceptance step above.

## Latest data-quality audit

2026-10-15: Rechecked the latest prepared snapshot for normalization, decorative noise, exact duplicates and residual source relationships. Confirmed further defects were repaired in `html-structure-v3` / `structure-nfc-v3`: decorative branding/CTA/testimonial-cover labels and image filenames are audited exclusions; direction-only marks/layout breaks normalize without changing Arabic letters, diacritics or joining controls; unrelated page titles are removed from footer embedding context while staying in metadata; four-column Elementor comparison matrices keep complete procedure rows, headers and explicit category context, with ambiguous shapes quarantined.

New immutable bundle: `data/processed/m3-quality-final`, **127 documents / 1,763 source chunk occurrences / 1,459 unique embedding inputs / 304 reusable repeated inputs**. `metadata/embedding-input-plan.json` binds the prepared digest and maps every original chunk once, preserving all occurrence provenance. Exact reuse remains scoped to literal owner/language/text and actual cache configuration; there is no fuzzy name, translation, qualifier or clinical-value merging. Candidate points remain per occurrence; M4 must collapse repeat evidence for answer context.

Independent audit matched **8,615 source/context spans** to original raw DOM text/attributes/IDs/offsets and raw/prepared digests. It found no omitted selected non-excluded main/footer heading, paragraph, list item, table cell or informative alt, no detected normalization/control/source-mapping/duplicate-ID defect, and no crossed native FAQ answer. All 280 informative alt occurrences retained; source doctor-unit count remains 238 and raw hours candidates remain two. The old prepared bundle's exact digest was verified unchanged. The raw snapshot and previous artifacts remain intact.

Review artifacts: `data/manifests/m3-quality-review.json` (all-page proof and source differences), `artifacts/m3-quality-audit/REPORT.md` (readable readiness report), and `artifacts/m3-quality-audit/validation.json`. Full offline suite: **430 passed**, Ruff lint/format passed; lock, offline sdist/wheel, 15-document/54-link checks and generated-data/secret exclusions passed. Restored comparison rows expose four literal source-difference candidates across Extra language variants (LASIK fast/very-fast; PRK slower/very-fast); they remain unapproved, not guessed corrected facts. Other previously recorded source-origin caveats remain. Clean drafts are ready for source admission/provider preparation; they are not yet ready for paid embedding or proven optimal for retrieval. No provider/Qdrant/Docker/deployment action or environment-file change ran.
