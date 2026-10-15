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

### Count reviewed source with the pinned Qwen tokenizer

The current verified tokenizer is a public `tokenizer.json`, not model weights. Obtain it from the immutable upstream URL `https://huggingface.co/Qwen/Qwen3-Embedding-8B/resolve/1d8ad4ca9b3dd8059ad90a75d4983776a23d44af/tokenizer.json` into a local ignored directory. The counter verifies SHA-256 `83cdf8c3a34f68862319cb1810ee7b1e2c0a44e0864ae930194ddb76bb7feb8d` and the locked library version before use. The current local copy is `.tools/qwen-tokenizer/1d8ad4ca9b3dd8059ad90a75d4983776a23d44af/tokenizer.json`.

```powershell
.\.venv\Scripts\python.exe -m telescope_rag.ingestion.cli count --bundle data/processed/m3-source-admitted-v2 --tokenizer .tools/qwen-tokenizer/1d8ad4ca9b3dd8059ad90a75d4983776a23d44af/tokenizer.json --profile openrouter-deepinfra-v1 --output data/processed/YOUR_NEW_COUNTED_BUNDLE
```

`count` performs offline preparation, without `.env`, provider dispatch or index access. It requires the direct admitted bundle's exact document/audit/review/plan/receipt bindings, preserves selected `ExtractedDocument` values and alias/source metadata, enforces the structural token ceiling, regenerates directory chunk references and writes a new digest-bound receipt. It retains the previous admission receipt as a parent record rather than relabeling that receipt. Earlier bundles cannot be overwritten. There is no free-form verification flag: the named hosted profile is the separately verified profile in [PROVIDERS.md](PROVIDERS.md). Omitting `--profile` uses an upstream-only unverified format and leaves embedding blocked. Neither profile approves a bundle automatically.

Earlier verified output: `data/processed/m3-token-validated-v2` (107 documents, 1,701 chunks, 1,441 unique inputs). One 1,617-token Arabic experience unit split into 1,195/438-token chunks at existing paragraph boundaries. Independent checks verified all 8,189 raw spans and complete selected-body interval coverage. Its separate exact-digest technical review is historical. The latest source-reviewed candidate is `data/processed/m3-llm-semantic-token-validated-v6` (107 documents, 955 chunks, 834 unique inputs); its source review is true and execution approval remains false. Use the exact current digests/evidence in [PROJECT_STATUS.md](../PROJECT_STATUS.md), not an earlier review receipt. `metadata/embedding-configuration.json` pins model, dimensions, format hash, preparation and tokenizer versions. A technical review does not certify clinical truth or authorize deployment.

Chunks and raw evidence remain in local immutable bundles for reproducibility. The authorized v6 corpus run stored vectors plus each original chunk's text, source and ownership metadata as 955 separate points in unpublished candidate `telescope_public_018817ac10ec05ecad92adb9`. Its 834 exact vector inputs preserve all 121 reuse occurrences. The local `EmbeddingCache` is ignored by Git/Docker; it retains validated vectors for inspection/reuse, while a later approved Qdrant snapshot will serve retrieval. No active alias has been published.

### Validate exact digests and run bounded ingestion

Review source-to-chunk coverage and every gap, removed-content reason, doctor occurrence, FAQ association, table/qualifier, language variant, and conflict. Repeated names/content on different pages retain separate provenance. A page's title/URL does not establish a doctor's specialty. Template or contradictory pages need a source decision; do not silently merge them into an authoritative directory. Directory coverage stays `requires_source_review` until reviewed. A source-span check proves mapping, not semantic completeness: the first M3 bundle passed mapping checks but the subsequent full-page LLM review found omitted facts and incorrect relationships. Keep those forms of evidence separate.

The preparation library and provider adapter require verified counter/format profiles. After those are established and the bundle is rebuilt, a reviewer must explicitly approve its exact digests and accepted crawl gaps. The provided template remains unapproved. Known source/preparation gaps cannot be erased merely by changing the approval flag; malformed mappings and incomplete preparation fail.

`embed_reviewed` is a library entry point for an explicitly authorized embedding run. It requires source approval and validated preparation, pins model/dimensions/format/preparation/tokenizer configuration, forms bounded batches with independent budgets, and optionally uses an immutable content/configuration cache. Exact reuse retains every occurrence as a separate point. Synthetic counters, model fixtures, and test review approvals are not production profiles or reviews.

`write_candidate` validates mappings, ownership, source policy, configuration, dimensions, finite nonzero vectors, unique IDs, and payload byte bounds before its first write. The ingestion-only `QdrantCandidateWriter` creates a new named collection and uploads bounded points with cosine vectors. It has no alias-switch or deletion API. Failed uploads leave an unpublished candidate for inspection; no automatic destructive rollback occurs. Candidate names bind snapshot, prepared digest, and embedding configuration. Local authenticated inventory and denial of the tested reader update route are now verified; actual candidate upload/full permission coverage remains unverified.

Initial publication, active-alias promotion, verified hosted conventions, and source-based retrieval evaluation remain gated work. Compare structural chunking against a fixed-window evaluation baseline on identical approved inputs/settings during M3/M4; no superiority claim follows from a successful parser test.

## Current evidence

The bounded v6 execution proposal is preserved in `artifacts/m3-embedding-execution-preflight-v1/REPORT.md` with ordered `offline-plan.json`: 955 points / 834 unique document inputs / 71,804 tokens, capped at 53 application HTTP attempts, batch 16, retries zero and 600 seconds. Following the user's next-step authorization and live pricing/access checks, that corpus stage passed using new execution copy `data/processed/m3-execution-approved-v6-v2`, cache `data/processed/m3-qwen-cache-v6-v1` and receipts `artifacts/m3-candidate-execution-v6-v1`. All 53 requests succeeded without retry; every reported token count matched the pinned local count. All 955 payloads/vectors and 834 cached vectors were verified. See `artifacts/m3-candidate-authorization-v1/REPORT.md`. The original false approval, historical policy receipts and sealed source files remain unchanged; the v2 copy changes only its separate approval record. An incomplete preparation-only v1 copy is preserved and retired, with no dispatch from that attempt.

`scripts/plan_embedding_candidate.py` remains an offline proposal tool: it does not approve the source, instantiate a cache or dispatch. The later query stage and its implementation/budget gates remain unexecuted. A document embedding/candidate pass does not establish retrieval quality, runtime source-policy handling, HNSW construction or chatbot readiness.

The initial local check failed while Docker was unavailable. The subsequent repair preserves the original Qdrant 1.19.2 container, volume, keys and internal network, and adds a loopback-only gateway; see [DEPLOYMENT.md](DEPLOYMENT.md). Three authenticated preflight receipts now pass, including after both services restart. Each records 13 bounded requests, empty collection inventories, candidate absence, unchanged aliases, unauthenticated inventory 401, reader update 403 and admin absent-target control 404. No collection or point was created. Evidence is in `artifacts/m3-local-preflight-repair-v1/REPORT.md`; the earlier failed receipt remains historical.

`QdrantCandidateAudit.preflight` and its final audit now use `PATCH {}` on a fresh random name confirmed absent before/after, rather than collection creation or point upsert. Only 401/403 counts as reader denial; unexpected success or any other status stops the check. These methods are permission probes, not GET-only observation. The dedicated local checker additionally forbids create/upsert/delete/alias routes, external URLs and updates to the actual candidate; it requires the explicit flag below. It never invokes the provider or candidate writer. Use a new evidence output on every run; never overwrite a receipt. The original v6 false approval and all source files remain immutable.

```powershell
& .\.tools\uv\bin\uv.exe run --locked python -m scripts.check_local_qdrant_preflight `
  --allow-absent-update-probe --output artifacts/NEW_LOCAL_PREFLIGHT.json
```

A local pass alone does not authorize paid embedding/indexing or establish every server permission, current provider pricing/access, retrieval quality or runtime source-policy enforcement. The completed corpus stage has its separate authorization and checked price; its conservative $0.01 allowance was arithmetic at the checked route price with strict token/attempt caps, not a new server-side USD billing cap. Do not repeat that paid run. The empty-target checker above is only for the first run: now that the candidate exists it correctly rejects a nonempty database. Inspect the existing candidate through bounded reads and the saved every-point verification; do not delete/reinitialize it to make preflight pass. Any later paid stage needs its own concrete scope/budget decision.

The offline source-witness benchmark is frozen at `artifacts/m3-retrieval-benchmark-v1` against the v6 corpus. Its 90 cases have exact chunk/citation witnesses, per-part scope outcomes and independent semantic reviews. See [EVALUATION.md](EVALUATION.md) for the pinned manifest hash, read-only verifier and metrics. Benchmark preparation made no corpus, approval, embedding, Qdrant or runtime change. Source uncertainty metadata must be honored and tested by the future retrieval/answer pipeline; it is not implemented enforcement.

See [PROJECT_STATUS.md](../PROJECT_STATUS.md) for the latest retained snapshots, actual counts, tests, known gaps, and next action. Earlier semantic/quality ledgers remain intact. Applied source decisions are recorded in `data/manifests/m3-source-admission-plan-v2.json` and `data/manifests/m3-source-admission-review.json`, with a readable `artifacts/m3-source-admission/REPORT.md`. Source selection and mapping checks are distinct from clinical truth and provider readiness. Local generated content is ignored by Git/Docker. No generated source text, credentials, or vectors belong in a commit.
