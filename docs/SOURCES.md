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
