# FastAPI contract

Local MVP replies include `answer_style=conversational`: `answer` contains generated
plain-text prose without technical citation IDs; `citations[].quote` retains original
evidence. Each original part, owner and unresolved outcome remains inspectable.
See [conversational verification](CONVERSATIONAL_ANSWERS.md).

Current local MVP: [runbook](LOCAL_MVP.md) and [acceptance evidence](LOCAL_MVP_ACCEPTANCE.md).
The explicit loopback entry point now serves live development queries. The default
application and production acceptance remain separate; earlier checkpoints below
describe their original scope.

## Current local MVP contract

Both local launchers serve `POST /api/v1/chat` with the request below. The Docker
factory is `telescope_rag.api.container:create_container_app`; the host alternative
is `telescope_rag.api.local:create_local_app`. The current closed response is
[`LocalChatResponse`](../src/telescope_rag/api/local.py), with:

| Field | Current local meaning |
| --- | --- |
| `schema_version` / `mode` | `local-mvp-response-v1` / `local_mvp` |
| `answer_style` / `answer_format` | `conversational` / `plain_text` |
| `status` | `draft_ready`, `not_found`, `out_of_scope` or `clarification_required` |
| `answer` | Natural response, readable bullet/paragraph layout; citation IDs stay in metadata |
| `language` | `en`, `ar` or `ar-JO` |
| `questions` | Every original part, with candidate/unknown/excluded/clarification outcome, citation IDs and nullable hours information |
| `citations` / `knowledge` | Exact source excerpts, ownership, URLs, source times and pinned snapshot/configuration metadata |
| `unresolved_questions` | Original parts still unsupported, excluded or ambiguous |
| `website_links` / `website_links_digest` | Separately proven outgoing website links with question/source ownership; no social-site fetch |

`draft_ready` and a part's `candidate` status are development outcomes, not factual
certification. They can include explicit partial uncertainty in prose. Structural
checks do not prove entailment. Open [the local OpenAPI page](http://127.0.0.1:8000/docs)
for the complete current schema. The browser sends empty history for independent
questions; API callers may supply the bounded interpretation-only history below.

`GET /` serves the UI. Local readiness checks the pinned candidate collection and
reviewed resources; it does not require a published active alias or make an
inference call. Invalid input returns sanitized 422; service/provider/projection
errors remain sanitized and bounded. The API does not expose ingestion or writes.

## Default factory and earlier injected profiles

The separately injected [offline hours response](HOURS_GRAPH.md) uses
`offline-hours-response-v1`, the same chat request and a nullable per-question
`hours` summary. It requires `HoursChatService` and explicit nonproduction
`offline_response_format="hours"`; old draft/rendered modes cannot silently drop
the hours receipt. Default serving and the production contract remain unadopted.
Semantic/model compatibility flags stay false.

The earlier injected draft/rendered/hours profiles retain their own contracts and
unverified flags. A production accepted-answer envelope remains planned; the
explicit local response above is implemented and distinct from it.

The original default factory's chat route remains a placeholder: valid input
receives `503` / `chat_not_available`; rejected input receives sanitized `422`.
That default does not call a provider or search knowledge. This does not describe
the explicit local factories above.

An explicitly injected, nonproduction [offline draft composition](OFFLINE_SERVICE.md) now connects this transport to the existing graph for contract checks. The default route above is unchanged. Trusted construction can supply `OfflineChatService` to `create_app`; production or mismatched settings are rejected. Its 200 response is the graph's `WorkflowResult` with immutable offline/unverified flags, exact per-question outcomes and quoted provenance, not the planned final answer envelope below. Invalid graph/provider/citation results return sanitized 502; timeouts return 504. This path does not select a default model client, approve sources or enable public serving. Caller-owned provider/retriever lifetime is explicit. No live compatibility or semantic acceptance is established by its mocked tests.

Trusted construction can additionally select `offline_response_format="rendered"` for the [offline response contract](OFFLINE_RESPONSE.md). Its closed `OfflineChatResponse` contains plain text, every original question/outcome and question-owned exact source citations, keeping mandatory offline/unverified flags. It never emits `answered`; unknown/excluded/ambiguous parts remain explicit. The existing injected draft wire remains the default. No client field or environment setting enables either mode, and the planned public contract below is not adopted. Invalid projection returns sanitized `502 / offline_response_failed` without another model call.

## Public routes

| Route | Purpose |
| --- | --- |
| `POST /api/v1/chat` | Answer one visitor request using approved public website evidence. |
| `GET /health/live` | Process liveness; no paid provider call. |
| `GET /health/ready` | Knowledge readiness for the selected factory: pinned candidate locally, active approved snapshot in the future production design. No paid provider call. |

Ingestion is a separate CLI/job, not a public route. There are no patient, calendar, booking, file-upload, form-submission, or arbitrary web-fetch endpoints.

## Chat request

```json
{
  "query": "Are you open Friday at 7?",
  "language": "auto",
  "history": []
}
```

| Field | Contract |
| --- | --- |
| `query` | Required nonblank string, at most 4,000 characters. Preserve the original question. |
| `language` | `auto`, `ar`, or `en`; default `auto`. Explicit user preference wins. |
| `history` | Zero to six messages, at most 8,000 characters in total, each with `role` (`user` or `assistant`) and plain-text `content`. |

Reject unknown fields, invalid roles, oversized input, and unsupported media. Clients cannot supply system prompts, tools, model IDs, provider keys, collection names, or source allowlists.

M1 enforces a 131,072-byte actual/declarative body limit, configurable downward or upward through trusted settings. Text/history bounds cannot exceed the documented contract and may be tightened by configuration. Request IDs are generated by the application and returned in JSON and `X-Request-ID`; client-supplied IDs are not reused.

History is untrusted conversational context. It may resolve "his" or "that service," but prior assistant answers and client-provided URLs cannot establish clinic facts. The MVP stores no conversations on the server and needs no conversation ID.

## Planned accepted public chat response

This example is illustrative and makes no claim about actual clinic hours:

```json
{
  "request_id": "application-generated-id",
  "status": "clarification_required",
  "answer": "Do you mean 7 AM or 7 PM on Friday?",
  "language": "en",
  "questions": [
    {
      "id": "q1",
      "question": "Are the clinic's posted hours open at 7 on Friday?",
      "status": "clarification_required",
      "citation_ids": [],
      "reason": "ambiguous_time"
    }
  ],
  "citations": [],
  "unresolved_questions": ["Please specify AM or PM."],
  "knowledge": null
}
```

| Field | Contract |
| --- | --- |
| `request_id` | Application-issued trace ID containing no personal identity. |
| `status` | `answered`, `partial`, `clarification_required`, `not_found`, or `out_of_scope`. |
| `answer` | Visitor-facing text; references resolve through validated citation IDs. |
| `language` | `ar` or `en`; Jordanian Arabic is rendered as Arabic. |
| `questions` | Every accepted request part, with ID, text, individual status, citation IDs, and a stable reason code when unresolved. |
| `citations` | Validated items with `id`, approved `url`, `title`, `section`, `fetched_at`, and `snapshot_id`. URLs come from stored evidence, never model invention. |
| `unresolved_questions` | Missing, ambiguous, conflicting, stale, excluded, or incompletely evaluated request parts. |
| `knowledge` | When used: `{ "snapshot_id": "...", "fetched_at": "..." }`; otherwise `null`. `fetched_at` is the oldest fetch time among cited facts, or the snapshot's oldest fetch time when no facts are cited. |

All timestamps are ISO 8601 UTC. Source-specific timestamps remain attached to individual citations. User-facing time calculations use `Asia/Amman`.

## Outcomes

- `answered`: all requested public parts are supported and there are no unresolved or excluded parts.
- `partial`: at least one part is supported and at least one is unresolved or excluded; the answer states those limits.
- `clarification_required`: a material ambiguity prevents a useful supported answer and no part can yet be answered.
- `not_found`: no requested part has adequate public evidence; this does not claim the entire website contains no answer.
- `out_of_scope`: all requested parts concern excluded behavior or non-clinic subjects.

If multiple unresolved reasons coexist without an answered part, prefer clarification when it can materially unlock an in-scope question; otherwise use `not_found` if any in-scope part exists, or `out_of_scope` if all parts are excluded. Keep every part's individual outcome.

## HTTP errors and readiness

Use `200` for handled product outcomes, including uncertainty and scope refusals. Use `422` for schema validation errors, `413` for body-size limits, `429` for rate limits, `503` for unavailable/missing/incompatible knowledge or provider service, `504` for the overall deadline, and `502` for invalid upstream protocol or schema output that cannot produce a safe response.

Error responses contain an application-issued `request_id`, a stable `error.code`, and a safe `error.message`. Do not expose stack traces, keys, prompts, provider payloads, or database details.

This envelope applies to application/API errors. Standard CORS preflight responses are transport responses: an unsupported origin/method/header returns `400` with plain text, no allowed-origin header, and an issued `X-Request-ID`. Successful preflight is also handled by CORS middleware. Neither path performs inference. Method rejection on an API route returns the JSON envelope and preserves its `Allow` header.

Liveness returns `200` while the process is operational. Readiness returns `200` only with validated configuration and a readable compatible approved snapshot; otherwise `503`. Readiness does not prove a provider can complete a paid request or that the knowledge corpus has every answer.

M1's readiness probe requires configured model credentials and a reachable, approved, identified snapshot with the selected embedding model/dimensions. The probe is bounded to two seconds by default. The production default adapter is unavailable until live knowledge is implemented. A `200` readiness response exists only in tests with an injected compatible fake snapshot at this stage. Liveness does not inspect the knowledge store.

The implemented health JSON is `{ "request_id": "...", "status": "live" }` or `{ "request_id": "...", "status": "ready" }`. Readiness failures use the error envelope with stable `configuration_incomplete`, `knowledge_unavailable`, `knowledge_not_ready`, or `knowledge_incompatible` codes. The 30-second overall request deadline is enforced by request middleware; expiration returns `504` / `request_timeout` before a response starts.

Unexpected pre-response exceptions return a sanitized `500` / `internal_error`. Default application logs include only an issued request ID, matched route template, status, duration, level, and timestamp. They exclude raw paths/query strings, headers, bodies, settings, and exception details. Run Uvicorn with `--no-access-log` to keep its separate access log from recording user-controlled URLs. Diagnostic `/docs` and `/openapi.json` routes are available in development and disabled in production.

Early body-limit errors and middleware-generated timeout/internal-error responses retain CORS headers for configured allowed origins, so a clinic browser client can read their error envelope and request ID. Unapproved origins receive no allowed-origin header.

Async adapter cleanup is bounded by `SHUTDOWN_TIMEOUT_SECONDS` (five seconds by default), independently of HTTP request deadlines. Cleanup failure/timeout emits only a fixed warning event, without exception details or credentials. Like request cancellation, this relies on cooperative async I/O; future provider adapters must preserve cancellation behavior. `OPENROUTER_BASE_URL` is validated as the approved `https://openrouter.ai/api/v1` endpoint, with an optional trailing slash.

## Website integration

The future website widget calls this API over HTTPS. It must never receive the OpenRouter or Qdrant key. Use an explicit CORS allowlist for the clinic's origins, bounded body sizes, and backend/proxy rate limits. CORS is not authentication and does not prevent direct API use; budget and abuse controls remain necessary.

Do not accept patient documents or display prompts inviting visitors to submit medical records. Before external calls, conservative local checks should reject obvious record payloads and identifiers. Arbitrary free text cannot be guaranteed free of sensitive data; do not claim otherwise. Default logs record timings, outcomes, and request IDs rather than message text.

Streaming is deferred until the structured response/citation validation path is stable. The first version returns a complete validated JSON result.
