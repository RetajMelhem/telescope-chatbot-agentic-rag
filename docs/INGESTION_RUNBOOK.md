# M3 ingestion runbook

The collector and data preparation run separately from FastAPI. Neither command below calls a model, accesses patient systems, writes Qdrant, or changes an active index. They create new directories exclusively and refuse to overwrite existing snapshots/bundles.

## Collect public HTML

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m telescope_rag.ingestion.cli collect --snapshot-id YOUR_NEW_SNAPSHOT_ID --output data/raw/YOUR_NEW_SNAPSHOT_ID
```

The command uses collection defaults and process-environment settings without reading `.env`; model/database secrets are explicitly blanked. Maximum pages can be lowered with `--max-pages N` (1–250). Default seeds are homepage, doctors, contact, and FAQ. Internal language variants and permitted sitemap links are discovered from the site.

Collection uses HTTPS GET, approved hosts only, public-address validation, a DNS-pinned connection with TLS hostname verification, explicit redirect checks, and robots rules. Unsupported robots patterns fail closed; this is a conservative supported subset, not a claim of complete RFC pattern support. It enforces one-second host delay or stricter site hints, page/depth/request/time/control-body limits, unique-discovery limits, and independent link/record caps. Collection is sequential, within the configured concurrency ceiling. Compressed responses, PDFs, non-UTF-8 HTML, unsupported resources, and JavaScript-only gaps are not silently converted into evidence.

Raw `.html` bytes and typed `.json` records are stored under `raw/`; `manifest.json` records pages, redirect/discovery outcomes, timestamps, hashes, and coverage gaps. No credentials/query values or rejected off-domain URLs are stored in rejected-reference records. Private/action routes, medical-report forms, testimonials, and form links are excluded. `coverage_complete` means bounded discovered traversal, not proof of every possible website fact or semantic completeness.

## Prepare a draft bundle

```powershell
.\.venv\Scripts\python.exe -m telescope_rag.ingestion.cli prepare --snapshot data/raw/YOUR_NEW_SNAPSHOT_ID --output data/processed/YOUR_NEW_SNAPSHOT_ID
```

Preparation verifies the manifest, original bytes/hashes, decoded HTML, page count and snapshot identities before extraction. It parses main content and meaningful footer information, then cleans known noise/placeholders and preserves structural ownership. It produces doctor units, paired FAQs (including closed accordions), coherent sections, lists, and tables. Source-backed context includes headings, FAQ questions, owner names, table labels, captions, and footnotes. NFC/layout normalization preserves Arabic letters/diacritics, names, numbers, negations, and time qualifiers. Unhandled or ambiguous structures are explicit audit gaps.

Source spans use original DOM locators and offsets within original extracted node text. Meaningful image alternatives use explicit `::attr(alt)` locators and `attribute=alt`; these labels do not establish individual insurance coverage or clinical suitability. Spans are not raw HTML byte offsets. Original bytes remain available for review. The preparation policy and source mappings are versioned; chunk IDs are reproducible hashes and Qdrant point IDs are UUIDs.

The current `html-structure-v3` / `structure-nfc-v4` policy preserves heading-only facts and publication statuses, scopes sibling cards by their source containers, binds comparison identities/fields and recovery labels/results, retains source list introductions/qualifiers, and resets footer scope. A qualification such as Doctor of Medicine does not create a doctor identity. Whole placeholder post/step containers and personal testimonial carousels are excluded with audit reasons. All-three-viewport hidden prototypes are excluded; responsive-only and animated content remain supported. Five-column direct-cell CSS grids preserve headers and literal category `grid-row: span N` relationships; four-column Elementor comparison matrices preserve complete procedure rows and explicit category context. Unsupported layouts fail closed. Version 3 introduced audited decorative-image exclusions, direction-only/layout normalization and footer context cleanup; version 4 carries reviewed source-admission and confirmed identity metadata. Informative partner/doctor labels and meaningful numbers remain source text.

Default chunks are **drafts**: `token_count=null`, `embedding_ready=false`. The CLI does not guess counts or expose a flag to bypass verification. The library's `prepare_document` can enforce the 1,200-token ceiling only with an explicitly verified compatible counter and embedding format. It counts the complete formatted input including the document prefix. Small units remain small; oversized units split within their owner at paragraphs/items/rows, then safe sentence boundaries. An indivisible overflow is quarantined. There are no fixed token windows, automatic overlap, minimum target, or padding.

The bundle includes prepared document JSON, `summary.json`, `audit.json`, an unapproved `review-template.json`, and `metadata/embedding-input-plan.json`. The exact-input plan is bound to the prepared digest and reports unique inputs/reused occurrences; every chunk remains mapped, with no fuzzy identity or cross-language merging. It is a draft audit projection, not an embedding authorization. The audit binds the exact collection-manifest digest and prepared-document digest and retains all doctor occurrences and raw hours candidates, including hours inside FAQs. Hours interpretation remains unresolved; a candidate is not an executable schedule or a claim about appointment availability.

## Apply reviewed source decisions

After reviewing exact source conflicts, compile a trusted `AdmissionPlan` with collection/input-prepared digests, all unit dispositions and exact segment/context keys, exclusion reasons and explicitly confirmed aliases. Plans apply only to their sealed input. Never generate corrections from raw website instructions, a similarity match or an LLM assertion. Keep earlier bundles and plans intact.

```powershell
.\.venv\Scripts\python.exe -m telescope_rag.ingestion.cli admit --bundle data/processed/REVIEWED_INPUT --plan data/manifests/REVIEWED_PLAN.json --output data/processed/NEW_ADMITTED_BUNDLE
```

`admit` validates complete source accounting, source/unit digests, order, atomic FAQ/table boundaries, owner/qualifier context and alias collisions before creating the new directory. It selects existing published recovery rows; it does not overwrite conflicting values. Disputed cards/body descriptions are excluded with reasons while unaffected material and source-backed service headings remain. Misleading department titles are trimmed from doctor context/path and marked non-authoritative; original page titles remain citation metadata. Main directory/profile role statements supply specialties.

The admitted bundle includes policy/receipt and optional primary-directory metadata under `metadata/`. Literal owner IDs/names remain source occurrences; confirmed display/identity fields are separate and bound to the policy. Source selection is recorded as reviewed, while `approved=false` and token/format gates remain intact. A later token-validated rebuild needs its own exact prepared digest approval. The versioned serializer preserves old sealed document digests when admission fields were absent; adding metadata cannot silently alter older receipts.

## Review before embedding/indexing

Review source-to-chunk coverage and every gap, removed-content reason, doctor occurrence, FAQ association, table/qualifier, language variant, and conflict. Repeated names/content on different pages retain separate provenance. A page's title/URL does not establish a doctor's specialty. Template or contradictory pages need a source decision; do not silently merge them into an authoritative directory. Directory coverage stays `requires_source_review` until reviewed. A source-span check proves mapping, not semantic completeness: the first M3 bundle passed mapping checks but the subsequent full-page LLM review found omitted facts and incorrect relationships. Keep those forms of evidence separate.

The preparation library and provider adapter require verified counter/format profiles. After those are established and the bundle is rebuilt, a reviewer must explicitly approve its exact digests and accepted crawl gaps. The provided template remains unapproved. Known source/preparation gaps cannot be erased merely by changing the approval flag; malformed mappings and incomplete preparation fail.

`embed_reviewed` is a library entry point for an explicitly authorized embedding run. It requires source approval and validated preparation, pins model/dimensions/format/preparation/tokenizer configuration, forms bounded batches with independent budgets, and optionally uses an immutable content/configuration cache. Exact reuse retains every occurrence as a separate point. Synthetic counters, model fixtures, and test review approvals are not production profiles or reviews.

`write_candidate` validates mappings, ownership, source policy, configuration, dimensions, finite nonzero vectors, unique IDs, and payload byte bounds before its first write. The ingestion-only `QdrantCandidateWriter` creates a new named collection and uploads bounded points with cosine vectors. It has no alias-switch or deletion API. Failed uploads leave an unpublished candidate for inspection; no automatic destructive rollback occurs. Candidate names bind snapshot, prepared digest, and embedding configuration. Actual Qdrant access/permissions remain unverified.

Initial publication, active-alias promotion, verified hosted conventions, and source-based retrieval evaluation remain gated work. Compare structural chunking against a fixed-window evaluation baseline on identical approved inputs/settings during M3/M4; no superiority claim follows from a successful parser test.

## Current evidence

See [PROJECT_STATUS.md](../PROJECT_STATUS.md) for the latest retained snapshots, actual counts, tests, known gaps, and next action. Earlier semantic/quality ledgers remain intact. Applied source decisions are recorded in `data/manifests/m3-source-admission-plan-v2.json` and `data/manifests/m3-source-admission-review.json`, with a readable `artifacts/m3-source-admission/REPORT.md`. Source selection and mapping checks are distinct from clinical truth and provider readiness. Local generated content is ignored by Git/Docker. No generated source text, credentials, or vectors belong in a commit.
