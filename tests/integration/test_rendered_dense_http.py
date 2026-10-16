"""Complete rendered path with actual graph/embedding/reader; all transport is mocked."""

import asyncio
import json

import httpx2 as httpx
import pytest
from test_anchored_workflow import part, wire
from test_offline_service import RecordingChat, compose
from test_request_dense import VECTOR, environment
from test_request_dense import fixture_tokenizer as fixture_tokenizer
from test_request_dense_http import TEXTS, RecordingEmbeddings

from telescope_rag.api.main import create_app
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft
from telescope_rag.ingestion.indexing import EmbeddingCache, configuration_hash
from telescope_rag.knowledge.source_authority import DirectoryAuthority
from telescope_rag.retrieval.request_dense import RequestDenseRetriever, query_cache_key


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize("mode", ["search", "cached", "read_source"])
def test_rendered_http_full_path_keeps_exact_source_text_two_owners_and_one_budget(
    fixture_tokenizer, tmp_path, text, mode
):
    async def run():
        language, targets = text
        env, bindings = None, None

        def chat_handler(received):
            body = json.loads(json.loads(received.read())["messages"][-1]["content"])
            if "max_parts" in body:
                handle = next(h for h, i in bindings.documents.items() if i == "main")
                owners = {i[1]: h for h, i in bindings.owners.items() if i[0] == "literal"}
                entries = []
                for index, (target, owner) in enumerate(
                    ((targets[0], "a"), (targets[1] + targets[2], "b"))
                ):
                    entries.append(
                        part(
                            target,
                            intended_use="doctor_role",
                            document_handles=(handle,),
                            owner_handle=owners[owner],
                            constraint_quotes=(targets[2],) if index else (),
                            operation="read_source" if mode == "read_source" else "search",
                            retrieval_query=None if mode == "read_source" else target,
                        )
                    )
                return wire(AnchoredPlannerReply(language=language, parts=tuple(entries)))
            return wire(
                AnswerDraft(
                    parts=tuple(
                        PartDraft(
                            part_id=p["part_id"],
                            status="candidate",
                            reason_code=None,
                            quotes=tuple(
                                QuoteDraft(chunk_id=i, quote=env.catalog.chunks[i].retrieval_text)
                                for i in p["eligible_quote_chunk_ids"]
                            ),
                        )
                        for p in body["parts"]
                    )
                )
            )

        cache = EmbeddingCache(tmp_path / "cache")
        async with environment(fixture_tokenizer, cache=cache, chat_handler=chat_handler) as value:
            env = value
            authority = DirectoryAuthority(
                prepared_digest=env.catalog.prepared_digest,
                admission_policy_hash="synthetic-policy",
                primary_directory_document_ids=("main",),
            )
            bindings = SourceBindings(
                env.catalog,
                include_block_types=True,
                directory_authority=authority,
                purpose_contract=True,
            )
            chat, embedding = (
                RecordingChat(env.providers.chat),
                RecordingEmbeddings(env.providers.embeddings),
            )
            bridge = RequestDenseRetriever(
                settings=env.settings,
                catalog=env.catalog,
                configuration=env.configuration,
                counter=env.counter,
                embeddings=embedding,
                reader=env.reader,
                cache=cache,
            )
            if mode == "cached":
                cfg = configuration_hash(env.configuration)
                for query in (targets[0], targets[1] + targets[2]):
                    cache.put(query_cache_key(query, cfg), cfg, VECTOR)
            before = {p.name: p.read_bytes() for p in cache.directory.iterdir()}
            app = create_app(
                env.settings,
                offline_chat_service=compose(env.settings, env.catalog, authority, chat, bridge),
                offline_response_format="rendered",
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/chat", json={"query": "".join(targets), "language": "auto"}
                )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["status"] == "draft_ready" and body["offline_only"] is True
            assert (
                not body["semantic_grounding_verified"] and not body["luna_compatibility_verified"]
            )
            assert [q["question"] for q in body["questions"]] == [
                targets[0],
                targets[1] + targets[2],
            ]
            assert [c["literal_owner_id"] for c in body["citations"]] == ["a", "b"]
            assert [c["canonical_owner_id"] for c in body["citations"]] == [
                "canonical-a",
                "canonical-b",
            ]
            for q, c, source in zip(
                body["questions"], body["citations"], env.values[:2], strict=True
            ):
                assert c["question_id"] == q["id"] and q["citation_ids"] == [c["id"]]
                assert c["quote"] == source.retrieval_text and source.retrieval_text in q["answer"]
                assert (
                    c["url"] == source.canonical_url
                    and c["fetched_at"] == source.model_dump(mode="json")["fetched_at"]
                )
                if mode == "read_source":
                    assert q["admitted_scope_complete"] is True
            budget = chat.calls[0][1]
            assert len(chat.calls) == 2 and all(b is budget for _, b in chat.calls)
            assert len(embedding.calls) == (1 if mode == "search" else 0)
            assert all(b is budget for _, b in embedding.calls)
            assert len(env.reads) == (0 if mode == "read_source" else 2)
            assert all(len(r["filter"]["must"][0]["has_id"]) == 1 for r in env.reads)
            assert {p.name: p.read_bytes() for p in cache.directory.iterdir()} == before

    asyncio.run(run())
