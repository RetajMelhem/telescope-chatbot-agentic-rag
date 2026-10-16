# Bounded v9/v10 planning comparison

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

Evidence is recorded under `artifacts/m5-dependency-comparison-v1` and budget
observations under `artifacts/m5-dependency-budget-v1`. Execution results and
semantic acceptance are pending at this runner checkpoint. Earlier paid runners
retain their original exact-code bindings and must not be reused for this run.
