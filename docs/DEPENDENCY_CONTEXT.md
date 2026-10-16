# Offline dependency-context candidate

The opt-in `dependency_context`/v10 candidate asks the planner to interpret each
dependent target with its exact subject or ordered group **and its governing
requested source context**. It replaces v9's referent append on the unchanged v8
base. See the [prompt](../src/telescope_rag/prompts/planner_dependencies_v10.py)
and prior [consumer diagnosis](REFERENT_DIAGNOSIS.md).

A source qualification continues into a dependent follow-up unless the user
explicitly changes it. A purpose such as `profile_detail` describes the requested
relationship; it does not authorize switching to a standalone profile. A page
reference alone is insufficient for a question about a particular service or
person within that page. Ambiguity can concern two entries of the same person.
Clear public siblings remain answerable while the unresolved part requires
clarification without retrieval. Plural groups, negations, order, time
constraints and literal ownership must remain intact.

The existing `original_text`, `reference_text`, selected history and
`retrieval_query` fields carry context. Their limits and literal validators stay
unchanged. The application neither chooses antecedents nor repairs queries,
sources, purposes or states. V8 purpose definitions, language metadata,
authority/source restrictions and drafting instructions remain unchanged. V10
has its own draft version tag but no new draft instruction. No judge, model
stage, retry, token guard or retrieval loop was added. Graph defaults, generic
live CLI allowlists and the unavailable public chat API remain unchanged.

Before prompt edits, 48 prior cases and 12 new English/Arabic/Jordanian Arabic
contrasts were frozen with primary language-authored acceptance criteria. New
contrasts cover inherited main-source training, an explicit profile-source
override, a negated neighboring doctor and explicitly unselected same-person
entry choice. That last family was clarified before any prompt edit or response:
the initial phrasing could naturally refer to the nearest entry. Both freezes
and the author correction remain preserved; the second freeze is authoritative.
These are exposed development cases, not a new holdout or generalization proof.
The reserved cohort remains unopened.

Preparation produced **60 v9/v10 pairs / 120 unexecuted packets**. Both arms
have identical schemas, source manifests, provider/model, reasoning settings,
output caps and non-message parameters. Only the system dependency instruction
and user `prompt_version` differ. Criteria, witness IDs and expected outcomes
are absent from model payloads. No paid runner was added or executed here.
All 60 v9 controls equal their pre-edit payloads. Another 240 historical payloads
were reproduced exactly; all 96 previous actual plans replay with identical
mechanical traces. Earlier semantic decisions are preserved, not regraded.

Primary language reasoning reread four complete saved Telescope witness chunks:
two English main-directory cards publish distinct roles/training; two standalone
profile cards publish names only. Eighteen source/context DOM references match
the saved original pages. Literal owner IDs differ across page occurrences and
stay separate; a same-person reference never authorizes merging source owners.
No clinic facts came from external sources or model knowledge. The 48 older
cases retain their sealed source reviews; this is not a new corpus-wide audit.

Verification passes **1,486 guarded offline tests**, including 24 new checks.
New checks exercise compiled graph paths and mocked OpenRouter wires, source
inheritance versus override, owner exclusion, ordered plural context, name-only
unknown outcomes, mixed public/clarification parts, missing literal reference
and incompatible source-language refusal. They establish representability and
transport/consumer boundaries, not the model's choice of interpretation.
Ruff lint/format, lock, local links and whitespace pass. All 122 source inputs,
955 chunks, 924 cached vectors and dotenv bytes remain unchanged. Historical
code/document bindings retain exact preserved copies.

V10 remains unadopted. Sparse-profile limitations are still absent from the
planner's per-document manifest entries; that observed gap is not a proven cause
and was not changed alongside this prompt experiment. Structurally valid but
irrelevant quotations remain possible. Actual Luna semantics, retrieval/ranking
quality, draft behavior and serving readiness are unverified. Neither mocked
success nor general wording establishes semantic robustness.

Next is a separately authorized, budget-checked bounded v9/v10 comparison using
the frozen packets, followed by individual source-grounded semantic review of
every response, retaining regressions and unknowns. Execution must authenticate
final code/source/payload bindings and retain once-only receipts; earlier paid
runners are bound to their own exact code. Actual retrieval/draft acceptance and
reserved evaluation follow semantic planning acceptance. No provider, embedding,
Qdrant, Telescope fetch, deployment or subagent ran; new project API spend is $0.
The last prior allowance observation was $1.535864855, still unreconciled and
not refreshed in this offline step.

Local evidence: `artifacts/m5-dependency-context-preparation-v1/REPORT.md`,
`frozen-contrasts-v2.json`, `prepared-packets.json`, `historical-replay.json`,
`source-evidence.json`, verification/test receipts and `evidence-seal.json`.
