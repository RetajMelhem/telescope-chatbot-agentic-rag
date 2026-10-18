"""Local graph offers same-page siblings under each part's own scope, without more reads."""

import asyncio
import json

import httpx2 as httpx
from test_anchored_workflow import part
from test_local_mvp import compose
from test_offline_workflow import FakeRetriever

from telescope_rag.graph.contracts import AnswerSentence, ConversationalDraft, ConversationalPart
from telescope_rag.graph.source_choices import SourceChoicePlannerPart, SourceChoicePlannerReply
from telescope_rag.providers.contracts import StructuredResult


def test_second_part_can_use_already_retrieved_page_without_an_extra_read(monkeypatch, tmp_path):
    async def run():
        app, provider, _ = compose(monkeypatch, tmp_path)
        workflow = app.state.offline_chat_service._workflow
        document = next(
            h for h, identity in workflow._bindings.documents.items() if identity == "main"
        )
        first = next(c.chunk_id for c in workflow._catalog.chunks.values() if c.doctor_id == "a")
        second = next(c.chunk_id for c in workflow._catalog.chunks.values() if c.doctor_id == "b")
        workflow._retriever = FakeRetriever(lambda i, q: (first,))
        runs = []
        original_run = workflow.run

        async def record(*args, **kwargs):
            result = await original_run(*args, **kwargs)
            runs.append(result)
            return result

        workflow.run = record
        query = "List A and B. What is their field?"

        async def complete(messages, output_model, **kwargs):
            body = json.loads(messages[-1].content)
            if output_model is SourceChoicePlannerReply:
                values = (
                    part(
                        "List A and B.",
                        operation="read_source",
                        retrieval_query=None,
                        document_handles=(document,),
                    ),
                    part(" What is their field?"),
                )
                return StructuredResult(
                    SourceChoicePlannerReply(
                        language="en",
                        parts=tuple(
                            SourceChoicePlannerPart(
                                **value.model_dump(), hours=None, clarification=None
                            )
                            for value in values
                        ),
                    ),
                    (),
                )
            assert second in body["parts"][1]["eligible_quote_chunk_ids"]
            return StructuredResult(
                ConversationalDraft(
                    parts=tuple(
                        ConversationalPart(
                            part_id=value["part_id"],
                            status="candidate",
                            reason_code=None,
                            sentences=(
                                AnswerSentence(
                                    text="A and B share the stated field.",
                                    chunk_ids=(first, second),
                                ),
                            ),
                        )
                        for value in body["parts"]
                    )
                ),
                (),
            )

        provider.complete = complete
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as c:
                response = await c.post("/api/v1/chat", json={"query": query})
        assert response.status_code == 200, (response.text, runs[0].result.error_code)
        data = response.json()
        assert len(data["questions"]) == 2
        assert len(workflow._retriever.calls) == 1
        for question in data["questions"]:
            assert {
                c["literal_owner_id"]
                for c in data["citations"]
                if c["question_id"] == question["id"]
            } == {"a", "b"}

    asyncio.run(run())
