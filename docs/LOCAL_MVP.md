# Local MVP

This entry point runs FastAPI and the existing bounded LangGraph flow with Luna
through OpenRouter, Qwen3 Embedding 8B through the pinned DeepInfra route, and
read-only dense retrieval against the existing local Qdrant collection. It uses
the approved saved Telescope website snapshot, not the current live website.

From PowerShell in `C:\CLINIC\clinic_agentic_rag`, run:

```powershell
.\run-local.ps1
```

Open [local chat](http://127.0.0.1:8000/),
[API documentation](http://127.0.0.1:8000/docs), or
[readiness](http://127.0.0.1:8000/health/ready). The launcher starts the two existing
Qdrant containers if stopped. Docker Desktop must be running. Ctrl+C stops the API;
it does not remove containers, volumes or knowledge. Restart with the same command.
The API binds to `127.0.0.1` only. Do not change it to a public bind for this MVP.

For a direct API question:

```powershell
$body = @{ query = 'When does the center open?'; language = 'en'; history = @() } |
    ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/chat `
    -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

Try English, Arabic or everyday Jordanian Arabic. Examples include visitor
preparation, published hours, doctor information and treatment descriptions.
Questions may combine public facts with an excluded private or booking request;
each part gets its own outcome. When several profiles could match a singular
page request, choose an exact URL and include it in a fresh question.

The browser sends independent questions without storing history. The API accepts
the bounded `history` contract. This MVP now writes natural answers from the original query and relevant website
evidence, with validated support references retained in source metadata. Technical
citation IDs are hidden from the answer prose. Original quotations
remain literal in expandable source details. It can faithfully translate an English
source for an Arabic reply. Missing facts remain unknown.
Published hours never establish actual attendance or appointment availability.

## Local resources and boundaries

The factory `telescope_rag.api.local:create_local_app` explicitly composes the
current v14 hours/source contracts, source-page choices and the local search
prompt. The local response schema is `local-mvp-response-v1`, with `mode=local_mvp`.
It sets `answer_style=conversational` and preserves question-owned citations,
source timestamps, literal/canonical
ownership and unresolved parts. The original default application remains disabled.
This entry point does not publish an alias or change the existing index.

Required local files already present in this workspace:

- `.env`: designated OpenRouter key; preserved, never sent to the browser.
- `.tools/qdrant-m3/read.key`: read-only Qdrant credential.
- `data/processed/m3-execution-approved-v6-v2/`: approved 107-document / 955-chunk bundle.
- `data/processed/m3-llm-semantic-token-validated-v6/metadata/`: admission and directory metadata.
- `artifacts/m5-public-hours-v1/reviewed-hours-plan.json`: reviewed hours records.
- `.tools/qwen-tokenizer/1d8ad4ca9b3dd8059ad90a75d4983776a23d44af/tokenizer.json`:
  exact hash-verified tokenizer; no download at startup.

The collection is `telescope_public_018817ac10ec05ecad92adb9`, at
`http://127.0.0.1:6333`, with 955 points and 4,096 dimensions. Startup validates the
approved bundle, prepared digest, hours digest, tokenizer bytes and collection
health/count/vector configuration. Returned Qdrant payloads must match the pinned
inventory exactly. The query cache is read-only; new query vectors are request-local.
The local factory uses the read key, never the admin key.

There are at most two Luna calls and one Qwen embedding batch per question,
one retrieval round, no retries/fallbacks, and no extra judge. Each chat stage has
a 4,096 output ceiling within the shared 8,192 output allowance. Normal chat uses
provider-reported token counts. Qwen uses the verified tokenizer. Provider timeout
is 60 seconds; the request deadline is 150 seconds. These are development settings,
not claims that every request will finish within typical observed latency.

The browser and `/docs` can spend the project's remaining OpenRouter credit when
you submit a query. Startup, static UI and health checks make no inference calls.
Default logs contain request metadata only. The explicit acceptance runner stores
public test payloads under ignored `artifacts/`; this is not default chat logging.

This MVP depends on local files excluded from Git and Docker. Copying the Git
repository alone is not a portable installation. The separate production app,
containerized API packaging, public deployment, widget, source refresh and broad
independent accuracy acceptance are outside this local delivery.


## Conversational answer stage

The local `ConversationalRagWorkflow` replaces the earlier extractive second stage.
Luna receives the original question, history as interpretation context only, the
validated per-part targets/policies, and the assembled untrusted source evidence.
It returns concise prose segments and their supporting chunk IDs in one strict
`ConversationalDraft`. No third model, judge or retrieval loop is added.

The application rejects omitted/duplicate parts, borrowed/unknown citation IDs,
forged citation markers and changed fixed outcomes without a repair call. Existing
source, ownership, exact quotation, complete-scope and time checks remain active.
Original excerpts stay in the provenance sidecar; generated text does not replace
source data. Complete-source reads retain their required provenance separately
from the sentence-specific support references.

The presenter rechecks references and keeps their IDs in the expandable source
panel and API metadata. Hours keep deterministic calculation and proof validation;
the existing second Luna stage phrases a concise answer for the requested day/time.
Hours-only questions now use two calls instead of one. Source-page ambiguities keep
validated URL choices. Excluded actions and missing facts stay explicit. Repeated
identical excluded-action explanations can share one visible paragraph while every
original part remains in the API response. Source records and distinct owners are
never deduplicated by this presentation rule.

Structural citation checks cannot prove factual entailment of arbitrary prose.
The local live examples received individual primary Codex language review; future
answers can still be wrong. See [conversational verification](CONVERSATIONAL_ANSWERS.md).
