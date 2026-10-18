# Local MVP acceptance, 2026-10-18

The public-information chatbot is delivered for bounded local development use.
Start with `run-mvp.ps1` and open `http://127.0.0.1:8000/`. See the
[Docker runbook](LOCAL_MVP_DOCKER.md) and [host alternative](LOCAL_MVP.md).
This is not production acceptance or a guarantee about arbitrary future questions.

## Delivered scope

FastAPI serves the browser, typed chat endpoint, API documentation and health
checks. LangGraph uses the bounded planner/retrieval/writer flow with GPT-6 Luna
and Qwen3 Embedding 8B through OpenRouter. English, Arabic and Jordanian Arabic
are supported. The local candidate pool combines five dense hits with up to three
literal matches and two source-bound context records; this is not a claim that
the strategy is globally best.

The reviewed snapshot remains 107 documents / 955 chunks / 834 unique corpus
embeddings. Published hours are independently computed and phrased conversationally.
The separately proven website-link supplement retains original occurrences.
Answers keep technical citation IDs out of prose; excerpts, owners, timestamps and
source URLs remain in metadata/details. Lists now use separated bullets. Arabic
numeric runs retain digits/signs inside LTR isolates. The browser uses independent
questions and does not store history.

The API image runs non-root with read-only root/data and file secrets. Only its
loopback host port is published. It reuses the private Qdrant network/volume without
the admin key, ingestion, corpus embedding or alias writes. Default/production chat
remains unavailable.

## Current verification

**2,255 full guarded offline tests pass**, zero failures/errors/skips, plus Ruff
lint/format and locked dependencies. Thirty-five new cases cover the fixed Docker
target, secret precedence/missing files, safe runtime preparation and multilingual
list layout with separate citation owners, plus request-local page reuse without
crossing owner/language/type/page/source-policy boundaries. Authored tests verify contracts, not
the semantic truth of an LLM answer.

Real Docker build/startup passed using digest-pinned Python 3.11.17/bookworm and
uv 0.13.1 images. Inspection confirms packaged application HTML and absent runtime
source data/tokenizer/secrets. Actual UID 10001, read-only mounts/root, dropped
capabilities, network selection and loopback binding were checked. Missing-secret
startup exits before inference. The read key's update of a confirmed absent
collection receives HTTP 403 and cannot create data. API recreation/readiness
passed while the 955-point inventory and alias result stayed unchanged. Database
backup restoration and new-machine installation were not tested.

Five initial requests and two targeted doctor follow-ups went through the container
HTTP API. Primary Codex individually read all **13 returned parts in seven requests**
against their original cited sources. The two earlier doctor defects remain recorded;
the final applicable result for each scenario is:

| Case | Observed behavior | Request time |
| --- | --- | --- |
| Arabic eye team and qualifications | Seven owner-bound entries with source-backed qualifications; no invented negative specialty | 51.61 s |
| English contact and Facebook | Correct phone/WhatsApp/email and exact website-published Facebook target | 18.34 s |
| Jordanian Friday hours plus booking | Direct 14:00–midnight answer; booking separately excluded | 11.11 s |
| Arabic cheek “surgery” premise | Documented filler service and explicit nonsurgical correction | 12.61 s |
| English exact price plus patient record | Exact price unconfirmed; private record excluded without access | 10.20 s |

The earlier doctor output inferred an absent specialty from a positive anesthesia
role. The v11 prompt removes that inference. Its follow-up then exposed a second
gap: useful main-card qualifications retrieved for the role part were not offered
to the qualifications part. The local graph now reuses already requested/retrieved
page candidates only when the receiving search part already selected that same
page, its exact scope permits the chunk, and source policy admits the intended use.
Normal global assembly caps still apply. Original candidate rank order, separate owner
records and default profiles are preserved; no new source/network/model round is
added. The last actual doctor reply includes previously missed qualification facts.
The full original cohort was not rerun after this targeted change, so no uniform
final-profile cohort or causal A/B claim is made.

The doctor reply can summarize qualifications instead of enumerating every
credential; related role/qualification parts can repeat names. It is not a complete
credential dossier. Source chunks are unchanged and available in supporting
excerpts. Candidate status may contain a supported partial answer with explicit
uncertainty in prose; it does not certify an exact price or coverage.

All **48 citation occurrences** match **20 chunks across 11 saved official
pages**; **151 DOM spans** verify exactly. The outgoing link matches its separately
sealed source record. Scripts checked coverage/literal correspondence rather than
making semantic judgments. No new full-corpus or removed-content audit is claimed.
Earlier development evidence/failures remain in ignored artifacts and Git history.

The first postflight compared complete alias envelopes, including Qdrant's changing
timing field. A separate diagnostic correction compares the actual alias result
and confirms it unchanged. No paid request was repeated for this check error.

## Budget and remaining limits

Observed key balance changed from $0.213661715 to $0.175885100 during the seven-query
window, a $0.037776615 increase. This is aggregate metadata, not independent
per-request billing reconciliation; concurrent user traffic or delayed accounting
can affect it. No corpus embedding or index write occurred. Normal allowances stay
at most two Luna calls, one Qwen query batch, one retrieval round and no automatic
retries/fallbacks. No typical-latency guarantee is made: the broad doctor request
was substantially slower than the other four.

Browser automation is disabled; no visual acceptance is claimed. The actual
JavaScript renderer has offline DOM/text checks. Longer compound answers can repeat
names, and retrieval/interpretation can miss evidence. Published hours never
establish live attendance/availability. Personal advice, private records and booking
actions remain excluded.

Ignored `artifacts/local-mvp-delivery-v1/` retains build/start/restart logs,
pre/postflight, actual replies, source proof, individual review, accounting,
image/runtime checks and final tests. Real keys and collected data are excluded
from Git and the image. Cloning Git alone is not a new installation.

Next: ordinary hands-on local use and focused bug reports. No additional audit is
required before using this MVP. Public hosting, HTTPS, website integration, source
refresh, backup/restore and broad independent quality acceptance are future work;
full M6/M7 are not marked complete.
