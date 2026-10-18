# Local service retrieval and reply repair

Date: 2026-10-18, Asia/Amman. Local MVP only; default/production stays unavailable.

The cheek-enhancement paragraph already existed in both admitted facial-aesthetics
pages. One actual run ranked it first; another paraphrase returned five generic
homepage passages and missed it. The original screenshot has no saved internal
trace, so its exact failure stage cannot be established. The later observed miss
is reproducible from its captured query/vector/ranking.

## Implementation

The local retriever keeps its five dense hits and appends up to three literal BM25
matches. It can also include up to two complete nearest section-context records.
Context must share the same document, source language, literal/canonical ownership
and an exact ancestor heading path. An oversized or partly scoped-out parent set
is omitted rather than partly represented or replaced by a broader one. These are
candidates, not machine-certified factual relationships. Original chunks stay
separate and unchanged; Luna must establish actual relevance and scope.

The local per-part candidate ceiling is ten; global assembly remains sixteen groups
and the existing evidence limit. Dense queries still use one exact Qdrant read per
part, with at most one Qwen batch and two Luna calls per request. BM25 is built in
memory from admitted text. No corpus embedding, Qdrant write, persistent cache
write, alias publication or source-bundle modification occurred. Earlier/default
retrievers retain their previous behavior because both additions default to zero.

The local planner keeps service searches broad unless the visitor restricts their
source. It preserves original wording and explicit method exclusions. The writer
can answer supported public content while correcting an inaccurate premise or
identifying an unconfirmed detail. It must distinguish a documented alternative
from an explicitly requested method. Real identity/time ambiguity, private actions
and personal medical advice retain their boundaries. Invalid group IDs used as
chunk citations still fail closed; the instructions now distinguish both IDs.

Replies use the center's voice and natural qualifications such as حسب معلوماتي,
without inventing staff identity, credentials, actions or private access. Technical
IDs remain outside the answer. The browser wraps numeric runs in isolated LTR
elements, preserving original digits, spacing, leading zeros and signs in Arabic
replies and source excerpts. It uses safe DOM text nodes, not HTML interpretation.

## Evidence and limits

**38 new / 2,182 guarded offline tests pass**, with zero skips in this environment,
plus lint/format and lock checks. Tests cover scoped literal matching, separate
owners, unchanged dense prefixes/batching, failed dense validation, bounded source
context and actual UI JavaScript execution. Nine Node checks cover phones, Arabic
digits/decimal separators, dates, ranges, nonbreaking spaces and untrusted markup.
Node is an optional test dependency; it is not needed to run the application.

**22 actual development requests / 27 returned parts** received individual primary
Codex language review. One invalid-citation request was rejected and retained.
Earlier cheek/jawline misses and an incomplete price explanation remain recorded.
Later cases cover English/Arabic services, explicit surgical restrictions, supported
alternatives, price uncertainty, excluded booking, insurance and staff voice. Final
backend wording has three real localhost HTTP examples; exact phrasing still varies.
One preceding case explicitly states the source-backed nonsurgical category. Some
later replies instead distinguish fillers from unconfirmed surgery. This is scoped
development evidence, not a universal correction/wording guarantee.

All 19 citation occurrences match six original chunks across four saved official
pages; **73 exact DOM spans** verify. A fresh official Arabic facial-aesthetics page
also corroborates the cheek card and its nonsurgical parent category. It was used
for corroboration, not new admission. The UI renderer passes text/DOM tests; browser
automation is disabled, so visual browser acceptance is not claimed.

A separate offline replay preserves the same ninety historical raw queries and
captured dense rankings. Selected answer-witness coverage across 72 eligible records
is **62.42% for dense five**, **64.27% for the additive pool**, and **71.95% for dense
ten**. The additive pool has two gains and no losses against the actual dense-five
baseline; context-witness scores are unchanged. Dense ten is stronger on these old
labels, so no claim that the additive strategy is universally best is justified.
This replay is not current planner end-to-end or exhaustive relevance acceptance.
BM25 lookup alone has approximately 0.23 ms median; this excludes context expansion
and network/model latency. Extra evidence can increase answer input and latency.

Evidence: ignored `artifacts/service-retrieval-gap-v1/` through
`service-retrieval-gap-v7/`, including actual traces, failed attempts, source checks,
individual judgments, offline comparison and final tests. Audited responses report
$0.076313045 for 34 Luna / 17 Qwen attempts. Five real HTTP requests lack provider
payload auditing. The observed key increase is $0.113560360 and includes concurrent
user queries; **$0.277946935 remained** at the observation. Independent billing
reconciliation is not claimed. No more paid requests were needed for the UI edit.

Remaining: candidate status may contain a supported reply with unconfirmed details
explicit in its prose; it is not certification of insurance coverage/availability.
Broader retrieval and production acceptance remain unproven. A subsequent user
report found social links in saved website HTML but absent from retained chunks;
restoring that separately proven hyperlink evidence is the next active repair.
