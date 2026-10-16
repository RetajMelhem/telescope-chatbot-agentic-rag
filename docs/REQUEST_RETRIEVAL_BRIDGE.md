# Request-scoped query embeddings and dense reads

`RequestDenseRetriever` now supplies the existing `EvidenceRetriever` contract
for explicit nonproduction HTTP/graph composition. It bridges planner-issued
public search queries to verified Qwen query formatting and bounded exact dense
reads on a pinned unpublished local candidate. Default API serving remains
unavailable, dense remains provisional and no index/profile/source is promoted.

Trusted construction supplies the existing settings/catalog, exact
`EmbeddingConfiguration`, explicitly loaded pinned `QwenPreparationCounter`,
embedding provider, `CandidateDenseReader` and optional read-only query cache.
The complete catalog and reader configuration bind before dispatch. Chunk
preparation/tokenizer/format metadata must match. The format hash uses ingestion's
existing `embedding-format-v1` namespace; no dataset metadata is rewritten.
Production configuration, retries, incompatible model/dimensions/format/counter
and top-k above the reader's existing 20-hit ceiling are refused. No credential,
client or tokenizer is implicitly loaded; callers retain resource ownership.

For each request:

1. Verify snapshot/digest, one to four distinct part IDs, exact query text and
   source scopes. Complete-source reads stay in the graph's admitted catalog path
   and do not call this search adapter. Unknown documents fail before dispatch;
   empty known scope intersections return empty results with no fallback search.
2. Resolve document, literal/canonical owner, block type and source language to
   exact pinned point IDs before top-k. This interprets declared literal filters,
   never names, pronouns, negations or purpose semantics. The planner remains
   responsible for correct targets and scope; ranking scores establish no facts.
3. Compute the same exact query-cache identity as earlier preparation: embedding
   configuration hash, complete hosted format and unchanged formatted text.
   Language, punctuation, qualifiers and query differences remain distinct.
   Validate every relevant cache entry before the first possible paid request.
   Corrupt cache data fails; it is not replaced through paid fallback.
4. Deduplicate only identical embedding inputs within this request. Every part,
   owner/source scope and retrieval result remains separate. Embed uncached
   inputs in at most one batch using the graph's existing `ExecutionBudget`.
   Count complete prefixed inputs with the verified Qwen tokenizer; Luna's
   reported-usage accounting is unchanged. No new ledger or chat token guard.
5. Validate dimensions, vectors, result ordering/identity and the new embedding
   receipt against that same budget. The route stays `deepinfra/us`, with the
   documented Qwen ID mapping only. Missing optional model/provider/usage metadata
   stays unknown; supplied conflicting metadata or counts fail. Counted
   reservations remain when usage is absent. Unknown is never called verified.
6. Query each nonempty scope once, under the request deadline and bounded
   concurrency. The reader sends `filter.must.has_id` with exact allowed point
   IDs and `params.exact=true`. It rejects known-but-outside-scope points,
   changed payloads, invalid scores and duplicates. Results return in original
   part order. Failed reads return no partial batch; cancellation joins/cancels
   in-flight child tasks, without retry.

The bridge never writes query vectors or text to a cache, embeds corpus chunks,
changes sources, creates/updates collections, builds indexes, switches aliases
or approves evidence. New vectors live only within the request. Cache hits can
avoid all embedding calls, but external read-only cache identity/integrity still
needs trusted provisioning. The existing evaluation embedding runner and
unfiltered reader defaults retain their prior behavior.

Qdrant's official [filter documentation](https://qdrant.tech/documentation/search/filtering/)
documents exact-ID membership, and its [query API](https://api.qdrant.tech/v-1-18-x/api-reference/search/query-points)
supports filters with vector queries. This software reference is never a clinic
fact source. Filter wire construction is mock-tested here; physical local-server
behavior and performance of the new scoped path remain unverified.

Sixty-six new guarded tests cover exact Arabic/English/Jordanian query text,
prefix/cache identity, deduplication with distinct owners/parts, hits/misses and
read-only caches, corrupt entries, invalid requests/configuration, empty scopes,
metadata/usage uncertainty, foreign points/altered payloads, deadlines, request
concurrency, cancellation and real ingestion-produced format metadata. The full
HTTP tests exercise actual middleware, graph, chat/embedding adapter and candidate
reader with mocked transports. Synthetic tokenizer fixtures prove mechanics,
not actual Qwen counts or model behavior.

A separate zero-dispatch preflight binds the actual 107-page/955-chunk bundle,
verified local tokenizer bytes/library and 90 existing query-cache vectors to
the bridge. An initial check exposed a missing namespace in the new format-hash
comparison; the initial code/receipts are preserved, the canonical recipe is
restored and a producer-generated regression now covers it. No source/cache
metadata changed to make that check pass. This preflight is not a fresh source
semantic audit, real database query or source/serving approval.

Evidence is in `artifacts/m5-request-retrieval-bridge-v1`. All **1,654 guarded
offline tests** pass (66 new), with Ruff
lint/format (169 files), the 65-package lock and whitespace checks. All 90 actual
query-cache keys match the new recipe; complete prefixed counts total the same
4,758 tokens. One old/new unfiltered reader request also matches byte-for-byte
under mocked transport. These checks do not measure new live retrieval quality.
No actual provider
metadata/inference, embedding, Qdrant, website-fetch, subagent or deployment
request ran. No real credentials were loaded into providers; additional API
spend is $0. The last allowance observation remains $1.1424752 at
2026-10-16 17:34:06 UTC, unrefreshed in this step.

The [offline response projection](OFFLINE_RESPONSE.md) is now implemented with
question-owned citations and explicit unverified outcomes. Next is source-bound
public-hours preparation and pure time calculations, retaining each question,
source quotes/citations and explicit unknown/excluded/
clarification outcomes. Earlier planner/source/ambiguity failures, time/directory
completion, real draft compatibility and approved publication/readiness remain
acceptance gates. The [completion budget plan](COMPLETION_BUDGET.md) continues to
defer large paid experiments; no automatic dispatch or serving adoption follows.
