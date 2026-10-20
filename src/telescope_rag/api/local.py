"""Explicit localhost MVP composition over the pinned, reviewed website snapshot."""

import asyncio
import json
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx2 as httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import Field

from telescope_rag.api.hours_responses import HoursResponseQuestion, ResponseWebsiteLink
from telescope_rag.api.hours_service import HoursChatService
from telescope_rag.api.main import create_app
from telescope_rag.api.responses import ResponseCitation, ResponseKnowledge, ResponseRecord
from telescope_rag.core.settings import ConfigurationError, Settings, load_settings
from telescope_rag.ingestion.admission import AdmissionPlan
from telescope_rag.ingestion.indexing import EmbeddingCache, EmbeddingConfiguration
from telescope_rag.ingestion.runner import load_reviewed_bundle, read_secret
from telescope_rag.knowledge.hours import PublicHoursPlan
from telescope_rag.knowledge.public_links import PublicLinksCatalog, WebsiteLinksPlan
from telescope_rag.knowledge.source_authority import (
    DirectoryAuthority,
    reviewed_directory_authority,
)
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.providers.qwen_tokenizer import QwenEmbeddingCounter, QwenPreparationCounter
from telescope_rag.retrieval.assembly import EvidenceCatalog
from telescope_rag.retrieval.candidate import CandidateDenseReader
from telescope_rag.retrieval.contracts import KnowledgeReadiness
from telescope_rag.retrieval.duplicates import DuplicateIndex
from telescope_rag.retrieval.request_dense import RequestDenseRetriever

COLLECTION = "telescope_public_018817ac10ec05ecad92adb9"
PREPARED_DIGEST = "a46be2d3fd18f11d46c79ff9bc992de22aab496836894a708bc57c1e8b48af88"
HOURS_DIGEST = "609a93a48f86b802c3ab2356a128fbc3b8736079dfd241b5ffa1572f1a5e59f7"
LINKS_DIGEST = "42b6ff716b519affa9c917422904a80426fac9bd59e83d03299bcfa2683cd331"
TOKENIZER_REVISION = "1d8ad4ca9b3dd8059ad90a75d4983776a23d44af"
OUTPUT_TOKENS = 4096


def local_settings(root: Path) -> Settings:
    """Keep dotenv credentials and explicitly select bounded development settings."""
    source = load_settings(root / ".env")
    return _profile_settings(source, "http://127.0.0.1:6333", root / ".tools/qdrant-m3/read.key")


def container_settings(secrets: Path = Path("/run/secrets")) -> Settings:
    """Explicit local container composition, with file secrets and no dotenv."""
    source = Settings(
        _env_file=None,
        openrouter_api_key=read_secret(secrets / "openrouter_key"),
        qdrant_api_key=read_secret(secrets / "qdrant_read_key"),
    )
    return _profile_settings(source, "http://telescope-m3-qdrant:6333", secrets / "qdrant_read_key")


def _profile_settings(source: Settings, qdrant_url: str, read_key: Path) -> Settings:
    if source.app_env == "production":
        raise ConfigurationError("Local MVP cannot run with APP_ENV=production.")
    values = source.model_dump()
    values.update(
        host="127.0.0.1",
        qdrant_url=qdrant_url,
        qdrant_api_key=read_secret(read_key),
        chat_input_accounting="reported_usage",
        provider_max_retries=0,
        max_llm_calls=2,
        max_total_output_tokens=2 * OUTPUT_TOKENS,
        retrieval_top_k_per_question=11,
        provider_timeout_seconds=60,
        request_timeout_seconds=150,
        log_level="WARNING",
    )
    # Revalidate rather than using unchecked model_copy for runtime settings.
    return Settings(_env_file=None, **values)


@dataclass(frozen=True)
class LocalResources:
    catalog: EvidenceCatalog
    authority: DirectoryAuthority
    hours: PublicHoursPlan
    counter: QwenPreparationCounter
    configuration: EmbeddingConfiguration
    tokenizer: Path
    website_links: PublicLinksCatalog | None = None


def load_resources(root: Path) -> LocalResources:
    """Validate existing admission/digests; never collect, embed or mutate the corpus."""
    bundle = load_reviewed_bundle(root / "data/processed/m3-execution-approved-v6-v2")
    catalog = EvidenceCatalog(bundle.documents, expected_digest=PREPARED_DIGEST)
    metadata = root / "data/processed/m3-llm-semantic-token-validated-v6/metadata"
    authority = reviewed_directory_authority(
        AdmissionPlan.model_validate_json((metadata / "source-admission-plan.json").read_bytes()),
        json.loads((metadata / "primary-directory.json").read_bytes()),
        prepared_digest=PREPARED_DIGEST,
    )
    if any(
        chunk.admission_policy_hash != authority.admission_policy_hash
        for chunk in catalog.chunks.values()
    ):
        raise ConfigurationError(
            "Local directory metadata differs from the admitted source policy."
        )
    hours = PublicHoursPlan.model_validate_json(
        (root / "artifacts/m5-public-hours-v1/reviewed-hours-plan.json").read_bytes()
    )
    tokenizer = root / f".tools/qwen-tokenizer/{TOKENIZER_REVISION}/tokenizer.json"
    links = PublicLinksCatalog(
        WebsiteLinksPlan.model_validate_json(
            (root / "artifacts/public-website-links-v1/reviewed-links-plan.json").read_bytes()
        ),
        expected_digest=LINKS_DIGEST,
        base_prepared_digest=PREPARED_DIGEST,
        pages=tuple(document.document.page for document in bundle.documents),
    )
    counter = QwenPreparationCounter(tokenizer)
    if counter.count(json.dumps(links.rendering(tuple(links.links)), ensure_ascii=False)) > 1600:
        raise ConfigurationError("Reviewed website link evidence exceeds its local ceiling.")
    return LocalResources(
        catalog,
        authority,
        hours,
        counter,
        bundle.configuration,
        tokenizer,
        links,
    )


class LocalChatResponse(ResponseRecord):
    """Local wire: retain provenance without inheriting inaccurate offline-only flags."""

    schema_version: Literal["local-mvp-response-v1"] = "local-mvp-response-v1"
    mode: Literal["local_mvp"] = "local_mvp"
    answer_style: Literal["conversational"] = "conversational"
    request_id: str
    status: Literal["draft_ready", "not_found", "out_of_scope", "clarification_required"]
    answer: str = Field(repr=False)
    answer_format: Literal["plain_text"] = "plain_text"
    language: Literal["en", "ar", "ar-JO"]
    questions: tuple[HoursResponseQuestion, ...] = Field(min_length=1, max_length=4, repr=False)
    citations: tuple[ResponseCitation, ...] = Field(max_length=64, repr=False)
    unresolved_questions: tuple[str, ...] = Field(max_length=4)
    knowledge: ResponseKnowledge | None
    website_links: tuple[ResponseWebsiteLink, ...] = Field(default=(), max_length=32)
    website_links_digest: str | None = None


class LocalKnowledgeProbe:
    """Report readiness for this explicitly admitted local snapshot, without inference."""

    def __init__(self, reader: CandidateDenseReader, resources: LocalResources):
        self.reader, self.resources = reader, resources

    async def check_readiness(self) -> KnowledgeReadiness:
        info = await self.reader.info()
        vectors = info.get("config", {}).get("params", {}).get("vectors", {})
        valid = (
            info.get("status") == "green"
            and info.get("points_count") == len(self.resources.catalog.chunks)
            and vectors.get("size") == 4096
            and vectors.get("distance") == "Cosine"
        )
        return KnowledgeReadiness(
            reachable=True,
            approved=valid,
            snapshot_id=next(iter(self.resources.catalog.chunks.values())).snapshot_id,
            embedding_model="qwen/qwen3-embedding-8b",
            dimensions=4096,
        )

    async def aclose(self) -> None:
        # The local application's exit stack owns both network clients.
        return None


def create_local_app(
    root: Path | None = None,
    *,
    provider_transport: httpx.AsyncBaseTransport | None = None,
    qdrant_transport: httpx.AsyncBaseTransport | None = None,
    runtime: Literal["host", "container"] = "host",
) -> FastAPI:
    """Uvicorn factory. Explicit opt-in; the original default app stays fail-closed.

    Transports are trusted offline test injection only, never public inputs.
    Run from the repository root so data and credentials resolve predictably.
    """
    root = (root or Path.cwd()).resolve()
    if runtime not in {"host", "container"}:
        raise ConfigurationError("Unknown local runtime.")
    settings = local_settings(root) if runtime == "host" else container_settings()
    if not settings.has_model_credentials:
        raise ConfigurationError(
            "Configure the project's OpenRouter key before starting Local MVP."
        )
    resources = load_resources(root)
    providers = OpenRouterProviders(
        settings,
        token_counter=QwenEmbeddingCounter(resources.tokenizer),
        transport=provider_transport,
    )
    reader = CandidateDenseReader(
        settings,
        settings.qdrant_api_key,
        collection=COLLECTION,
        chunks={c.point_id: c for c in resources.catalog.chunks.values()},
        transport=qdrant_transport,
        target="loopback" if runtime == "host" else "local_container",
    )
    retriever = RequestDenseRetriever(
        settings=settings,
        catalog=resources.catalog,
        configuration=resources.configuration,
        counter=resources.counter,
        embeddings=providers.embeddings,
        reader=reader,
        cache=EmbeddingCache(root / "data/processed/m4-query-cache-v1"),
        lexical_rescue_limit=2,
        ancestor_context_limit=1,
        duplicate_index=DuplicateIndex(resources.catalog.chunks),
        duplicate_margin=12,
    )
    service = HoursChatService(
        settings=settings,
        chat=providers.chat,
        retriever=retriever,
        catalog=resources.catalog,
        counter=resources.counter,
        directory_authority=resources.authority,
        hours_plan=resources.hours,
        expected_hours_plan_digest=HOURS_DIGEST,
        planner_output_tokens=OUTPUT_TOKENS,
        draft_output_tokens=OUTPUT_TOKENS,
        hours_profile="contracts_v14",
        reviewed_profile_limitations=True,
        source_page_clarifications=True,
        local_mvp_search=True,
        conversational_answers=True,
        website_links=resources.website_links,
        reuse_page_candidates=True,
    )
    probe = LocalKnowledgeProbe(reader, resources)
    app = create_app(
        settings,
        knowledge_probe=probe,
        offline_chat_service=service,
        offline_response_format="local",
    )
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            stack.push_async_callback(providers.aclose)
            # Also close the reader if startup readiness fails before the old lifespan.
            stack.push_async_callback(reader.aclose)
            async with asyncio.timeout(settings.readiness_timeout_seconds):
                readiness = await probe.check_readiness()
            if not readiness.approved:
                raise ConfigurationError("The pinned local knowledge collection is not ready.")
            async with original_lifespan(app):
                yield

    app.router.lifespan_context = lifespan
    app.title = "Telescope local RAG MVP"
    app.description = "Local development chat over reviewed public website evidence."
    app.state.local_providers = providers

    @app.get("/", include_in_schema=False)
    async def home() -> FileResponse:
        return FileResponse(Path(__file__).with_name("local_chat.html"))

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(
        "telescope_rag.api.local:create_local_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        access_log=False,
    )


if __name__ == "__main__":
    main()
