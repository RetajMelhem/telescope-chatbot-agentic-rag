# Website ingestion and knowledge lifecycle

Status: planned workflow. No corpus has been crawled or embedded.

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

## Extraction and chunking

Preserve headings, lists, tables, doctor profile associations, treatment names, time qualifiers, and meaningful contact sections. Remove duplicated navigation, cookie banners, empty forms, scripts, and placeholder copy. Links in a navigation menu are discovery hints; they do not establish doctor-specific services.

Preserve original Arabic/English text and section boundaries. Use normalized text for retrieval only, while retaining original text for citation and audit. Never translate sources into new authoritative clinic facts.

Start with approximately 500 tokens per chunk and 75-token overlap using an appropriate tokenizer. Keep a short profile, hours block, or table together when possible. Do not combine different doctors merely to fill a chunk.

Create separate source-backed structured records for hours and a complete directory manifest. Extracted values must point to exact supporting source spans. Ambiguous extraction remains unresolved; a model's inferred interval is not sufficient for time calculations.

## Evidence metadata

Each chunk records `chunk_id`, `document_id`, `canonical_url`, `page_title`, `language`, `section_path`, `source_span`, `original_text`, `retrieval_text`, `content_hash`, `fetched_at`, `snapshot_id`, `source_type`, optional explicitly established `doctor_id`, and extraction/chunker versions.

Use reproducible IDs derived from source identity, content, and chunk configuration. Qdrant point IDs must use a supported UUID or integer representation; keep a human-readable hash in metadata. Retain every original source occurrence when duplicate content appears on different pages.

## Embedding contract

Use `qwen/qwen3-embedding-8b` for both documents and queries. The upstream model supports vectors up to 4096 dimensions; configure 4096 initially and verify the actual endpoint response before creating a collection. See the [Qwen model card](https://huggingface.co/Qwen/Qwen3-Embedding-8B).

Pin the embedding model, effective provider configuration, actual dimensions, normalization, and query instruction format in the snapshot manifest. Query instructions follow the verified hosted endpoint's behavior; do not assume it applies the same prefixes as the local model or apply a prefix twice.

Validate response item indexes, count, finite vector values, and dimensions. Preserve batch-to-chunk mapping even if responses arrive reordered. Cache embeddings by content plus embedding configuration. Changing dimensions, model, or effective embedding conventions requires a new compatible index; never mix incompatible vectors in an active collection.

## Publishing an index

Build a candidate collection such as `telescope_public_<snapshot_id>`, with cosine vectors and source payloads. Maintain a finite manifest of collected pages, failures, doctor directory coverage, structured hours, collection parameters, and embedding configuration.

Validate required seed coverage, source ownership, exclusions, dimensions, and evaluation fixtures before changing the `telescope_public_active` alias. Initial publication needs a reviewed snapshot; later refreshes use the same validation gate. Use atomic alias updates and retain the prior approved collection for rollback. See [Qdrant collections and aliases](https://qdrant.tech/documentation/manage-data/collections/).

Pin each chat request to one resolved snapshot so an update cannot mix generations within an answer. Never overwrite or delete the active collection while serving.

## Freshness and gaps

A refresh cadence is still to be decided. The initial freshness threshold is 168 hours, a design default. Stale hours and other time-sensitive facts cannot support a current open/closed claim. For less volatile content, indicate the snapshot date and evaluate the appropriate freshness policy.

A missing page or crawl error does not prove that a service or doctor does not exist. Do not retire a previously collected document on a transient failure without reviewing the coverage change.

The limited website inspection on 2026-10-14 did not establish Friday opening hours. That is an evidence gap, not a fact that the clinic is closed. Complete ingestion and any clinic-approved source extension must be handled explicitly rather than inventing a schedule.
