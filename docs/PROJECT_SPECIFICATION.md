# Project specification

Status: requirements established on 2026-10-14, reviewed for the current local MVP
on 2026-10-18. The local Docker chatbot is implemented and has scoped live/offline
verification. This specification records requirements; it does not certify every
answer or production readiness. See [acceptance](LOCAL_MVP_ACCEPTANCE.md).

## Purpose

Help visitors ask natural-language questions about information published on `https://telescopecenter.com/`, in English, Arabic, or everyday Jordanian Arabic. Return concise, source-backed answers, clarification questions, or explicit statements that the requested information was not found.

## Confirmed requirements

| ID | Requirement |
| --- | --- |
| R1 | Use FastAPI for the backend HTTP API. |
| R2 | Use LangGraph for query planning and retrieval/answer orchestration. |
| R3 | Use GPT-6 Luna through OpenRouter for planning and answer generation. |
| R4 | Use Qwen3 Embedding 8B for query and document embeddings. |
| R5 | Support Arabic, English, and everyday Jordanian Arabic. |
| R6 | Answer facts supported by public website content, including doctor profiles, specialties, treatment techniques, and opening hours. |
| R7 | Answer public doctor working hours only when present on the website. |
| R8 | Do not access patient files, edit records, access private schedules, check appointment availability, or make bookings. |
| R9 | Deliver a Docker-based deployment when the application is implemented. |
| R10 | Prepare folder architecture, pipeline/specification Markdown, and Codex instructions first. |

## Answerable subject matter

Doctors and their published qualifications, specialties, and explicitly associated treatments; clinic services and techniques; equipment; clinic opening times and public doctor working hours; location and contact channels; FAQs; published insurance and administrative information; facilities and other clinic information supported by approved public pages.

The source boundary is broad public website information, not a fixed list of keyword intents. New website subjects can become answerable through reviewed ingestion without adding topic-specific routing rules.

Do not infer that every doctor offers a treatment because the clinic offers it. Do not interpret an insurer logo as evidence that a specific patient's procedure is covered. List all doctors only from a complete, current directory snapshot; a top-k result cannot prove an exhaustive list.

## Excluded behavior

No patient record or private calendar integrations, record uploads, identity lookup, patient-specific medical reports, writes, bookings, cancellations, form submissions, payments, or checks of available slots. Public business information does not authorize access to private systems.

General treatment explanations may summarize the website. The chatbot does not determine personal eligibility, diagnose symptoms, prescribe medication, or guarantee clinical outcomes. If a personal question cannot be answered from public clinic information, explain that limit and point to a verified clinic contact page where useful.

## Representative behavior

| Question | Required behavior |
| --- | --- |
| Who are your doctors? | Return the approved public directory with citations, or state the limits of the available listing. |
| What is Dr. X's specialty? | Use that doctor's own profile or an explicit attributed statement; clarify an ambiguous identity. |
| What techniques do you use for vision correction? | Summarize published techniques with citations; preserve stated limitations. |
| Are you still open Friday at 7 PM? | Use evidenced Friday hours and a deterministic time comparison; say unknown if hours are absent. |
| Is Dr. X working on Friday? | Answer only supported public working hours; do not claim actual attendance or appointment availability. |
| مين الدكاترة؟ وشو دوامكم الجمعة؟ | Address each part in Arabic, keeping unsupported parts explicit. |
| What is my test result? | Decline access to patient records and provide a supported contact route. |
| What is Dr. X's specialty, and book me a slot? | Answer the specialty if supported and state that booking is outside scope. |

`Dr. X` and time examples are illustrative; they are not clinic facts.

## Conversation and response behavior

Respond in the user's language unless they request otherwise. Keep names and technical terms faithful to source content. Accept bounded previous turns for follow-up questions such as "What about his specialty?"; ambiguous references require clarification. Previous messages can help identify the question, but cannot supply clinic facts.

The current local wire is `local-mvp-response-v1`: top-level outcomes are
`draft_ready`, `not_found`, `out_of_scope` and `clarification_required`. Per-part
candidate/unknown/excluded/clarification outcomes, citations, unresolved questions
and source timestamps remain visible in metadata. `draft_ready` is a generated
development answer, not semantic certification. Citation IDs stay out of visible
prose; original excerpts remain in source details. See [the API contract](API_CONTRACT.md).

The future production envelope proposes `answered`, `partial`,
`clarification_required`, `not_found` and `out_of_scope`; it is not the current local
schema. A future `answered` result would mean all requested public parts have
support, not that the whole website has been searched.

## Acceptance criteria

- Every factual clinic claim has supporting evidence from the active approved website snapshot.
- Every subquestion is accounted for, including unsupported or excluded parts.
- Unknown opening hours, absent doctor specialties, ambiguous names, and conflicting sources produce honest uncertainty or clarification.
- Public doctor working hours are answerable; private availability and record requests stay outside scope.
- Arabic, English, and Jordanian Arabic evaluation cases pass on the same evidence.
- Provider/schema failures terminate within budgets and do not create invented fallback answers.
- Docker deployment starts healthy, preserves the knowledge index across restarts, excludes secrets from images, and separates serving from ingestion.

Concrete evaluation cases and release gates are in [EVALUATION.md](EVALUATION.md).
Local container checks and scoped answer reviews are recorded in
[LOCAL_MVP_ACCEPTANCE.md](LOCAL_MVP_ACCEPTANCE.md). Broad independent accuracy,
public hosting, backup restoration and website integration remain unverified.
