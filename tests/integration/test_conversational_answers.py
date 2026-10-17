"""Authored prose tests validate contracts and ownership, not LLM factual entailment."""

import asyncio
import json

import httpx2 as httpx
import pytest
from test_anchored_workflow import part
from test_local_mvp import compose

from telescope_rag.graph.contracts import AnswerSentence, ConversationalDraft, ConversationalPart
from telescope_rag.graph.source_choices import SourceChoicePlannerPart, SourceChoicePlannerReply
from telescope_rag.providers.contracts import StructuredResult

TEXTS = {
    "en": (
        [
            "Tell me about A.",
            " Tell me about B.",
            " Book a private appointment.",
            " What does it cost?",
        ],
        ["A's published field is the same as B's.", "B also works in that field."],
    ),
    "ar": (
        ["أخبرني عن الطبيب أ.", " أخبرني عن الطبيب ب.", " احجز موعدًا خاصًا.", " ما التكلفة؟"],
        ["الطبيب أ يعمل في المجال المذكور بالموقع.", "الطبيب ب يعمل في المجال نفسه."],
    ),
    "ar-JO": (
        ["احكيلي عن الطبيب أ.", " واحكيلي عن الطبيب ب.", " واحجزلي موعد خاص.", " وشو التكلفة؟"],
        ["الطبيب أ شغله بالمجال المذكور عالموقع.", "والطبيب ب كمان بنفس المجال."],
    ),
}


async def exercise(monkeypatch, root, language="en", failure=None):
    app, provider, _ = compose(monkeypatch, root)
    workflow = app.state.offline_chat_service._workflow
    bindings = workflow._bindings
    docs = {value: key for key, value in bindings.documents.items()}
    owners = {value: key for key, value in bindings.owners.items()}
    segments, answers = TEXTS[language]
    seen = []
    runs = []
    original_run = workflow.run

    async def record(*args, **kwargs):
        value = await original_run(*args, **kwargs)
        runs.append(value)
        return value

    workflow.run = record

    async def complete(messages, output_model, *, budget, **kwargs):
        body = json.loads(messages[-1].content)
        seen.append((body, budget))
        if output_model is SourceChoicePlannerReply:
            proposed = []
            for i, text in enumerate(segments):
                entry = part(
                    text,
                    operation="read_source",
                    retrieval_query=None,
                    document_handles=(docs["main" if i < 2 else "contact"],),
                    owner_handle=owners[("literal", "a" if i == 0 else "b")] if i < 2 else None,
                ).model_dump()
                if i == 2:
                    entry.update(
                        state="excluded",
                        operation="search",
                        document_handles=(),
                        owner_handle=None,
                        reason="Private booking is excluded.",
                    )
                proposed.append(SourceChoicePlannerPart(**entry, hours=None, clarification=None))
            return StructuredResult(
                SourceChoicePlannerReply(language=language, parts=tuple(proposed)), ()
            )
        assert output_model is ConversationalDraft
        assert body["original_query"] == "".join(segments)
        assert body["language"] == language and body["untrusted_candidate_rendering"]
        proposed = []
        for i, item in enumerate(body["parts"]):
            selected = item["eligible_quote_chunk_ids"]
            if i < 2:
                ids = (selected[0],)
                if failure == "borrow_sibling" and i == 0:
                    ids = (body["parts"][1]["eligible_quote_chunk_ids"][0],)
                elif failure == "unknown_id" and i == 0:
                    ids = ("unissued-source",)
                elif failure == "duplicate_id" and i == 0:
                    ids = ids * 2
                text = answers[i] + (" [C9.9]" if failure == "fake_marker" and i == 0 else "")
                entry = ConversationalPart(
                    part_id=item["part_id"],
                    status="candidate",
                    reason_code=None,
                    sentences=(AnswerSentence(text=text, chunk_ids=ids),),
                )
            else:
                entry = ConversationalPart(
                    part_id=item["part_id"],
                    status="excluded" if i == 2 else "unknown",
                    sentences=(),
                    reason_code="scope_excluded" if i == 2 else "not_found",
                )
            if failure == "override_excluded" and i == 2:
                entry = entry.model_copy(update={"status": "unknown", "reason_code": "not_found"})
            proposed.append(entry)
        if failure == "omit_part":
            proposed.pop()
        elif failure == "duplicate_part":
            proposed[-1] = proposed[0]
        return StructuredResult(ConversationalDraft(parts=tuple(proposed)), ())

    provider.complete = complete
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            response = await c.post(
                "/api/v1/chat",
                json={"query": "".join(segments), "language": "en" if language == "en" else "ar"},
            )
    assert len(seen) == 2, (runs[0].result.error_code, runs[0].stages)
    assert seen[0][1] is seen[1][1]
    return response, answers


@pytest.mark.parametrize("language", TEXTS)
def test_natural_prose_keeps_distinct_owners_unknown_and_excluded(monkeypatch, tmp_path, language):
    response, answers = asyncio.run(exercise(monkeypatch, tmp_path, language))
    assert response.status_code == 200
    data = response.json()
    assert data["answer_style"] == "conversational"
    assert all(text in data["answer"] for text in answers)
    assert "Source excerpt:" not in data["answer"] and "مقتطف من المصدر" not in data["answer"]
    assert [p["status"] for p in data["questions"]] == [
        "candidate",
        "candidate",
        "excluded",
        "unknown",
    ]
    assert not data["questions"][2]["citation_ids"] and not data["questions"][3]["citation_ids"]
    assert len(data["unresolved_questions"]) == 2
    assert {c["literal_owner_id"] for c in data["citations"]} == {"a", "b"}
    assert all(c["quote"] not in data["answer"] for c in data["citations"])
    assert all(c["snapshot_id"] and c["fetched_at"] and c["url"] for c in data["citations"])
    assert "[C" not in data["answer"]
    for question in data["questions"]:
        assert "[C" not in question["answer"]
        assert set(question["citation_ids"]) == {
            c["id"] for c in data["citations"] if c["question_id"] == question["id"]
        }


@pytest.mark.parametrize(
    "failure",
    [
        "borrow_sibling",
        "unknown_id",
        "duplicate_id",
        "fake_marker",
        "override_excluded",
        "omit_part",
        "duplicate_part",
    ],
)
def test_bad_generated_references_or_coverage_fail_without_repair(monkeypatch, tmp_path, failure):
    response, _ = asyncio.run(exercise(monkeypatch, tmp_path, failure=failure))
    assert response.status_code == 502
    assert "answer" not in response.json()
