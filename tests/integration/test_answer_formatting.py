"""List presentation preserves separate source owners and unchanged support metadata."""

import asyncio
import json

import httpx2 as httpx
import pytest
from test_anchored_workflow import part
from test_local_mvp import compose

from telescope_rag.graph.contracts import AnswerSentence, ConversationalDraft, ConversationalPart
from telescope_rag.graph.source_choices import SourceChoicePlannerPart, SourceChoicePlannerReply
from telescope_rag.providers.contracts import StructuredResult


@pytest.mark.parametrize(
    "language,texts",
    [
        ("en", ("A: published field.", "B: the same field, with a separate owner.")),
        ("ar", ("الطبيب أ: المجال المذكور.", "الطبيب ب: المجال نفسه مع مصدره المنفصل.")),
        ("ar-JO", ("الطبيب أ: هاد مجاله.", "الطبيب ب: نفس المجال ومصدره منفصل.")),
    ],
)
@pytest.mark.parametrize("bullets", [True, False])
def test_owned_items_get_line_breaks_but_short_prose_stays_compact(
    monkeypatch,
    tmp_path,
    language,
    texts,
    bullets,
):
    async def run():
        app, provider, _ = compose(monkeypatch, tmp_path)
        workflow = app.state.offline_chat_service._workflow
        document = next(
            h for h, identity in workflow._bindings.documents.items() if identity == "main"
        )
        supplied = tuple(("• " if bullets else "") + text for text in texts)

        async def complete(messages, output_model, **kwargs):
            body = json.loads(messages[-1].content)
            if output_model is SourceChoicePlannerReply:
                entry = part(
                    body["original_query"],
                    operation="read_source",
                    retrieval_query=None,
                    document_handles=(document,),
                ).model_dump()
                return StructuredResult(
                    SourceChoicePlannerReply(
                        language=language,
                        parts=(SourceChoicePlannerPart(**entry, hours=None, clarification=None),),
                    ),
                    (),
                )
            target = body["parts"][0]
            sources = [workflow._catalog.chunks[i] for i in target["eligible_quote_chunk_ids"]]
            by_owner = {c.doctor_id: c.chunk_id for c in sources}
            return StructuredResult(
                ConversationalDraft(
                    parts=(
                        ConversationalPart(
                            part_id=target["part_id"],
                            status="candidate",
                            reason_code=None,
                            sentences=tuple(
                                AnswerSentence(text=text, chunk_ids=(by_owner[owner],))
                                for text, owner in zip(supplied, ("a", "b"), strict=True)
                            ),
                        ),
                    )
                ),
                (),
            )

        provider.complete = complete
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/chat", json={"query": "Tell me about A and B."}
                )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["answer"] == ("\n\n" if bullets else " ").join(supplied)
        assert {c["literal_owner_id"] for c in data["citations"]} == {"a", "b"}
        assert all(c["question_id"] == data["questions"][0]["id"] for c in data["citations"])
        for citation in data["citations"]:
            assert (
                citation["quote"] == workflow._catalog.chunks[citation["chunk_id"]].retrieval_text
            )

    asyncio.run(run())
