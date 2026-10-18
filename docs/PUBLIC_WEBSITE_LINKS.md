# Official website social links

Local MVP repair, 2026-10-18. The saved official homepages contained informative
social-icon hrefs, but the admitted 955 vector chunks contained none of those
addresses or platform labels. Improving ranking alone could not recover them.

The local app now loads a separately reviewed supplement from
`artifacts/public-website-links-v1/reviewed-links-plan.json`. It preserves eight
source occurrences across the English and Arabic homepages, pointing to four
distinct destinations: Facebook, Instagram, LinkedIn and YouTube. Both original
and newly fetched official homepages were checked. External profiles were never
fetched; website publication does not establish independent account verification,
current posts, message delivery or private account access.

The supplement digest is
`42b6ff716b519affa9c917422904a80426fac9bd59e83d03299bcfa2683cd331`,
bound separately to the unchanged base prepared digest. Startup checks every raw
HTML hash, source identity/time, unique DOM locator, literal label and exact href.
The base corpus, tokenizer, admission decisions, vectors, alias, query cache and
Qdrant readiness inventory are unchanged. No new corpus embeddings or index writes.
Reproduce the same supplement offline with:

```powershell
& .\.tools\uv\bin\uv.exe run --locked python scripts/prepare_public_website_links.py --output artifacts/public-links-reproduction-v1
```

The output directory must be new. Compare its digest with the pinned value before
using it; a changed source or inventory needs another review. This explicitly
bounded two-page repair is not a review of all outgoing links on all 107 pages.

The existing second Luna stage receives eligible link facts alongside ordinary
evidence. There is no keyword router, extra model, external fetch or new loop.
The model judges relevance; code enforces exact part/source/language/owner/type
capabilities. Doctor-specific, private, ambiguous and time-calculation parts cannot
borrow clinic social links. An unsupported platform remains unconfirmed rather
than being invented or declared nonexistent. A candidate reply may explain a
supported part and explicitly state an unsupported detail in the same prose.

The separate strict `WebsiteConversationalDraft` schema has per-sentence
`chunk_ids` and `website_link_ids`, requiring at least one support reference. Old
conversational callers retain their original schema when the supplement is absent.
Link-only answers never manufacture vector-chunk quotations. Independent response
projection rechecks link scope and selected destinations before publishing prose.

Local JSON adds `website_links`, `website_links_digest` and question-owned
`website_link_ids`. Each link record retains source URL, document/snapshot IDs,
fetch time, original HTML hash, locator, literal label and outgoing target URL.
The main reply has no technical citation IDs. Clickable platform names appear
under it; expandable website-source details retain selected source occurrences.
The UI only links validated HTTPS destinations on the four approved platform
hosts, uses safe text nodes and opens links with `noopener noreferrer`.

The eight unique prompt records occupy 957 verified Qwen retrieval tokens under a
separate 1,600-token supplement ceiling, sent once per draft rather than repeated
per part. This is additional to the existing assembled-evidence ceiling. Normal
chat input remains provider-reported; this is not an exact Luna input count.
Two Luna calls and at most one Qwen query batch remain the request allowance.
Supplying a supplement can require the second stage even when ordinary retrieval
finds nothing. Extra input has a small cost; no universal latency claim is made.

Verification: **38 new / 2,220 full offline tests pass**, zero failures/errors/skips,
plus lint/format. Tests include source/hash/digest/href tampering, unsafe target
hosts, owner/language/type/page/operation boundaries, mixed unknown/private parts,
bad/duplicate IDs, shared budgets, and six executions of the actual UI renderer.
These authored tests verify contracts, not model semantic judgment or visual pixels.

Two actual development requests passed the hosted schema and were individually
read by primary Codex: Arabic Facebook confirmation with the exact target; English
Instagram/YouTube plus explicit TikTok uncertainty and independently calculated
Friday 14:00 opening. These are two requests / three returned parts, not exhaustive
future-answer acceptance. Measured request durations were 7.50 and 13.03 seconds.
Provider traces record four Luna and two Qwen query attempts, no retries, reported
cost $0.009679885. The point-in-time key remaining was $0.257830345; metadata-window
increase differed from returned costs, so settled billing reconciliation is not
claimed. No additional paid repetition is required for transport verification.
Two offline API replays preserve the exact saved actual prose, questions and link
metadata. The restarted localhost app passes readiness and serves the new renderer.

Evidence is in ignored `artifacts/public-website-links-v1/`: source plan/proof,
current official-page corroboration, actual request/response traces, individual
semantic review and offline tests. The browser automation setting prevents visual
browser acceptance. This targeted fix does not establish broad data completeness
or production readiness. Continue hands-on local acceptance before portable API
Docker packaging.
