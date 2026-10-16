# Offline response projection and citations

The nonproduction graph now has a closed, rendered response contract through
`OfflineChatService.respond`. Trusted construction selects it with
`create_app(..., offline_chat_service=service, offline_response_format="rendered")`.
The existing draft format remains the default for an injected service. There is
no request/environment toggle, new route, provider stage, source approval or
production adoption. Without a service, chat still returns 503. Production
injection and a rendered format without a service are rejected.

This is the final presentation stage of the offline prototype. Its facts remain
literal candidate source excerpts, with semantic support and live model behavior
unverified. It does not produce an accepted natural-language clinical answer.
The existing planner/source/ambiguity failures remain separate acceptance gates.

## Wire contract

`POST /api/v1/chat` accepts the same closed request. Its selected 200 response is
`OfflineChatResponse`, version `offline-response-v1`:

| Field | Actual behavior |
| --- | --- |
| `request_id` | The application-issued UUID, matching `X-Request-ID`. |
| `status` | Original `draft_ready`, `not_found`, `out_of_scope` or `clarification_required`; never `answered`. |
| `answer`, `answer_format` | Deterministic plain text containing every original part, its status message and complete selected excerpts with citation markers. |
| `language` | Original graph `en`, `ar` or `ar-JO`; Arabic status messages serve both Arabic varieties. Source quotations retain their original language. |
| `questions` | Original order, issued IDs, exact question text, individual candidate/unknown/excluded/clarification status, answer text, citation IDs, unchanged reason code and admitted-scope completeness. |
| `citations` | One record per question/selected occurrence, with exact quotation, stored URL/title/section/language, chunk/document/parent/snapshot IDs, fetch time, separate literal/canonical owner IDs/names and source caveat codes. |
| `unresolved_questions` | Ordered IDs of all noncandidate parts; candidate parts still have unverified semantic support. |
| `knowledge` | Snapshot/digest and oldest **cited** fetch instant, or null when no excerpts are cited. |
| `review_notice` | Fixed localized notice identifying an unverified offline draft. |
| Verification flags | Always `offline_only=true`, `semantic_grounding_verified=false`, `luna_compatibility_verified=false`. |

Citation IDs such as `C1.1` are scoped to this response. Identical text, owners or
chunks across questions never remove a question or transfer its citation. IDs,
question associations and quotation fields are authoritative; bracket-like text
inside a source quotation is untrusted source text, not a citation capability.
Consumers must display plain text as text, never interpret quotations/questions
as HTML or parse their contents to create links/tools. Citation URLs come only
from the bound catalog. Title metadata is a source label, not proof of a doctor's
specialty. Canonical aliases remain separate from literal source ownership.

All emitted fetch times use ISO 8601 UTC while retaining the original instant.
No source text is normalized, translated, shortened, summarized or medically
rewritten. Raw DOM provenance stays in the unchanged catalog/source artifacts;
the response exposes selected occurrence metadata rather than the full manifest.

## Projection checks and limits

The pure projector revalidates the closed result and original request against
the actual run: issued request/part IDs, complete literal question coverage,
order, language, outcome, states/reasons and evidence digest. For every citation,
it rechecks the part's offered representative occurrence, declared source scope,
source-use restrictions and exact source text/URL/document/snapshot/fetch/owner
bindings. Hidden coalesced copies and sibling citations cannot become new
citations. Complete-source candidates must retain every eligible offered group.
These are structural and literal checks, not semantic relevance or entailment.

Missing evidence, context-only claims, incomplete scope, evidence limits and
unavailable hours calculations keep their original unknown reasons. The response
never interprets missing material as closed hours or whole-website absence.
Excluded and ambiguous parts remain explicit, with no factual quotations. A
clarification message identifies the original part; producing a more specific
accepted clarification remains part of later model behavior acceptance.

Invalid projection returns sanitized `502 / offline_response_failed`; existing
graph/provider failures retain `offline_draft_failed` and deadlines retain 504.
There is no output repair, fallback, retry, extra model/judge, new budget guard,
cache persistence or knowledge write. Cancellation propagates through the
existing graph/provider path. Request IDs, citations and budgets are isolated
between concurrent requests. No input, source text or provider error is added to
default logs.

## Verification and next step

**1,733 guarded offline tests pass**, including **79 new checks**. New tests use
actual compiled graphs, HTTP middleware, chat/embedding adapters and the dense
reader with injected fixtures/mocked transports. They cover all three language
varieties, mixed outcomes, exact qualifiers/metadata/owners, hidden/sibling
citations, source drift, complete/incomplete scopes, UTC conversion, literal
injection-like text, cache/search/full-source paths, shared budgets, concurrent
IDs, cancellation, failure logs and closed OpenAPI/default configuration. A
fixed-request comparison proves the draft and rendered methods send identical
planner/draft payloads. This does not measure generalization or live accuracy.

Ruff lint/format, locked dependencies, links, historical payload/trace replay,
source/cache preservation and secret/staging checks are recorded under
`artifacts/m5-offline-response-v1`. No paid/provider metadata/embedding/Qdrant/site
request, index change, deployment or subagent ran; this step spent $0. The last
observed allowance remains $1.1424752 at 2026-10-16 17:34:06 UTC, unrefreshed.

The [source-bound public-hours records/calculations](PUBLIC_HOURS.md) are now
implemented offline. Next is their explicit source/owner-bound graph input
contract, preserving literal date/time/reference constraints. Remaining planner/source failures, actual draft compatibility,
directory/time completion, live acceptance, readiness/publication and deployment
still block production readiness. Follow the [completion spending plan](COMPLETION_BUDGET.md);
no automatic paid experiment or serving promotion follows.
