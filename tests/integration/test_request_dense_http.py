"""Full HTTP/graph/embedding/candidate-reader flow with synthetic sources and mock transports."""

import asyncio
import json

import httpx2 as httpx
import pytest
from test_anchored_workflow import part, wire
from test_offline_service import RecordingChat, compose
from test_request_dense import COLLECTION, VECTOR, environment
from test_request_dense import fixture_tokenizer as fixture_tokenizer

from telescope_rag.api.main import create_app
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft
from telescope_rag.ingestion.indexing import EmbeddingCache, configuration_hash
from telescope_rag.knowledge.source_authority import DirectoryAuthority
from telescope_rag.retrieval.request_dense import RequestDenseRetriever, query_cache_key


class RecordingEmbeddings:
    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = []

    async def embed(self, texts, *, role, format, budget):
        self.calls.append((tuple(texts), budget))
        return await self.delegate.embed(texts, role=role, format=format, budget=budget)


TEXTS = [
    (
        "en",
        (
            "Report the role of Synthetic Person A.",
            " Also report the role of Synthetic Person B.",
            " Do not book an appointment.",
        ),
    ),
    ("ar", ("انقل دور الشخص التجريبي أ.", " وانقل دور الشخص التجريبي ب.", " ولا تحجز موعداً.")),
    ("ar-JO", ("هات دور الشخص التجريبي أ.", " وكمان دور الشخص التجريبي ب.", " ولا تحجز موعد.")),
]


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize("mode", ["search", "cached", "read_source", "missing"])
def test_http_actual_graph_uses_shared_embedding_budget_and_keeps_owners(
    fixture_tokenizer, tmp_path, text, mode
):
    async def run():
        language, targets = text
        env = None
        bindings = None
        seen = []

        def chat_handler(received):
            body = json.loads(json.loads(received.read())["messages"][-1]["content"])
            seen.append(body)
            if "max_parts" in body:
                assert body["original_query"] == "".join(targets)
                handle = next(h for h, i in bindings.documents.items() if i == "main")
                owners = {i[1]: h for h, i in bindings.owners.items() if i[0] == "literal"}
                # Prohibition remains a constraint on the second public target,
                # not an extra requested booking action. Both people stay distinct.
                first = part(
                    targets[0],
                    intended_use="doctor_role",
                    document_handles=(handle,),
                    owner_handle=owners["a"],
                    operation="read_source" if mode == "read_source" else "search",
                    retrieval_query=None if mode == "read_source" else targets[0],
                )
                second_text = targets[1] + targets[2]
                second = part(
                    second_text,
                    intended_use="doctor_role",
                    document_handles=(handle,),
                    owner_handle=owners["b"],
                    constraint_quotes=(targets[2],),
                    operation="read_source" if mode == "read_source" else "search",
                    retrieval_query=None if mode == "read_source" else second_text,
                )
                return wire(AnchoredPlannerReply(language=language, parts=(first, second)))
            return wire(
                AnswerDraft(
                    parts=tuple(
                        PartDraft(
                            part_id=p["part_id"],
                            status="candidate",
                            quotes=tuple(
                                QuoteDraft(chunk_id=i, quote=env.catalog.chunks[i].retrieval_text)
                                for i in p["eligible_quote_chunk_ids"]
                            ),
                            reason_code=None,
                        )
                        for p in body["parts"]
                    )
                )
            )

        cache = EmbeddingCache(tmp_path / "cache")
        async with environment(
            fixture_tokenizer,
            mode="empty_results" if mode == "missing" else "normal",
            cache=cache,
            chat_handler=chat_handler,
        ) as value:
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
            embedding = RecordingEmbeddings(env.providers.embeddings)
            chat = RecordingChat(env.providers.chat)
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
                for q in (targets[0], targets[1] + targets[2]):
                    cache.put(query_cache_key(q, cfg), cfg, VECTOR)
            before = {p.name: p.read_bytes() for p in cache.directory.iterdir()}
            service = compose(env.settings, env.catalog, authority, chat, bridge)
            app = create_app(env.settings, offline_chat_service=service)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/chat",
                    json={
                        "query": "".join(targets),
                        "language": "en" if language == "en" else "ar",
                    },
                )
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["request_id"] == response.headers["X-Request-ID"]
            assert result["offline_only"] is True and result["semantic_grounding_verified"] is False
            assert [p["original_text"] for p in result["parts"]] == [
                targets[0],
                targets[1] + targets[2],
            ]
            assert result["language"] == language
            assert len(chat.calls) == (1 if mode == "missing" else 2)
            budget = chat.calls[0][1]
            assert all(b is budget for _, b in chat.calls)
            assert len(embedding.calls) == (0 if mode in {"cached", "read_source"} else 1)
            if embedding.calls:
                assert embedding.calls[0][1] is budget
                assert embedding.calls[0][0] == (targets[0], targets[1] + targets[2])
            assert budget.operations["embedding"] == len(embedding.calls)
            assert budget.operations["chat"] == len(chat.calls)
            if mode == "missing":
                assert result["outcome"] == "not_found" and all(
                    not p["quotes"] for p in result["parts"]
                )
            else:
                assert result["outcome"] == "draft_ready"
                for p, owner, source in zip(
                    result["parts"], ("a", "b"), env.values[:2], strict=True
                ):
                    assert p["quotes"][0]["literal_owner_id"] == owner
                    assert p["quotes"][0]["canonical_owner_id"] == "canonical-" + owner
                    assert p["quotes"][0]["quote"] == source.retrieval_text
                    assert p["quotes"][0]["source_url"] == source.canonical_url
                    if mode == "read_source":
                        assert p["admitted_scope_complete"] is True
            assert len(env.reads) == (0 if mode == "read_source" else 2)
            assert all(len(r["filter"]["must"][0]["has_id"]) == 1 for r in env.reads)
            assert {p.name: p.read_bytes() for p in cache.directory.iterdir()} == before

    asyncio.run(run())


def test_http_altered_qdrant_payload_blocks_drafting_and_sanitizes_error(fixture_tokenizer):
    async def run():
        bindings = None
        seen = []

        def chat_handler(received):
            body = json.loads(json.loads(received.read())["messages"][-1]["content"])
            seen.append(body)
            assert "max_parts" in body, "No draft call is allowed after failed source validation"
            handle = next(h for h, i in bindings.documents.items() if i == "main")
            owner = next(h for h, i in bindings.owners.items() if i == ("literal", "a"))
            return wire(
                AnchoredPlannerReply(
                    language="en",
                    parts=(
                        part(
                            body["original_query"],
                            intended_use="doctor_role",
                            document_handles=(handle,),
                            owner_handle=owner,
                        ),
                    ),
                )
            )

        async with environment(
            fixture_tokenizer, mode="bad_payload", chat_handler=chat_handler
        ) as env:
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
            app = create_app(
                env.settings,
                offline_chat_service=compose(
                    env.settings, env.catalog, authority, env.providers.chat, env.bridge
                ),
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/chat", json={"query": "Report role for Synthetic Person A."}
                )
            assert (
                response.status_code == 502
                and response.json()["error"]["code"] == "offline_draft_failed"
            )
            assert len(seen) == len(env.embeddings) == len(env.reads) == 1
            assert "Altered source." not in response.text and COLLECTION not in response.text

    asyncio.run(run())
