"""Local composition tests use authored plans and synthetic evidence, with no network."""

import asyncio
import json
from types import SimpleNamespace

import httpx2 as httpx
import pytest
from test_hours_graph import NOW, fixtures, hours_part, inputs
from test_offline_workflow import FakeRetriever, SyntheticCounter

from telescope_rag.api import local
from telescope_rag.core.settings import ConfigurationError, Settings
from telescope_rag.graph.contracts import AnswerSentence, ConversationalDraft, ConversationalPart
from telescope_rag.graph.source_choices import SourceChoicePlannerPart, SourceChoicePlannerReply
from telescope_rag.knowledge.hours import hours_plan_digest
from telescope_rag.providers.contracts import StructuredResult


@pytest.mark.parametrize(
    "language,text,subject",
    [
        ("en", "When does the center open?", "the center"),
        ("ar", "متى يفتح المركز؟", "المركز"),
    ],
)
def test_local_lifespan_health_chat_sources_and_cleanup(
    monkeypatch, tmp_path, language, text, subject
):
    async def run():
        app, provider, reader = compose(monkeypatch, tmp_path)
        assert provider.calls == reader.reads == 0
        async with app.router.lifespan_context(app):
            assert provider.calls == 0 and reader.reads == 1
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                assert (await client.get("/health/ready")).status_code == 200
                ui = await client.get("/")
                assert ui.status_code == 200 and "renderMixedText(answer,data.answer)" in ui.text
                assert "innerHTML" not in ui.text and "language,history" in ui.text
                assert provider.calls == 0
                provider.subject = subject
                response = await client.post(
                    "/api/v1/chat", json={"query": text, "language": language}
                )
                assert response.status_code == 200
                data = response.json()
                assert data["schema_version"] == "local-mvp-response-v1"
                assert data["mode"] == "local_mvp" and "offline_only" not in data
                assert data["questions"][0]["hours"]["status"] == "schedule_available"
                assert data["citations"] and provider.calls == 2
                qid = data["questions"][0]["id"]
                assert all(c["question_id"] == qid for c in data["citations"])
                assert all(
                    c["url"].startswith("https://telescopecenter.com/") for c in data["citations"]
                )
                assert all(c["fetched_at"] and c["snapshot_id"] for c in data["citations"])
                invalid = await client.post(
                    "/api/v1/chat", json={"query": text, "document_handles": []}
                )
                assert invalid.status_code == 422 and provider.calls == 2
        assert provider.closed == 1 and reader.closed == 1

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["count", "dimensions", "distance", "network"])
def test_local_startup_refuses_bad_index_and_closes_clients(monkeypatch, tmp_path, failure):
    async def run():
        app, provider, reader = compose(monkeypatch, tmp_path)
        if failure == "network":
            reader.error = True
        elif failure == "count":
            reader.info_value["points_count"] += 1
        else:
            reader.info_value["config"]["params"]["vectors"][
                "size" if failure == "dimensions" else "distance"
            ] = 32 if failure == "dimensions" else "Dot"
        with pytest.raises((ConfigurationError, ValueError)):
            async with app.router.lifespan_context(app):
                pytest.fail("bad index must not serve")
        assert provider.calls == 0 and provider.closed == reader.closed == 1

    asyncio.run(run())


def test_local_settings_use_dotenv_and_readonly_key_and_reject_production(tmp_path):
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=synthetic-dotenv-key\n", encoding="utf-8")
    secret = tmp_path / ".tools/qdrant-m3/read.key"
    secret.parent.mkdir(parents=True)
    secret.write_text("synthetic-reader", encoding="utf-8")
    settings = local.local_settings(tmp_path)
    assert settings.openrouter_api_key.get_secret_value() == "synthetic-dotenv-key"
    assert settings.qdrant_api_key.get_secret_value() == "synthetic-reader"
    assert settings.host == "127.0.0.1" and settings.provider_max_retries == 0
    assert settings.max_llm_calls == 2 and settings.max_total_output_tokens == 8192
    assert settings.retrieval_top_k_per_question == 11
    (tmp_path / ".env").write_text(
        "APP_ENV=production\nQDRANT_API_KEY=synthetic\n", encoding="utf-8"
    )
    with pytest.raises(ConfigurationError, match="production"):
        local.local_settings(tmp_path)


def compose(monkeypatch, root, *, fixture_args=None, clock=None, website_links=None):
    catalog, authority, hours, _ = fixtures(**(fixture_args or {}))
    config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
    config = Settings(
        _env_file=None,
        **{**config.model_dump(), "provider_max_retries": 0, "max_total_output_tokens": 8192},
    )
    resources = local.LocalResources(
        catalog,
        authority,
        hours,
        SyntheticCounter(),
        SimpleNamespace(),
        root / "synthetic.json",
        website_links,
    )

    class Providers:
        calls = closed = 0
        subject = "the center"

        def __init__(self, *args, **kwargs):
            self.chat = self.embeddings = self

        async def complete(self, messages, output_model, **kwargs):
            self.calls += 1
            body = json.loads(messages[-1].content)
            if output_model is ConversationalDraft:
                return StructuredResult(
                    ConversationalDraft(
                        parts=tuple(
                            ConversationalPart(
                                part_id=p["part_id"],
                                status="candidate",
                                reason_code=None,
                                sentences=(
                                    AnswerSentence(
                                        text="The center opens at 09:00, except Friday at 14:00.",
                                        chunk_ids=tuple(p["eligible_quote_chunk_ids"]),
                                    ),
                                ),
                            )
                            for p in body["parts"]
                        )
                    ),
                    (),
                )
            workflow = app.state.offline_chat_service._workflow
            p = hours_part(
                body["original_query"], inputs(workflow, subject_text=self.subject)
            ).model_dump()
            reply = SourceChoicePlannerReply(
                language=body["requested_language"] if "requested_language" in body else "en",
                parts=(SourceChoicePlannerPart(**p, clarification=None),),
            )
            # Source and hours validators still validate the authored native schema.
            assert output_model is SourceChoicePlannerReply
            return StructuredResult(reply, ())

        async def aclose(self):
            self.closed += 1

    class Reader:
        reads = closed = 0
        error = False

        def __init__(self, *args, **kwargs):
            self.info_value = {
                "status": "green",
                "points_count": len(catalog.chunks),
                "config": {"params": {"vectors": {"size": 4096, "distance": "Cosine"}}},
            }

        async def info(self):
            self.reads += 1
            if self.error:
                raise ValueError("synthetic_unavailable")
            return self.info_value

        async def aclose(self):
            self.closed += 1

    original_service = local.HoursChatService

    def synthetic_service(**kwargs):
        return original_service(
            **kwargs, token_basis="synthetic_test", clock=clock or (lambda: NOW)
        )

    monkeypatch.setattr(local, "local_settings", lambda root: config)
    monkeypatch.setattr(local, "load_resources", lambda root: resources)
    monkeypatch.setattr(local, "QwenEmbeddingCounter", lambda path: None)
    monkeypatch.setattr(local, "OpenRouterProviders", Providers)
    monkeypatch.setattr(local, "CandidateDenseReader", Reader)
    monkeypatch.setattr(
        local, "RequestDenseRetriever", lambda **kwargs: FakeRetriever(lambda i, q: ())
    )
    monkeypatch.setattr(local, "HoursChatService", synthetic_service)
    monkeypatch.setattr(local, "HOURS_DIGEST", hours_plan_digest(hours))
    app = local.create_local_app(root)
    return app, app.state.local_providers, app.state.knowledge_probe.reader
