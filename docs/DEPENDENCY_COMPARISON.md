# Bounded v9/v10 planning comparison

Executed on 2026-10-16 at `f805ff9`: **120 one-attempt HTTP-200 Luna/OpenAI
planning requests**, exact runtime model and unique generation IDs, no retries.
All strict schemas pass; literal validity is 51/60 v9 versus 54/60 v10. Primary
language reasoning individually reviewed **120 plans / 182 parts** against
34 complete saved Telescope chunks and 201 exact DOM references. A second
primary reread covers 40 high-risk plans/76 parts; there was no independent
second reviewer or external judge.

Conservative admission is **45/60 v9 versus 47/60 v10**: 40 both admitted,
seven gains, five regressions and eight shared failures. Gains include English
pore-refinement context and inherited Arabic/dialect main-source training.
Regressions include unrelated/phone-only source narrowing, missing HydraFacial
context, an informal page-alias clarification and cross-target constraints.
Two page-alias cases retain evaluation ambiguity; noncanonical purpose/style
labels are annotated, not silently treated as exact-label failures. These are
exposed-development planning results, not retrieval or answer metrics.
**V10 remains unadopted; reserved evaluation and serving remain closed.**

All 1,507 guarded offline tests passed before dispatch (21 new runner checks).
Ruff lint/format, lock, links, whitespace and scoped Git checks pass. All
79 executed source/script files, 122 source files/955 chunks, 924 cached vectors
and dotenv bytes remain unchanged. Complete original plans and mechanical
replay, individual judgments, high-risk reread and source packets are under
`artifacts/m5-dependency-comparison-v1/REPORT.md` and its sealed evidence.

The user authorized the next step after offline
[dependency-context preparation](DEPENDENCY_CONTEXT.md). The
[dedicated runner](../scripts/run_dependency_comparison.py) authenticates the
34-file preparation seal, all 78 prepared code files, the 122 source inputs,
the complete frozen 60-case inventory and every exact paired wire before the
first request. It admits no additional cases or changed payloads.

The experiment sends at most 120 planning requests, once per packet in the
frozen alternating order: control `referent_context`/v9 and treatment
`dependency_context`/v10. Both use the same strict anchored schema, admitted
source manifest, model/provider settings and 4,096-output allowance. Reasoning
settings remain omitted; normal chat uses reported usage. No local input token
estimate, additional guard, retry, fallback, retrieval, answer generation,
embedding, Qdrant operation, reserved case or default adoption is included.

`--execute` requires the exact prepared plan and committed clean code; an
exclusive start marker prevents replay before credentials load. Fatal provider
errors stop the run. A timeout is retained as unknown and never retried.
Credential loading uses the designated project dotenv key, without displaying
or changing it. Local results retain request hashes, issued handles, original
proposals, literal-validation errors and provider usage/generation receipts.

Semantic review is separate from dispatch and deterministic validation.
Primary language reasoning must read every returned proposal and each requested
part against saved official Telescope evidence, recording explicit individual
decisions and uncertainty. Scripts may bind and count these records but cannot
grade meaning. Partial/truncated or absent outputs stay unassessable. Report
both frozen-criterion findings and additional failures, preserving regressions.
These exposed development comparisons do not prove retrieval or answer quality,
generalization, clinical truth or serving readiness.

Before execution, a read-only project-key observation reported $1.515430345
remaining of $2 at 2026-10-16 16:29:22 UTC. That is a dated observation, not a
guaranteed final balance or invoice. Record current model prices, usage and
post-run observations separately; do not resend inference to reconcile logs.

Actual reported usage is 1,670,110 input / 103,153 output tokens, including
75,747 reasoning tokens as an output subset. V10 adds exactly 102 input tokens
per request. Observed median/p95 planning seconds are 9.9295/28.782 versus
7.539/16.297; no causal latency claim. Standard uncached usage estimate is
$0.2185875, not an invoice. The final key observation at 16:58:08 UTC reports
$0.810432255 used / **$1.189567745 remaining** of $2. Its aggregate increase
exceeds the estimate; whole-run billing remains unreconciled. Seven metadata
GETs include one successful generation-ID/native-usage/cost match ($0.00183505)
and two unavailable 404 samples; no inference or metadata sample was retried.
No model alias, credential, key limit or budget guard was changed.

The next step is one **offline contract clarification distinguishing target-local
constraint_quotes from inherited reference context**, using existing fields.
The active base instructions do not explicitly state the locality enforced by
the anchor validator. Repeated actual out-of-span constraint errors confirm the
representation problem, not its hidden causal reasoning. Preserve original
coverage, qualifiers, source restrictions and validators; no app-side repair.
Source-selection/ambiguity failures remain unresolved and must not be claimed
fixed by that clarification. No further paid run follows automatically.

Evidence is under `artifacts/m5-dependency-comparison-v1` and budget observations
under `artifacts/m5-dependency-budget-v1`. Earlier runners retain their exact-code
bindings. No retrieval, draft, embedding, Qdrant, source fetch, reserved or
deployment operation ran. Source and serving readiness remain unverified.
