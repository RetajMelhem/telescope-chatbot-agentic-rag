"""Mixed hours/source questions through real adapters with authored mock model replies.

Synthetic sources/vectors/tokenizer exercise contracts, never semantic model accuracy.
"""

import asyncio
import json
from datetime import timedelta

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from test_anchored_workflow import part, wire
from test_hours_graph import NOW, fixtures, inputs
from test_offline_service import RecordingChat
from test_offline_workflow import catalog
from test_public_hours import reference
from test_request_dense import COLLECTION, VECTOR
from test_request_dense import fixture_tokenizer as fixture_tokenizer
from test_request_dense_http import RecordingEmbeddings

from telescope_rag.api.hours_service import HoursChatService
from telescope_rag.api.main import create_app
from telescope_rag.core.settings import Settings
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft
from telescope_rag.graph.hours_contract import ContractHoursPlannerPart, ContractHoursPlannerReply
from telescope_rag.ingestion.indexing import (
    EmbeddingCache,
    EmbeddingConfiguration,
    configuration_hash,
)
from telescope_rag.ingestion.models import stable_id
from telescope_rag.knowledge.hours import hours_plan_digest
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.providers.qwen_tokenizer import (
    COUNT_PROFILE,
    QwenEmbeddingCounter,
    QwenPreparationCounter,
    hosted_qwen_format,
)
from telescope_rag.retrieval.candidate import CandidateDenseReader
from telescope_rag.retrieval.request_dense import RequestDenseRetriever, query_cache_key

TEXTS = (
    (
        "en",
        "When does the center open?",
        "the center",
        " Also state Synthetic A's published role.",
        " Also state Synthetic B's published role.",
        " Book an appointment.",
    ),
    (
        "ar",
        "متى يفتح المركز؟",
        "المركز",
        " واذكر دور الطبيب التجريبي أ المنشور.",
        " واذكر دور الطبيب التجريبي ب المنشور.",
        " واحجز موعداً.",
    ),
    (
        "ar-JO",
        "إيمتى بيفتح المركز؟",
        "المركز",
        " وكمان شو دور الطبيب التجريبي أ المكتوب؟",
        " وشو دور الطبيب التجريبي ب المكتوب؟",
        " واحجزلي موعد.",
    ),
)


async def exercise(path, tmp_path, texts, *, mode="search", missing_usage=False):
    language, opening, subject, first, second, booking = texts
    config = Settings(
        _env_file=None,
        app_env="test",
        openrouter_api_key="synthetic-only",
        provider_max_retries=0,
        retrieval_top_k_per_question=2,
    )
    old, authority, hours, _ = fixtures()
    format = hosted_qwen_format()
    counter = QwenPreparationCounter(path)
    values = tuple(
        c.model_copy(
            update={
                "tokenizer_version": COUNT_PROFILE,
                "embedding_format_version": format.version,
                "embedding_format_hash": stable_id("embedding-format-v1", format.model_dump_json()),
                "canonical_doctor_id": "canonical-" + c.doctor_id if c.doctor_id else None,
                "canonical_doctor_name": "Synthetic canonical " + c.doctor_id
                if c.doctor_id
                else None,
            }
        )
        for c in old.chunks.values()
    )
    evidence = catalog(*values)
    authority = authority.model_copy(update={"prepared_digest": evidence.prepared_digest})
    hours = hours.model_copy(
        update={
            "prepared_digest": evidence.prepared_digest,
            "schedules": tuple(
                r.model_copy(
                    update={
                        "evidence": tuple(
                            reference(evidence.chunks[e.chunk_id]) for e in r.evidence
                        ),
                    }
                )
                for r in hours.schedules
            ),
        }
    )
    embedding_config = EmbeddingConfiguration(
        format_version=format.version,
        format_hash=values[0].embedding_format_hash,
        tokenizer_version=COUNT_PROFILE,
        preparation_version=values[0].preparation_version,
    )
    inventory = {c.point_id: c for c in values}
    cache = EmbeddingCache(tmp_path / "cache")
    if mode == "cached":
        for text in (first, second):
            cache.put(
                query_cache_key(text, configuration_hash(embedding_config)),
                configuration_hash(embedding_config),
                VECTOR,
            )
    cache_before = {p.name: p.read_bytes() for p in cache.directory.iterdir()}
    seen, embeddings, reads, runs = [], [], [], []

    def provider_handler(request):
        payload = json.loads(request.read())
        if request.url.path == "/api/v1/embeddings":
            embeddings.append(payload)
            assert payload["input"] == [format.format(t, "query") for t in (first, second)]
            total = sum(counter.count(t) for t in payload["input"])
            return httpx.Response(
                200,
                json={
                    "model": "Qwen/Qwen3-Embedding-8B",
                    "provider": "DeepInfra",
                    "data": [{"index": i, "embedding": list(VECTOR)} for i in range(2)],
                    "usage": {"prompt_tokens": total, "total_tokens": total},
                },
            )
        assert request.url.path == "/api/v1/chat/completions"
        body = json.loads(payload["messages"][-1]["content"])
        seen.append(body)
        if "max_parts" in body:
            bindings = service._workflow._bindings
            handle = next(h for h, identity in bindings.documents.items() if identity == "main")
            owners = {
                identity[1]: h
                for h, identity in bindings.owners.items()
                if identity[0] == "literal"
            }
            proposed = [
                ContractHoursPlannerPart(
                    **part(opening, operation="time_comparison", retrieval_query=None).model_dump(),
                    hours=inputs(service._workflow, subject_text=subject).model_dump(),
                )
            ]
            for text, owner in ((first, "a"), (second, "b")):
                proposed.append(
                    ContractHoursPlannerPart(
                        **part(
                            text,
                            document_handles=(handle,),
                            owner_handle=owners[owner],
                            intended_use="doctor_role",
                            operation="read_source" if mode == "read_source" else "search",
                            retrieval_query=None if mode == "read_source" else text,
                        ).model_dump(),
                        hours=None,
                    )
                )
            proposed.append(
                ContractHoursPlannerPart(
                    **part(
                        booking,
                        state="excluded",
                        operation="search",
                        retrieval_query=None,
                        reason="scope_excluded",
                    ).model_dump(),
                    hours=None,
                )
            )
            return wire(
                ContractHoursPlannerReply(language=language, parts=tuple(proposed)),
                missing_usage=missing_usage,
            )
        assert body["original_query"] == opening + first + second + booking
        parts = []
        for p in body["parts"]:
            allowed = p["eligible_quote_chunk_ids"]
            parts.append(
                PartDraft(
                    part_id=p["part_id"],
                    status="candidate"
                    if allowed
                    else "excluded"
                    if p["state"] == "excluded"
                    else "unknown",
                    quotes=tuple(
                        QuoteDraft(chunk_id=i, quote=evidence.chunks[i].retrieval_text)
                        for i in allowed
                    ),
                    reason_code=None
                    if allowed
                    else "scope_excluded"
                    if p["state"] == "excluded"
                    else "operation_unavailable"
                    if p["operation"] == "time_comparison"
                    else "not_found",
                )
            )
        if mode == "swapped_owners":
            parts[1] = parts[1].model_copy(update={"quotes": parts[2].quotes})
        elif mode == "hours_as_source":
            c = next(c for c in values if c.document_id == "faq-en")
            parts[1] = parts[1].model_copy(
                update={"quotes": (QuoteDraft(chunk_id=c.chunk_id, quote=c.retrieval_text),)}
            )
        elif mode == "altered_quote":
            q = parts[1].quotes[0].model_copy(update={"quote": "Invented unqualified claim."})
            parts[1] = parts[1].model_copy(update={"quotes": (q,)})
        elif mode == "dropped_part":
            parts.pop()
        elif mode == "timeout":
            raise httpx.ReadTimeout("Synthetic sensitive upstream text")
        return wire(AnswerDraft(parts=tuple(parts)), missing_usage=missing_usage)

    def reader_handler(request):
        assert request.method == "POST" and request.url.path.endswith("/points/query")
        assert request.headers["api-key"] == "synthetic-reader"
        body = json.loads(request.read())
        reads.append(body)
        ids = body["filter"]["must"][0]["has_id"]
        assert len(ids) == 1
        points = [
            {"id": i, "score": 1.0, "payload": inventory[i].model_dump(mode="json")} for i in ids
        ]
        if mode == "missing":
            points = []
        elif mode == "bad_payload":
            points[0]["payload"]["original_text"] = "Untrusted changed source."
        return httpx.Response(200, json={"status": "ok", "result": {"points": points}})

    async with OpenRouterProviders(
        config,
        token_counter=QwenEmbeddingCounter(path),
        transport=httpx.MockTransport(provider_handler),
    ) as providers:
        reader = CandidateDenseReader(
            config,
            SecretStr("synthetic-reader"),
            collection=COLLECTION,
            chunks=inventory,
            transport=httpx.MockTransport(reader_handler),
        )
        try:
            chat = RecordingChat(providers.chat)
            embedding = RecordingEmbeddings(providers.embeddings)
            bridge = RequestDenseRetriever(
                settings=config,
                catalog=evidence,
                configuration=embedding_config,
                counter=counter,
                embeddings=embedding,
                reader=reader,
                cache=cache,
            )
            service = HoursChatService(
                settings=config,
                chat=chat,
                retriever=bridge,
                catalog=evidence,
                counter=counter,
                directory_authority=authority,
                hours_plan=hours,
                expected_hours_plan_digest=hours_plan_digest(hours),
                hours_profile="contracts_v14",
                clock=lambda: NOW + timedelta(days=10) if mode == "stale_hours" else NOW,
            )
            original_run = service._workflow.run

            async def record_run(*args, **kwargs):
                run = await original_run(*args, **kwargs)
                runs.append(run)
                return run

            service._workflow.run = record_run
            app = create_app(config, offline_chat_service=service, offline_response_format="hours")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/chat",
                    json={
                        "query": opening + first + second + booking,
                        "language": "en" if language == "en" else "ar",
                    },
                )
        finally:
            await reader.aclose()
    assert {p.name: p.read_bytes() for p in cache.directory.iterdir()} == cache_before
    assert len(chat.calls) <= 2
    budget = chat.calls[0][1]
    assert all(b is budget for _, b in chat.calls + embedding.calls)
    assert budget.operations["embedding"] == len(embedding.calls)
    assert budget.operations["chat"] == len(chat.calls)
    assert len(embeddings) == len(embedding.calls)
    assert len(runs) == 1
    return response, evidence, seen, embeddings, reads, budget, runs[0]


@pytest.mark.parametrize("texts", TEXTS)
@pytest.mark.parametrize("mode", ["search", "cached", "read_source", "missing", "stale_hours"])
@pytest.mark.parametrize("missing_usage", [False, True])
def test_mixed_hours_two_distinct_doctors_and_excluded_booking(
    fixture_tokenizer,
    tmp_path,
    texts,
    mode,
    missing_usage,
):
    response, evidence, seen, embeddings, reads, budget, run = asyncio.run(
        exercise(
            fixture_tokenizer,
            tmp_path,
            texts,
            mode=mode,
            missing_usage=missing_usage,
        )
    )
    assert response.status_code == 200, response.text
    assert run.result.error_code is None
    value = response.json()
    assert value["request_id"] == response.headers["X-Request-ID"]
    assert value["language"] == texts[0]
    assert value["offline_only"] and not value["semantic_grounding_verified"]
    assert not value["luna_compatibility_verified"]
    assert [q["question"] for q in value["questions"]] == [texts[i] for i in (1, 3, 4, 5)]
    opening, first, second, booking = value["questions"]
    assert opening["hours"]["status"] == (
        "unknown" if mode == "stale_hours" else "schedule_available"
    )
    if mode == "stale_hours":
        assert opening["hours"]["reason"] == "stale_hours"
    assert booking["status"] == "excluded" and not booking["citation_ids"]
    assert booking["hours"] is None
    assert len(embeddings) == (0 if mode in {"cached", "read_source"} else 1)
    assert len(reads) == (0 if mode == "read_source" else 2)
    assert len(seen) == (1 if mode == "missing" else 2)
    citations = {c["id"]: c for c in value["citations"]}
    assert len(citations) == (2 if mode == "missing" else 4)
    for question, owner in ((first, "a"), (second, "b")):
        assert question["hours"] is None
        if mode == "missing":
            assert question["status"] == "unknown" and not question["citation_ids"]
            continue
        assert question["status"] == "candidate"
        assert len(question["citation_ids"]) == 1
        citation = citations[question["citation_ids"][0]]
        source = evidence.chunks[citation["chunk_id"]]
        assert citation["question_id"] == question["id"]
        assert citation["literal_owner_id"] == owner
        assert citation["canonical_owner_id"] == "canonical-" + owner
        assert citation["quote"] == source.retrieval_text
        assert citation["url"] == source.canonical_url
        assert citation["fetched_at"] == source.fetched_at.isoformat().replace("+00:00", "Z")
        assert source.retrieval_text in question["answer"]
    if missing_usage:
        assert budget.input_charged["chat"] is None
    if len(seen) == 2:
        assert seen[1]["parts"][0]["eligible_quote_chunk_ids"] == []
        assert seen[1]["parts"][3]["eligible_quote_chunk_ids"] == []


@pytest.mark.parametrize(
    "mode",
    [
        "swapped_owners",
        "hours_as_source",
        "altered_quote",
        "dropped_part",
        "bad_payload",
        "timeout",
    ],
)
def test_mixed_rejects_source_corruption_omission_and_failed_drafting_without_retry(
    fixture_tokenizer,
    tmp_path,
    mode,
):
    response, _, seen, embeddings, reads, _, run = asyncio.run(
        exercise(
            fixture_tokenizer,
            tmp_path,
            TEXTS[0],
            mode=mode,
        )
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "offline_draft_failed"
    assert (
        run.result.error_code
        == {
            "swapped_owners": "invalid_citation",
            "hours_as_source": "invalid_citation",
            "altered_quote": "invalid_quotation",
            "dropped_part": "invalid_draft",
            "bad_payload": "retrieval_failed",
            "timeout": "provider_failed",
        }[mode]
    )
    assert len(seen) == (1 if mode == "bad_payload" else 2)
    assert len(embeddings) == 1 and len(reads) <= 2
    assert "synthetic-reader" not in response.text
    assert "sensitive upstream" not in response.text
    assert "Invented" not in response.text and "Untrusted changed" not in response.text


def test_concurrent_mixed_requests_keep_sources_and_budgets_isolated(fixture_tokenizer, tmp_path):
    async def run():
        results = await asyncio.gather(
            *(exercise(fixture_tokenizer, tmp_path / texts[0], texts) for texts in TEXTS)
        )
        assert len({id(result[-2]) for result in results}) == 3
        assert len({result[0].json()["request_id"] for result in results}) == 3
        for result, texts in zip(results, TEXTS, strict=True):
            response, _, seen, embeddings, reads, budget, workflow_run = result
            assert response.status_code == 200
            assert workflow_run.result.error_code is None
            assert response.json()["language"] == texts[0]
            assert seen[0]["original_query"] == texts[1] + texts[3] + texts[4] + texts[5]
            assert len(embeddings) == 1 and len(reads) == len(seen) == 2
            assert budget.operations == {"chat": 2, "embedding": 1}

    asyncio.run(run())
