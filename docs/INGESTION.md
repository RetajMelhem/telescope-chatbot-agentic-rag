# Website ingestion and knowledge lifecycle

Status: M3 collection, structural extraction, cleaning/formatting, chunking, reviewed source selection, verified Qwen counting and candidate writing are implemented. The authorized corpus run produced 834 distinct embeddings and verified all 955 occurrence payloads/vectors in an unpublished local Qdrant candidate. The initial dense/BM25/hybrid comparison has executed; dense remains provisional. Runtime source-policy enforcement and publication remain pending. A later targeted semantic diagnosis found coherent broader units suitable for a controlled granularity experiment, without establishing a need for wholesale re-chunking; see [RETRIEVAL_DIAGNOSIS.md](RETRIEVAL_DIAGNOSIS.md). See [INGESTION_RUNBOOK.md](INGESTION_RUNBOOK.md) and [PROJECT_STATUS.md](../PROJECT_STATUS.md) for exact bundles, checks and remaining gates.

## Source boundary

The approved source is public content on `telescopecenter.com` and its `www` variant. Initial discovery seeds are the homepage, [doctors](https://telescopecenter.com/doctors/), [contact](https://telescopecenter.com/contact-us/), and [FAQs](https://telescopecenter.com/faqs/). Discover other public service, technology, facility, insurance, and informational pages from approved internal links and permitted sitemaps.

Inspect robots rules and website usage constraints before bulk collection. Crawl conservatively. Do not submit forms, authenticate, access patient reports, appointment slots, private calendars, admin routes, external maps/social platforms, or follow arbitrary URLs supplied by visitors.

Use HTTPS, validate the allowlisted hostname and public IP resolution on every fetch and redirect, and block private/loopback/link-local addresses and unsafe ports. Prevent a public link or redirect from becoming access to internal infrastructure.

Public pages that describe how to contact/book may provide information, but the ingestion job never performs the described action. Do not index form fields, testimonials with patient-identifying details, user submissions, or exposed private content.

## Discovery and collection

1. Read the configured seeds, robots rules, and permitted sitemap locations.
2. Discover internal pages within 250 pages and depth four. Use two concurrent fetches and a one-second delay per host as initial limits; honor stricter site limits.
3. Record each discovered URL's result: collected, duplicate, disallowed, failed, or deferred. Exceeding a limit makes coverage incomplete.
4. Canonicalize URLs conservatively, preserve language variants, and verify each redirect before following it.
5. Save bounded raw HTML snapshots and fetch metadata. Start with a two-megabyte limit per page and text/HTML extraction; PDFs and OCR need an explicit supported ingestion path later.
6. Prefer static extraction. If content is visible only through JavaScript, record the gap and add a bounded rendering step only when needed.

## Prepare data before embedding

The required order is **snapshot -> parse source structure -> clean -> normalize/format -> form structural chunks -> validate -> embed**. Do not flatten the entire page into plain text before identifying ownership, headings, question/answer pairs, lists, or tables. Formatting preserves these relationships; it is not an LLM rewrite of clinic facts.

1. Retain immutable raw HTML, fetched URL/time, original extracted text, and source locations. Parse the HTML into content blocks while preserving document order, heading hierarchy, cards, definition/FAQ pairs, list groups, and table captions/headers/rows.
2. Remove scripts, styles, duplicated navigation, cookie banners, empty form controls, and verified placeholder material. Record removed blocks and reasons. Do not remove a meaningful contact/hours block merely because it appears in a footer. Do not assume all repeated material is irrelevant.
3. Decode HTML entities, normalize line endings and redundant layout whitespace, and apply conservative Unicode NFC normalization to the retrieval representation. Remove direction-only LRM/RLM/ALM marks and treat a zero-width space as a layout break; keep Arabic letters, diacritics and joining controls. Preserve paragraph, list, table, and sentence boundaries. Retain original names, numbers, units, negations, time qualifiers, and punctuation. Do not fold distinct Arabic letters, transliterate names, convert ambiguous dates/times, or translate evidence into new authoritative facts.
4. Format admitted blocks as typed JSON records with deterministic embedding text: source title/heading context plus the block's own content. Render tables with explicit column labels and values; retain lists as lists and FAQs as paired questions and answers. Any repeated context must point to its own source blocks and count toward token limits.
5. Validate scope, source mapping, meaningful-content presence, exclusions, ownership, extraction coverage, and token bounds before sending an embedding batch. Ambiguous tables, broken profiles, unmapped text, or unsegmentable oversized units are quarantined with a recorded gap rather than silently discarded or guessed.

Deduplicate exact repeated content for embedding efficiency without deleting its occurrence provenance. Differences in doctor ownership, language, dates, or qualifiers remain distinct. Cleaning and formatting changes are versioned and invalidate cached embedding inputs when their output changes.

Draft bundles include `metadata/embedding-input-plan.json`: one entry per exact formatted text, literal owner and language, with every original chunk ID mapped to that entry. This projection is bound to the prepared digest and is not an approved provider batch. The embedding cache additionally binds model/configuration. All occurrences retain separate source records; M4 must collapse exact repeated evidence before spending answer-context space while retaining question links and citations. Do not merge near matches, spelling variants, translations or rows with different qualifiers.

Decorative branding/CTA/testimonial-cover labels and literal image filenames are excluded with source audit reasons. Informative image alternatives, including insurance partner names and labels with numbers or `_converted` suffixes, remain literal when they may carry information. Shared footer blocks use their own source labels; the containing page title stays in metadata rather than becoming unrelated footer embedding context. Supported four-column Elementor comparison matrices retain complete procedure rows, column headings and explicit category labels; unresolved layouts are quarantined.

`html-structure-v5` preserves a structurally established introductory header/qualifier across its nested child group, including mixed heading levels. A following group with its own introduction ends that scope; described sibling service cards and doctor identities remain independent. Visually authored heading-only lists keep their complete condition group and closing qualifier, repeating the mapped governing text if token limits require children. Narrative question headings retain their list, lead-in and closing qualification in one source section; oversized children repeat required context. Native FAQs keep their own question/answer boundary. A text wrapper is retired only when its entire normalized literal text equals its ordered child text; the wrapper receives an audit reason and unique parent text survives. Supported small comparison tables are emitted as complete matrices or explicit source category groups; the preparation layer may split oversized groups only by complete rows. A detached parallel category column without authenticated row membership is quarantined as `unsupported_parallel_category_layout`; source order or medical knowledge cannot supply the missing mapping.

The earlier audit's corpus-specific pruning used exact literal sets and DOM/context rules, informed by page-packet inspection. That ledger alone did not prove individual semantic usefulness, and its unsupported acceptance claim was retracted. The later explicit language review and independently reviewed changed representations are recorded in [PROJECT_STATUS.md](../PROJECT_STATUS.md); scripts track their exact coverage rather than replacing judgments. Retain useful short facts and governing context; preserve immutable sources and exact exclusion receipts. Source fidelity, token counts and targeted semantic regressions do not substitute for a justified usefulness decision for each final retrieval record.

`structure-nfc-v5` formats an exactly repeated heading/context/body/alt label once within an input while retaining all of its original source spans. Separate repeated list items, ordered steps and table rows are preserved. Across chunks, exact vector reuse continues to require identical text, literal doctor owner, language and embedding configuration. Two doctors sharing a specialty retain two independent records; different translations, spellings, numbers and qualifications are not duplicate facts. Source occurrences remain available for citations even when their embedding vector can be reused.

## Chunk by content structure

Use `CHUNKING_STRATEGY=structure_aware`. Chunk boundaries follow source structure and ownership; chunks have variable lengths. There is no target/minimum token size, automatic padding, or default token-overlap window.

| Source format | Preferred retrieval unit and required context |
| --- | --- |
| Doctor card/profile | One doctor's name, published role/specialty, and attached description. Keep complete when within the safety ceiling; never merge neighboring doctors. |
| FAQ | The complete question with its associated answer, under the relevant category. Preserve the question if a long answer needs multiple pieces. |
| Service/treatment page | A coherent heading/subheading section with its paragraphs, qualifications, and associated list. A generic service page does not acquire doctor-specific ownership. |
| Clinic or public doctor hours | The hours block/table plus owner, day/date, interval labels, timezone when explicit, and qualifications/exceptions. Preserve relationships needed for time interpretation. |
| Tables | Keep a small table intact. For a large table, partition by complete rows or source-defined row groups while repeating caption/column headings and retaining applicable footnotes. Preserve merged-header relationships; unresolved layout stays a gap. |
| Lists/steps | Keep a complete related list or procedure sequence when it fits. Split a long list only at item boundaries and retain its heading, ordering, and qualifiers. |
| Contact/facility/insurance block | One coherent named information block with its labels and qualifiers. A logo alone cannot establish a patient's coverage. |
| Long narrative section | Prefer subheadings, then complete paragraphs, then language-aware sentence boundaries within the same section/owner. |

Store a parent section and its ordered child block/chunk IDs when a coherent unit must be split. The full parent remains source material; only bounded child retrieval units are embedded. A future bounded parent/neighbor read may restore missing context, but cannot bypass request evidence budgets or cross an ownership boundary.

## Token limits are a guard, not the boundary policy

`CHUNK_MAX_TOKENS=1200` is an initial unmeasured safety ceiling for the complete embedding input, including repeated context. It is not a recommended optimal size or an instruction to make every chunk 1,200 tokens long. Small complete profiles/FAQs stay small; unrelated units are not combined to approach this limit.

Count with a verified Qwen-compatible tokenizer and enforce the stricter of the configured ceiling, the hosted endpoint's input limit after any verified instruction overhead, and the downstream evidence budget. Character counts are not token counts, especially across Arabic/English.

If an otherwise valid unit exceeds the ceiling, split recursively within that unit: subheading -> coherent block group -> paragraph/list item/table row group -> sentence boundaries. Repeat only the source-backed owner/heading/question/header context that the child needs. Do not use a blind character/token cut as the default. If one indivisible sentence, row, or required context cannot fit, record and quarantine it for an explicit extraction/segmentation remedy before embedding. Never emit an over-limit input or silently lose a qualifier.

`CHUNK_TARGET_TOKENS` and `CHUNK_OVERLAP_TOKENS` are obsolete. The settings loader accepts them only for compatibility with existing local `.env` files, excludes them from the active serialized settings, and does not use them for chunking. Existing `.env` files are preserved. New examples use the structure strategy and ceiling.

## Why this default, and what remains unproven

The inspected [doctor directory](https://telescopecenter.com/doctors/) contains distinct named profiles and group headings, so keeping those units separate is a source-backed design choice. [LangChain's structural splitting guidance](https://docs.langchain.com/oss/python/integrations/splitters/markdown_header_metadata_splitter) describes grouping by headings and applying size limits within groups. A generic heading splitter alone is insufficient for doctor cards, FAQ pairs, and table relationships; the HTML extraction must preserve those formats first.

This design does not require embedding-distance or LLM-based semantic chunking. [Qu et al., NAACL 2025](https://aclanthology.org/2025.findings-naacl.114/) found that semantic chunking's added cost did not produce consistent gains across their evaluated retrieval/generation tasks. That does not prove this clinic's best strategy; it argues against assuming a more complex method is automatically superior.

During M3/M4, compare this policy with a bounded fixed-window baseline on the same approved snapshot, embedding model, retrieval settings, and bilingual questions. Review retained facts, source mapping, doctor/FAQ/table integrity, retrieval recall, answer support, total embedded inputs, and cost. Select or refine the policy using those results. Cleaning/chunking is implemented and tested structurally; no embedded retrieval comparison has run yet.

Create separate source-backed structured records for hours and a complete directory manifest. Extracted values must point to exact supporting source spans. Ambiguous extraction remains unresolved; a model's inferred interval is not sufficient for time calculations.

## Evidence metadata

Each chunk records `chunk_id`, `document_id`, `canonical_url`, `page_title`, `language`, `section_path`, typed `block_type`, `parent_block_id`, source spans for both content and repeated context, `original_text`, `retrieval_text`, `token_count`, `content_hash`, `fetched_at`, `snapshot_id`, optional explicitly established `doctor_id`, and preparation/tokenizer/embedding-format versions. The document retains extractor version and original HTML; ordered source block IDs are present in span records. Explicit image-alt attribute spans preserve informative labels. DOM/source mappings survive normalization; normalized offsets are never presented as raw HTML offsets.

Use reproducible IDs derived from source identity, content, and chunk configuration. Qdrant point IDs must use a supported UUID or integer representation; keep a human-readable hash in metadata. Retain every original source occurrence when duplicate content appears on different pages.

Reviewed source admission is a separate selection step before embedding. A sealed plan accounts for every original unit, binds the input prepared/collection digests, and retains or excludes actual source segments without medical rewriting. A damaged description may be replaced only by its existing heading as a name-only service record. FAQ pairs and table rows remain atomic; mandatory owner/header/qualifier context cannot be trimmed. Unknown/missing selectors fail closed.

A grouped table admission may select an ordered subset of complete original row segments; it cannot select individual cells or reorder rows. All table context, including categories, headers and footnotes, remains mandatory. A source-boundary rebuild rebinds the sealed plan to the new extracted units and must prove exact prior source accounting, identity preservation and all earlier source decisions before a new technical approval. Quarantined source layouts remain in the immutable raw snapshot with explicit exclusion receipts; accepting that exclusion does not authenticate the missing relationship.

Human-confirmed doctor aliases add `canonical_doctor_id` / `canonical_doctor_name` metadata while `doctor_id`, `doctor_name`, source text and coordinates stay literal. The admission-policy hash and source issue codes travel with chunks. These aliases are not new biographies, specialty assertions or rewritten website names. Derivative directory titles marked non-authoritative cannot establish department membership; use explicit main-directory/profile roles. Source selection does not verify token counts, approve provider dispatch or certify clinical truth. See the [source admission runbook](INGESTION_RUNBOOK.md#apply-reviewed-source-decisions).

An explicitly authorized offline semantic review may reorganize already sourced units through a new digest-bound preparation/admission plan. Each usefulness/removal decision requires an actual language judgment with source evidence, a rationale and a plausible question or necessary context contribution. Scripts may track coverage, apply enumerated exact-source decisions and validate provenance; a default retain rule, keyword screen or inventory count is not semantic acceptance. Independently review changed representations and high-risk source relationships before accepting a candidate.

Keep raw snapshots and earlier bundles immutable. Preserve before/after source-unit and owner-occurrence receipts when a single profile's portrait/page heading and card heading are consolidated under its established card owner; never combine different people because their roles or text resemble one another. Exact source text/spans survive grouping. Useful labels can become context instead of standalone retrieval hits. Complete row tuples from a disputed layout may be represented only when their own cells/headers are authenticated independently of an unresolved category relationship; the unsupported relationship remains a documented gap.

Unresolved source scope stays unresolved in diagnostic `source_issue_codes`. A generic FAQ cannot acquire a specific procedure from a neighboring question, and a free-consultation advertisement cannot become a universal fee claim. Diagnostic metadata and human-authorized canonical aliases are separate from factual source text. A completed source audit does not prove retrieval optimality or authorize embeddings, indexing or publication. The current audit scope and evidence are recorded in [PROJECT_STATUS.md](../PROJECT_STATUS.md).

## Embedding contract

Use `qwen/qwen3-embedding-8b` for both documents and queries. The upstream model supports vectors up to 4096 dimensions; configure 4096 initially and verify the actual endpoint response before creating a collection. See the [Qwen model card](https://huggingface.co/Qwen/Qwen3-Embedding-8B).

Pin the embedding model, effective provider configuration, actual dimensions, cleaning/formatting/chunking policy, normalization, and query instruction format in the snapshot manifest. Only validated formatted chunks enter embedding batches. Query instructions follow the verified hosted endpoint's behavior; do not assume it applies the same prefixes as the local model or apply a prefix twice.

M2 supplies the bounded embedding adapter described in [PROVIDERS.md](PROVIDERS.md). Use a new budget for each batch; cap both text count and total formatted tokens before dispatch. The default counter refuses dispatch and the format profile must be explicitly verified. M3 can validate extraction/cleaning/chunking offline before those live prerequisites are resolved; no source or paid-embedding gate is waived by the adapter tests.

Validate response item indexes, count, finite vector values, and dimensions. Preserve batch-to-chunk mapping even if responses arrive reordered. Cache embeddings by content plus embedding configuration. Changing dimensions, model, or effective embedding conventions requires a new compatible index; never mix incompatible vectors in an active collection.

## Publishing an index

Build a candidate collection such as `telescope_public_<snapshot_id>`, with cosine vectors and source payloads. Maintain a finite manifest of collected pages, failures, doctor directory coverage, structured hours, collection parameters, and embedding configuration.

Validate required seed coverage, source ownership, exclusions, dimensions, and evaluation fixtures before changing the `telescope_public_active` alias. Initial publication needs a reviewed snapshot; later refreshes use the same validation gate. Use atomic alias updates and retain the prior approved collection for rollback. See [Qdrant collections and aliases](https://qdrant.tech/documentation/manage-data/collections/).

Pin each chat request to one resolved snapshot so an update cannot mix generations within an answer. Never overwrite or delete the active collection while serving.

## Freshness and gaps

A refresh cadence is still to be decided. The initial freshness threshold is 168 hours, a design default. Stale hours and other time-sensitive facts cannot support a current open/closed claim. For less volatile content, indicate the snapshot date and evaluate the appropriate freshness policy.

A missing page or crawl error does not prove that a service or doctor does not exist. Do not retire a previously collected document on a transient failure without reviewing the coverage change.

The initial limited inspection did not establish Friday hours. M3 subsequently found published working-hours FAQ evidence, retained as raw unresolved clinic/pharmacy/optical-center information. Review its exact source, ownership, wording, and freshness before interpreting intervals in M4. No opening times or appointment availability have been inferred by the ingestion pipeline.
