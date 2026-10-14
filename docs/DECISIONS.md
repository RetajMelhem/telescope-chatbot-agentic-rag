# Decisions and open items

Updated: 2026-10-14. Distinguish user requirements from proposed implementation defaults.

## Confirmed with the user

| Decision | Basis |
| --- | --- |
| FastAPI backend and LangGraph orchestration | Original project request |
| GPT-6 Luna through OpenRouter | Original project request; key will be placed in local `.env` |
| Qwen3 Embedding 8B | Original project request |
| Broad public website questions | Original request and follow-up: answer any question supported by website content |
| Public doctor working hours are allowed | Follow-up: answer if published on the website; otherwise do not invent them |
| Arabic, English, and everyday Jordanian Arabic | Explicit answer to the language question |
| No patient files, record edits, or private schedule access | Original exclusion |
| Docker deployment | Original project request; implementation follows foundation |
| Codex repository instructions | User requested an agent instruction file |
| One canonical `AGENTS.md` | User requested removal of the unnecessary duplicate; `agent.md` removed |
| Living project progress/next-step file | User requested continuity for later Codex sessions |

## Proposed design defaults

| Choice | Reason and validation needed |
| --- | --- |
| Hosted Qwen embeddings through OpenRouter | Fits the selected provider and avoids an initial GPU service; account access and endpoint vectors unverified |
| Qdrant with versioned collections | Separate persistent knowledge from application containers; verify pinned release and permission configuration |
| Two Luna stages, one retrieval round | Retains decomposition/retrieval/generation while bounding latency and cost; evaluate recall and answer coverage |
| Source citations and explicit partial/unknown answers | Needed to avoid unsupported clinic facts |
| Source-backed directory and hours records | Supports complete listings and time calculations without guessing from top-k results |
| Client-provided bounded context, no server chat storage | Supports follow-ups without adding a retention/session service |
| `Asia/Amman` for clinic time | Clinic website identifies an Amman location; verify branch-specific timezone if new branches appear |
| 4096 vector dimensions | Upstream Qwen model capacity; verify the actual hosted endpoint before index creation |
| Budgets in `.env.example` | Initial limits only, not measured performance guarantees |
| 168-hour freshness ceiling | Initial operational default; review with clinic owners before release |

These choices are reviewable defaults, not user mandates or verified runtime behavior.

## Open decisions for later milestones

- Hosting destination, public API domain, HTTPS/proxy setup, and operational ownership.
- Website widget scope and how it will be added to the clinic's existing website.
- Knowledge refresh cadence and who approves content changes or conflicting hours.
- First complete source inventory, Arabic-page coverage, and whether JavaScript/PDF/OCR ingestion is needed.
- What to do if opening hours cannot be found in the public website: remain unknown, or separately approve an additional official public source. No additional source is authorized by default.
- Exact validated dependency/container versions and OpenRouter endpoint/provider settings.

None of these prevent M1's offline API/configuration work. Resolve decisions when their implementation milestone needs them.
