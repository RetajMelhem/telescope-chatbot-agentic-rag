# Planner generalization and semantic robustness

Status: 2026-10-16, development verification only. The implementation uses general mechanisms, but semantic robustness and transfer to new wording remain unproven. Default API chat is unavailable; this document does not authorize deployment or further provider dispatch.

## What is general and what is not yet established

The [anchor resolver](../src/telescope_rag/graph/anchoring.py) applies exact Unicode quotations, unique source positions, constraint ownership and unchanged query checks to any request. It has no doctor-specific, question-family, phrase-to-source or benchmark-answer routing. [Source bindings](../src/telescope_rag/graph/bindings.py) issue handles from the admitted catalog and validate literal selections. Source-policy rules are explicit admitted metadata, not facts inferred from a retrieval score. The [experimental prompt](../src/telescope_rag/prompts/planner_anchors_v4.py) adds general dependent-qualification and source-attribution instructions. No development case IDs, witness IDs, expected answers or fixed document handles enter its runtime instructions.

These properties reduce opportunities for brittle patches. They do not establish that the model understands every request correctly. Absence of keyword rules does not rule out overfitting: v4 was selected after observing errors in six exposed cases, covering only two intent families in three correlated language variants. Repeated improvement on those same questions is development evidence. There are no model weight updates here; selection and prompt tuning can still adapt to a narrow test distribution.

The 18 reserved cases cover six other authored families and have never been dispatched. They are a useful broader check, not a statistically independent sample of real users or a guarantee of unseen-data performance. Expected plans/source witnesses were authored and reviewed during fixture preparation. Their exact shape is not the sole correct answer, and valid alternative source scopes need source-based review.

## Current evidence

The frozen v4 screen ran once at `8dbf56d`: six actual Luna/OpenAI requests, all complete strict JSON and literal-valid. Root individually reviewed six actual plans/12 parts against nine relevant source-owned chunks from five saved official pages, with 72 exact original DOM references verified. This is targeted source verification, not a fresh website or corpus audit. No secondary paid judge or independent second reviewer was used.

Four cases are accepted for their targeted development planning purpose. The two Arabic mixed-purpose plans are not admitted because an independent eligibility question is repeated inside the fee-reporting part under a broader declared use. The previous Jordanian wrong-page/dependent-notice issue is corrected, but that improvement does not resolve the new purpose/context ambiguity. English keeps separate question targets and the fee notice, with broader related Patient Rights scope remaining a retrieval caution.

This is not rejection of all overlapping context. The specific concern is that a complete independently unresolved question reappears in a part whose policy allows a different kind of answer, with no separately represented focus/context distinction. The draft input exposes the full part text and intended use. The offer witness is context-only for the eligibility part but eligible under the service-description part. This reproduces the policy mechanics; no draft was generated, so an actual unsupported answer is not established.

Evidence: `artifacts/m5-context-generalization-audit-v1/root-semantic-review.json`, `source-evidence.json`, `purpose-policy-replay.json`, provider receipts in `artifacts/m5-literal-context-preparation-v2`, and the audit report. Scripts corroborate exact coverage, hashes and policy mechanics; the root's language reasoning makes the semantic decisions. The 1,201 passing mocked/offline tests establish their tested contracts and boundaries, not language accuracy.

## Trade-offs and limits

- Exact matching verifies provenance, not meaning. Repeated or altered quotations can fail safely or require clarification, reducing completion. The app does not infer which occurrence the model intended.
- Requiring the full original part in a retrieval query retains negation and qualifiers, but can add irrelevant words or contextual questions. Effects on dense recall, nDCG, ranking noise and latency remain unmeasured.
- Per-part source policy relies on the semantic correctness of the declared purpose/use. Correct source IDs and quotations cannot establish that a claim answers that purpose.
- Broad related sources may add useful context or reduce precision. Separate ownership must be preserved; neither advantage nor harm has been measured for the new queries.
- New wording, misspellings, dialect variations, changed clause order, histories, ambiguous identities and different combinations of public/unsupported/private requests still need actual language evaluation. Model schema compatibility does not prove that transfer.
- No model-driven draft acceptance, end-to-end retrieval comparison, production acceptance or calibrated real-user error rate is established by this screen.

## Next correction and experiment

The next correction should make each answer target explicit and distinguish supporting literal context from that target. Use the existing `reference_text`/history/source bindings where they can express this adequately; extend the proposal contract only if they cannot. Shared context must not implicitly become another answerable question under a broader use. Do not add a rule for particular clinic phrases, forbid every benign overlap, silently relabel model output or infer missing source facts.

Before the next candidate is selected, freeze fresh paraphrases and meaning-changing contrast pairs in English, Arabic and Jordanian Arabic. Cover shared source references, reordered/dependent qualifications, distinct owners with the same specialty, prohibitions versus actual action requests, unresolved eligibility versus published claims, and ambiguous references. Questions and expected outcomes must derive only from admitted Telescope evidence and product boundaries. Do not inject expected plans, witness IDs or reviewer text into model input.

Hold the model, source snapshot, schema/profile under comparison, reasoning policy and declared request/output limits fixed for a meaningful comparison. Review every actual plan, including alternatives and failures; report syntax, literal correctness, semantic admission, latency and usage separately. A contract change may need a separately disclosed comparison because its request schema differs. Do not claim isolated causal gains from combined changes or reclassify failures to improve a score.

After development acceptance, freeze the candidate before one separately prepared reserved-case run. Do not change the prompt between those cases, retry for a better score, or remove failed cases. If reserved outcomes inform a later correction, those cases are exposed development evidence for that correction; use a fresh evaluation set for a new generalization claim. Only then connect provisional dense retrieval and assess answer evidence coverage and source-faithful drafting. No reserved run or production adoption is implied while the current development acceptance issue remains.
