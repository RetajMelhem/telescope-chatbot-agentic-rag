# Offline HTTP draft composition

The existing offline graph now has an explicit nonproduction HTTP service
composition. `OfflineChatService` connects typed chat input to the actual
`OfflineRagWorkflow`, preserving its validation, budgets and source policy.
This completes an offline integration boundary, not production serving or live
planner/draft acceptance. No default provider or index client is constructed.

Trusted Python code must supply settings, chat/retrieval dependencies, an
evidence catalog, assembly counter, explicit planner profile and directory
authority. Passing the service to `create_app(..., offline_chat_service=service)`
selects the draft route at `POST /api/v1/chat`. There is no environment toggle or
request field that enables it. The service and factory reject production
configuration; differing transport/graph settings are rejected before dispatch.
The default `create_app()` retains `503 / chat_not_available` and does not
advertise a successful chat response in OpenAPI. No candidate profile is adopted.

Construction, liveness, OpenAPI and shutdown do not infer. Provider/retriever
resources remain caller-owned; manage their async lifetime outside this injected
app. The existing knowledge probe retains its app-owned bounded cleanup.
Injected dependency types cannot prove offline behavior: tests use synthetic
sources, mocked HTTP transport and a fake retriever. Supplying live dependencies
would require separate authorization and preflight. This change does not expose
a network listener or deploy an application.

The HTTP request remains the same closed `ChatRequest`: original query,
language and user/assistant history only. Text/history and actual body limits
are enforced before graph dispatch. The service maps text literally, without
normalization, rewriting, semantic routing or source reassignment. One graph-owned
`ExecutionBudget` is shared by planning, retrieval and drafting. Provider
settings, token counting, retries and output caps are unchanged.

Successful offline responses use `WorkflowResult`, not the planned final answer
envelope, by default. An explicit trusted `offline_response_format="rendered"`
selects the [closed rendered response](OFFLINE_RESPONSE.md) instead, through the
same service/graph. It preserves question-owned citations and literal excerpts
without another model stage, semantic promotion or changes to the draft wire.
Both forms retain every original question and its `candidate`, `unknown`,
`excluded` or `clarification_required` state. Each quote preserves literal text,
chunk/document/snapshot IDs, source URL, fetched timestamp and separate literal
and canonical owners. No free-form final answer is claimed. Every response keeps
`offline_only=true`, `semantic_grounding_verified=false` and
`luna_compatibility_verified=false`. HTTP 200 indicates a completed prototype
result, not approved clinical accuracy or production acceptance.

The same application-issued UUID appears in JSON and `X-Request-ID`; part IDs
retain the graph's hexadecimal rendering of that UUID. Incoming request IDs are
ignored. Source manifests, provider objects, budgets, receipts, prompts, retrieval
queries and internal plans are excluded from the HTTP response. There is no
conversation storage or server-side result cache.

| Outcome | HTTP behavior |
| --- | --- |
| Candidate, missing evidence, excluded or clarification result | 200 with explicit offline/unverified result and per-part states |
| Invalid input, extra configuration fields or tightened limits | Sanitized 422 before graph/provider dispatch |
| Invalid plan/anchors, provider failure or invalid citation/draft | Sanitized 502 `offline_draft_failed`; no output repair or retry |
| Graph or overall request timeout | Sanitized 504 `request_timeout`; cancellation propagates |
| Oversized body | Sanitized 413 before dispatch, preserving allowed CORS headers |

Health/readiness behavior is unchanged. A draft-capable injected test app does
not establish an approved reachable index or live model compatibility; default
readiness remains unavailable. Existing read-source/time behavior is preserved,
including unimplemented time outcomes. Source-selection, inherited service
context and ambiguity failures from earlier live screens remain unresolved.

Verification exercises the actual HTTP middleware, service, compiled LangGraph
and OpenRouter adapter with mocked transport. Fifty-one new checks cover all
three required language varieties, exact request/history/quote preservation,
four-part mixed outcomes, missing evidence, out-of-part constraints, missing
reference context, forged owner citations, provider errors, unknown usage,
production/configuration refusal, closed input, default behavior, schema labels,
content-free logs, concurrent owners/budgets/IDs, resource lifetime, body limits
and real asyncio cancellation without retries. Synthetic assembly units and
retrieval receipts are test fixtures, not Luna/Qwen token or quality evidence.

Evidence and full check receipts are in
`artifacts/m5-offline-service-composition-v1`. All **1,588 guarded offline tests**
pass (51 new), along with Ruff lint/format (164 files), the 65-package lock and
whitespace checks. Historical payload/trace and source/cache preservation are
recorded separately; this is not a new semantic review. No credential loading, provider
metadata/inference, embedding, Qdrant, website fetch, source/index change,
subagent or deployment ran. The [completion budget plan](COMPLETION_BUDGET.md)
still defers broad paid comparisons. The last observed allowance was
$1.1424752 at 2026-10-16 17:34:06 UTC; it was not refreshed in this offline step.

The [request-scoped query/retrieval bridge](REQUEST_RETRIEVAL_BRIDGE.md) is now
implemented and mock-tested through this HTTP boundary, preserving one graph
budget, exact cache identity and filters before top-k. Default serving remains
disabled; the new scoped database path has not run live. Offline final response
projection/rendering and its contract are now implemented as an explicit option.
Next is source-bound public-hours preparation and pure time calculations. Complete remaining planner/source
fixes and subsequent draft/answer/API/deployment acceptance before enabling
public serving. No paid dispatch or automatic promotion follows from mock success.
