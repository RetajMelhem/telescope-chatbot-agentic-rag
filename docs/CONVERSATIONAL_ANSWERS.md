# Local conversational answering

The local MVP now writes answers from the original question and relevant admitted
website evidence. It replaces the earlier extractive second stage within the same
bounded LangGraph flow. There is at most one planning call and one answer call to
Luna, plus the existing Qwen query embedding batch when needed. No third agent,
judge, retrieval loop or additional call allowance was introduced.

## Behavior and boundaries

The opt-in `conversational_answers=True` setting requires the explicit local MVP
profile. Earlier and default profiles retain their extractive behavior. The new
`ConversationalDraft` contains each original part's status and prose segments with
supporting chunk IDs. Luna receives the original query, bounded interpretation-only
history, per-part targets, source policies and assembled evidence. Its versioned
prompt requires natural English, Arabic or Jordanian Arabic while preserving factual
ownership, names, numbers, uncertainty, qualifiers and explicit source restrictions.

The application validates part coverage, IDs, fixed outcomes and citation scope.
It constructs original evidence quotations from the pinned catalog and passes them
through the existing source/ownership/complete-scope validator. The presenter then
independently rechecks generated references. Technical citation IDs stay in the
structured source metadata and expandable source panel, outside the answer prose.
Original excerpts remain in source records; generated prose never replaces
the data. Complete-source provenance stays separate from sentence support selection.

Published hours retain deterministic calculation and evidence validation. The local
writer receives the validated records/outcome and phrases a short answer for the
requested day or time, using the same second stage as ordinary answers. A shared
source-proof decision is checked before writing and again at publication; the model
cannot change a missing, ambiguous or conflicting outcome. The full weekly table is
appropriate only when requested. Hours-only questions now incur a second Luna call;
the maximum remains two calls, with no extra judge or retrieval loop. Ambiguous source
pages keep validated URL choices. Missing facts and excluded private or personalized
medical requests stay explicit. Several excluded actions may share one visible
explanation while all original API parts retain their individual outcomes.

The local planner, starting with v3, answers a general introduction from a clearly matching main
directory owner without demanding a profile URL. A first name that identifies
multiple people still needs clarification; an explicit single-page restriction
remains binding. Five actual development requests were individually reviewed for
Arabic/English Rihab, ambiguous Osama and a restricted profile request. The cited
directory records retain their literal owners and exact source spans; no new
identity aliases were added. Evidence: `artifacts/direct-doctor-answer-v1/`.

Local v7 also carries full literal short-part subject quotations for hours and can
append a standard-language dialect paraphrase to the literal search query. The
original question, references and constraints remain mandatory. It does not resolve
ambiguous people/times, add facts or change source filters. A first rewrite that
replaced the original text was rejected and is retained as a failed diagnostic.

The UI shows prose as its main answer and offers expandable original source excerpts.
`answer_style=conversational` identifies the local output style. Citation identity
and exact original quotation do not prove semantic entailment of generated prose;
the application does not claim such a mechanical guarantee.

## Verification on 2026-10-18

Latest follow-up:

- **19 new / 2,144 full offline tests pass**, including hours prose, mixed questions,
  separate owners, stale/conditional/conflicting/missing proof, expired records,
  AM/PM ambiguity, unchanged computed outcomes, dated exceptions, forged/borrowed
  references and hidden inline IDs. Lint/format and locked dependencies pass.
- **16 actual requests / 19 returned parts** were individually reviewed by primary
  Codex. Three rejected protocol attempts and one earlier visitor retrieval miss
  remain recorded. The final v7 screen has **five actual requests / nine parts**
  adequate in tested scope, including two restarted real localhost HTTP requests.
  Earlier v5 checks also cover English Monday/closing, pharmacy hours, current time
  and a direct Rihab introduction. These are development cases, not a held-out
  generalization claim.
- Friday now answers directly in Jordanian Arabic, for example: “آه، المركز فاتح
  يوم الجمعة من الساعة ٢ الظهر لحدّ ١٢ بالليل.” Relevant visitor documents and
  optional ID/insurance remain qualified; booking remains separately excluded.
- All 26 citation occurrences match their original records; **five distinct chunks /
  three saved official pages / 26 exact DOM spans** verify. After the later cosmetic
  ID removal, three offline replays of saved actual native replies preserve all
  non-answer fields exactly. No new paid call was needed for that presentation edit.
- Observed usage increase during this screen window is **$0.066729350**, with
  **$0.408153510 remaining**. Thirty audited provider attempts (25 chat/five Qwen)
  report $0.058140330; two real HTTP requests lack provider payload auditing.
  Independent billing reconciliation is not claimed. Hours-only queries now use
  two Luna calls, so their generation cost/latency increases over deterministic-only
  formatting; no general performance comparison was conducted.

Evidence: ignored `artifacts/conversational-hours-v1/` through
`conversational-hours-v5/`, including failed diagnostics, individual review,
source checks, actual requests, final tests, ID-removal replays and accounting.
No source/index/cache/credential write, corpus embedding or public deployment.

Earlier conversational-stage verification:

- **2,125 guarded offline tests pass**, including ten new bilingual/Jordanian
  contract cases for prose, distinct owners, missing/excluded parts, borrowed or
  unknown citations, forged markers, omissions and duplicate parts. Two logical
  stages share one request budget; invalid output is rejected without repair.
- **Eight actual live requests / 16 parts** were individually read by primary
  Codex against their source passages. Six audited cases made ten chat and four
  embedding attempts, with no retry. Two further requests went through the
  restarted real localhost API.
- English and Jordanian visitor replies preserve relevant documents, optional
  available ID/insurance, most appointments taking 20–40 minutes and variation by
  consultation/procedure. Arabic generation from the explicitly restricted English
  cataract page preserves typical 10–20-minute duration and lens-dependent glasses
  reduction; an absent exact price stays unknown. One Arabic phrase has a minor
  fluency caution, without an observed factual alteration.
- Mixed payment/hours/booking retains the payment owner, Friday/time interpretation,
  public-schedule limits and excluded booking. The ambiguous Rihab page request keeps
  separate URL choices. A medical request exposed that the original safe refusal
  explained bookings rather than personalized advice; its final HTTP rerun now
  explains the correct general boundary and retains both excluded parts.
- All ten citation occurrences, including the final HTTP example, preserve original
  evidence and ownership. Nine distinct chunks / three original saved official
  pages / **45 exact DOM spans** were checked. This is selected-source verification,
  not another full-corpus audit or global answer-accuracy evaluation.

Evidence is under ignored `artifacts/conversational-answer-v1/`: the bounded plan,
provider/Qdrant traces, actual replies, individual semantic review, source/DOM checks,
test receipt and accounting. These are development examples and targeted repairs,
not a broad independent holdout or a guarantee that future paraphrases are correct.

The project key increased by **$0.033173155 during the screen window** and reported
**$0.500979850 remaining** afterward. Audited responses report $0.025720165; two HTTP
requests did not record provider payloads. Independent per-request billing
reconciliation is not claimed. No source/index/cache/credential change, corpus
embedding, extra judge or public deployment occurred.

Current milestone: **M5 local conversational chat is working with scoped evidence**.
Next is hands-on acceptance in the [local interface](http://127.0.0.1:8000/), then
M6 portable API Docker packaging. Broad answer/retrieval quality, source refresh,
production adoption and website integration remain separate unfinished work.
