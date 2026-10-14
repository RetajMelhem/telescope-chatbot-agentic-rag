# Sources and verification limits

Inspected on 2026-10-14 for foundation design. Public browsing is distinct from authenticated provider inference and from a complete ingestion run.

## Clinic sources

| Source | Observation used in the specification |
| --- | --- |
| [Clinic homepage](https://telescopecenter.com/) | Public doctors, services, facilities, informational navigation, English/Arabic links; also placeholder news copy that should not enter clinic knowledge. |
| [Doctors directory](https://telescopecenter.com/doctors/) | Public directory is a seed for source-backed doctor information and coverage review. |
| [Contact page](https://telescopecenter.com/contact-us/) | Published contact/location information; identifies Amman, Jordan. |
| [FAQs](https://telescopecenter.com/faqs/) | Public FAQ content is a discovery seed. |

The inspected homepage, contact page, and FAQs did not establish Friday opening hours in the accessible extracted text. This was a limited check. It does not prove those hours are absent from all website pages, embedded assets, or rendered content. No real hours have been added to the scaffold.

Some fetches timed out or required the website's `www` entry point. An ingestion implementation must record such failures instead of treating them as missing facts. No complete crawl, content snapshot, embeddings, or knowledge index was produced.

## Technology references

| Primary source | Use and limits |
| --- | --- |
| [LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) | `StateGraph`, structured-output planning, conditional workflows, and the distinction between workflows and dynamic agents. |
| [GPT-6 Luna on OpenRouter](https://openrouter.ai/openai/gpt-6-luna?view=api) | Catalog model identifier `openai/gpt-6-luna`; catalog describes structured output/tool support. Account and selected endpoint behavior still need verification. |
| [Qwen3 Embedding 8B on OpenRouter](https://openrouter.ai/qwen/qwen3-embedding-8b) | Catalog identifier `qwen/qwen3-embedding-8b`; account/provider compatibility untested. |
| [Qwen model card](https://huggingface.co/Qwen/Qwen3-Embedding-8B) | Upstream multilingual embedding model and dimensions up to 4096; hosted endpoint conventions must be checked independently. |
| [OpenRouter RAG guide](https://openrouter.ai/docs/cookbook/evaluate-and-optimize/rag) | Pre-index document vectors, embed queries, retrieve evidence, and generate an answer. Reranking is optional and deferred. |
| [Qdrant collections](https://qdrant.tech/documentation/manage-data/collections/) | Collection parameters and aliases for versioned knowledge publication. |
| [FastAPI Docker guide](https://fastapi.tiangolo.com/deployment/docker/) | Build an application image from an official Python base and run the API in a container. |
| [Docker environment settings](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/) | Explicit container environment injection and runtime secret handling. |
| [Codex AGENTS.md guidance](https://learn.chatgpt.com/docs/agent-configuration/agents-md) | `AGENTS.md` is the standard repository instruction file; `agent.md` would need a configured fallback. |

Do not treat model catalogs as proof of the user's account access, live schemas, returned dimensions, pricing guarantees, latency, grounding accuracy, or production readiness. No authenticated model/embedding requests or runtime checks were made.

All project-specific budgets, folder organization, response schemas, and release criteria are design choices or user requirements, not claims that the cited tools implement this project automatically.

## M1 implementation references

Consulted on 2026-10-14: [FastAPI settings](https://fastapi.tiangolo.com/advanced/settings/), [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [FastAPI error handling](https://fastapi.tiangolo.com/tutorial/handling-errors/), [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/), and [uv projects](https://docs.astral.sh/uv/guides/projects/). These informed the factory, validated environment settings, safe handlers, and locked environment.

The installed Starlette test client requested HTTPX2 rather than deprecated HTTPX; the [HTTPX2 publisher page](https://pypi.org/project/httpx2/) was checked, and the compatible client is pinned in `uv.lock`. M1 verification is local/offline and does not change the provider-access limitations above.

## Chunking revision evidence

Re-inspected the [doctor directory](https://telescopecenter.com/doctors/) on 2026-10-14: distinct named profiles and team headings support preserving entity/section boundaries. Website observations establish input structure, not measured retrieval performance.

[LangChain's heading-based splitting guide](https://docs.langchain.com/oss/python/integrations/splitters/markdown_header_metadata_splitter) describes preserving common heading context and constraining size within those groups. The guide concerns Markdown; applying the structural principle to parsed HTML cards/FAQs/tables is this project's design choice, and a generic heading splitter is not a complete HTML extraction solution.

[Qu et al., NAACL 2025](https://aclanthology.org/2025.findings-naacl.114/) reports inconsistent benefits from costlier semantic chunking in the study's tested retrieval/generation tasks. It does not establish a winning chunker for this clinic. The project therefore chooses a deterministic structure-aware default, retains token overflow limits, and requires source-grounded evaluation before claiming it is best.

No complete cleaner/chunker, corpus comparison, or embedding call was executed for this revision. The policy/settings were updated in preparation for M3; M2 was subsequently implemented offline as recorded below.

## M1 completion audit

The current implementation, installed middleware behavior, and offline tests were rechecked on 2026-10-14. [OpenRouter's quickstart](https://openrouter.ai/docs/quickstart) confirms the HTTPS `/api/v1` base used by the tightened configuration check. Audit findings and fixes concern the API shell, not live model compatibility. Results and the concrete M2 definition of done are recorded in the project status and implementation plan.

## M2 implementation references

Consulted on 2026-10-14: [OpenRouter chat completion API](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion), [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [embedding requests](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request), and [HTTPX2 transports](https://pydantic.dev/docs/httpx2/advanced/transports/). These establish documented request/response fields, schema parameter support/routing controls, and explicit/mock transport behavior. Installed HTTPX2 signatures were also inspected.

The adapter's local validation, reservation semantics, retry allowlist, exact model-ID policy, and refusal to guess token counts or Qwen instructions are project design choices. These sources do not establish the selected endpoint's actual behavior or account access. All M2 protocol execution used synthetic HTTP fixtures; live counting/format/schema/dimension compatibility remains unverified.

## M3 implementation and source review

Consulted on 2026-10-14: [Beautiful Soup documentation](https://www.crummy.com/software/BeautifulSoup/bs4/doc/), [Robots Exclusion Protocol RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html), [Qdrant collection creation](https://api.qdrant.tech/api-reference/collections/create-collection), and [Qdrant point upserts](https://api.qdrant.tech/api-reference/points/upsert-points). These informed parsing, conservative supported robots matching, and candidate-only write requests. Installed HTTPX2/HTTPcore2 transport signatures were also inspected. Offline tests verify numeric-address connections with retained Host/TLS hostname verification; this does not establish arbitrary future network behavior.

Actual public HTML collection and retained-source inspection were performed during M3. Main [English doctor directory](https://telescopecenter.com/doctors/) and its Arabic variant preserve explicit doctor occurrences; [FAQ](https://telescopecenter.com/faqs/) working-hours content was found in native closed accordion details. This supersedes the earlier limited inspection's unknown-hours observation. The raw answer covers distinct clinic, pharmacy, and optical-center hours; interval interpretation and current factual acceptance remain unverified.

Source review also found template/placeholder content and inconsistent derivative directory pages. Such material cannot become authoritative merely because collection succeeded. The runbook/status distinguish raw collection, cleaned draft preparation, reviewed knowledge, and live indexing. Actual retained snapshot IDs/counts/gaps are recorded in [PROJECT_STATUS.md](../PROJECT_STATUS.md); no paid embedding, Qdrant request, active alias change, retrieval comparison, or deployment was performed.
