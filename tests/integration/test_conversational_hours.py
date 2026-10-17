"""Authored hours prose checks wiring and safety, not future model entailment."""

import asyncio
import json
from dataclasses import replace
from datetime import date, timedelta
from uuid import UUID

import httpx2 as httpx
import pytest
from test_anchored_workflow import part
from test_hours_graph import NOW, hours_part, inputs, quote
from test_local_mvp import compose

from telescope_rag.api.conversation import project_conversation
from telescope_rag.api.hours_presentation import project_hours_response
from telescope_rag.api.hours_responses import HoursChatResponse
from telescope_rag.graph.contracts import AnswerSentence, ConversationalDraft, ConversationalPart
from telescope_rag.graph.source_choices import SourceChoicePlannerPart, SourceChoicePlannerReply
from telescope_rag.knowledge.hours import DatedHours, PublishedHours
from telescope_rag.providers.contracts import StructuredResult

CASES = (
    ("ar-JO", "يوم الجمعة بتكونوا فاتحين؟", "نعم، بنفتح الجمعة من 14:00 إلى 24:00."),
    ("en", "Are you open on Monday?", "Yes, we're open Monday from 09:00 to midnight."),
    ("ar", "ما ساعات العمل؟", "يفتح المركز من 09:00 إلى 24:00، والجمعة من 14:00 إلى 24:00."),
)


async def exercise(
    monkeypatch,
    root,
    *,
    language="en",
    text="Are you open on Monday?",
    prose="Yes, we're open Monday from 09:00 to midnight.",
    failure=None,
    fixture_args=None,
    clock=None,
    mixed=False,
    local=False,
):
    app, provider, _ = compose(monkeypatch, root, fixture_args=fixture_args, clock=clock)
    workflow = app.state.offline_chat_service._workflow
    docs = {v: k for k, v in workflow._bindings.documents.items()}
    owners = {v: k for k, v in workflow._bindings.owners.items()}
    seen, runs = [], []
    original = workflow.run

    async def record(*args, **kwargs):
        run = await original(*args, **kwargs)
        runs.append(run)
        return run

    workflow.run = record
    segments = [text] + ([" Tell me about A.", " Book a private appointment."] if mixed else [])

    async def complete(messages, output_model, *, budget, **kwargs):
        body = json.loads(messages[-1].content)
        seen.append((body, budget))
        if output_model is SourceChoicePlannerReply:
            supplied = inputs(
                workflow,
                subject_text=text,
                kind="doctor" if failure == "missing" else "clinic",
                **(
                    {
                        "intent": "local",
                        "date_value": "2026-10-16",
                        "date_quote": quote("2026-10-16"),
                        "hour": 12 if failure != "ambiguous" else 2,
                        "minute": 0,
                        "clock_basis": "24h" if failure != "ambiguous" else "unspecified",
                        "time_quote": quote("at 12:00" if failure != "ambiguous" else "at 2"),
                    }
                    if local
                    else {}
                ),
            )
            proposed = [
                SourceChoicePlannerPart(
                    **hours_part(text, supplied).model_dump(),
                    clarification=None,
                )
            ]
            if mixed:
                proposed.append(
                    SourceChoicePlannerPart(
                        **part(
                            segments[1],
                            operation="read_source",
                            retrieval_query=None,
                            document_handles=(docs["main"],),
                            owner_handle=owners[("literal", "a")],
                        ).model_dump(),
                        hours=None,
                        clarification=None,
                    )
                )
                excluded = part(segments[2]).model_dump()
                excluded.update(
                    state="excluded", reason="Private actions excluded.", retrieval_query=None
                )
                proposed.append(SourceChoicePlannerPart(**excluded, hours=None, clarification=None))
            return StructuredResult(
                SourceChoicePlannerReply(language=language, parts=tuple(proposed)), ()
            )
        assert output_model is ConversationalDraft
        assert body["original_query"] == "".join(segments)
        proposed = []
        for i, p in enumerate(body["parts"]):
            if p["fixed_outcome"]:
                entry = ConversationalPart(part_id=p["part_id"], sentences=(), **p["fixed_outcome"])
            else:
                entry = ConversationalPart(
                    part_id=p["part_id"],
                    status="candidate",
                    reason_code=None,
                    sentences=(
                        AnswerSentence(
                            text=prose if i == 0 else "A works in the published field.",
                            chunk_ids=(p["eligible_quote_chunk_ids"][0],),
                        ),
                    ),
                )
            if i == 0:
                if failure == "borrow_sibling":
                    entry = entry.model_copy(
                        update={
                            "sentences": (
                                AnswerSentence(
                                    text=prose,
                                    chunk_ids=(body["parts"][1]["eligible_quote_chunk_ids"][0],),
                                ),
                            )
                        }
                    )
                elif failure in {"flip_outcome", "override_unknown"}:
                    entry = entry.model_copy(
                        update={
                            "status": "unknown" if entry.status == "candidate" else "candidate",
                            "reason_code": "not_found" if entry.status == "candidate" else None,
                        }
                    )
                elif failure == "no_sentence":
                    entry = entry.model_copy(update={"sentences": ()})
                elif failure == "fake_marker":
                    entry = entry.model_copy(
                        update={
                            "sentences": (
                                AnswerSentence(
                                    text=prose + " [C9.9]", chunk_ids=entry.sentences[0].chunk_ids
                                ),
                            )
                        }
                    )
            proposed.append(entry)
        return StructuredResult(ConversationalDraft(parts=tuple(proposed)), ())

    provider.complete = complete
    if failure == "missing_proof":
        assemble = workflow._catalog.assemble

        def omit(*args, **kwargs):
            return replace(assemble(*args, **kwargs), groups=())

        monkeypatch.setattr(workflow._catalog, "assemble", omit)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            response = await c.post(
                "/api/v1/chat", json={"query": "".join(segments), "language": "auto"}
            )
    assert len(seen) == 2, (runs[0].result.error_code, runs[0].stages)
    assert seen[0][1] is seen[1][1]
    return response, seen, runs[0], workflow


@pytest.mark.parametrize("language,text,prose", CASES)
def test_supported_hours_use_same_writer_and_keep_exact_sources(
    monkeypatch, tmp_path, language, text, prose
):
    response, seen, run, _ = asyncio.run(
        exercise(monkeypatch, tmp_path, language=language, text=text, prose=prose)
    )
    assert response.status_code == 200
    data = response.json()
    assert prose in data["answer"] and "Asia/Amman" not in data["answer"]
    assert "[C" not in data["answer"] and "[C" not in data["questions"][0]["answer"]
    hours = seen[1][0]["parts"][0]["validated_hours"]
    assert hours["status"] == "schedule_available" and hours["schedules"]
    assert len(data["citations"]) == 2 and all(
        c["quote"] not in data["answer"] for c in data["citations"]
    )
    assert data["questions"][0]["hours"]["status"] == "schedule_available"
    assert data["questions"][0]["hours"]["actual_attendance_verified"] is False
    assert run.result.parts[0].reason_code == "operation_unavailable"
    assert run.conversation.parts[0].status == "candidate"


def test_mixed_hours_doctor_and_excluded_parts_share_two_stages(monkeypatch, tmp_path):
    response, _, _, _ = asyncio.run(exercise(monkeypatch, tmp_path, mixed=True))
    assert response.status_code == 200
    data = response.json()
    assert [q["status"] for q in data["questions"]] == ["candidate", "candidate", "excluded"]
    assert data["questions"][0]["hours"] and data["questions"][1]["hours"] is None
    assert {
        c["literal_owner_id"]
        for c in data["citations"]
        if c["question_id"] == data["questions"][1]["id"]
    } == {"a"}
    assert len(data["unresolved_questions"]) == 1


@pytest.mark.parametrize(
    "failure", ["borrow_sibling", "flip_outcome", "no_sentence", "fake_marker"]
)
def test_writer_cannot_change_hours_outcome_or_borrow_sources(monkeypatch, tmp_path, failure):
    response, _, _, _ = asyncio.run(exercise(monkeypatch, tmp_path, mixed=True, failure=failure))
    assert response.status_code == 502 and "answer" not in response.json()


@pytest.mark.parametrize(
    "mode", ["stale", "conditional", "conflict", "missing", "missing_proof", "expired"]
)
def test_uncertain_hours_are_fixed_and_never_generated_as_facts(monkeypatch, tmp_path, mode):
    args, clock = {}, None
    if mode == "stale":

        def clock():
            return NOW + timedelta(days=8)
    elif mode == "conditional":
        args = {"record_changes": {"conditional": True}}
    elif mode == "expired":
        args = {"record_changes": {"valid_through": date(2026, 10, 15)}}
    elif mode == "conflict":
        from test_hours_graph import fixtures

        extra = fixtures()[2].schedules[0]
        args = {
            "extra_records": (
                PublishedHours(
                    **(
                        extra.model_dump()
                        | {
                            "record_id": "conflicting",
                            "weekly": tuple(
                                r.model_copy(update={"state": "closed", "intervals": ()})
                                for r in extra.weekly
                            ),
                        }
                    )
                ),
            )
        }
    response, seen, _, _ = asyncio.run(
        exercise(
            monkeypatch,
            tmp_path,
            fixture_args=args,
            clock=clock,
            failure=mode if mode in {"missing_proof", "missing"} else None,
        )
    )
    assert response.status_code == 200
    q = response.json()["questions"][0]
    assert q["status"] == "unknown"
    assert "[C" not in response.json()["answer"] and "[C" not in q["answer"]
    assert seen[1][0]["parts"][0]["fixed_outcome"]["status"] == "unknown"
    assert not seen[1][0]["parts"][0]["eligible_quote_chunk_ids"]


@pytest.mark.parametrize("ambiguous", [False, True])
def test_local_time_computation_is_authority_for_writer(monkeypatch, tmp_path, ambiguous):
    text = "Is the center open on 2026-10-16 at " + ("2?" if ambiguous else "12:00?")
    response, seen, _, _ = asyncio.run(
        exercise(
            monkeypatch,
            tmp_path,
            text=text,
            local=True,
            failure="ambiguous" if ambiguous else None,
            prose="That's outside the published Friday hours.",
        )
    )
    assert response.status_code == 200
    hours = seen[1][0]["parts"][0]["validated_hours"]
    q = response.json()["questions"][0]
    assert hours["status"] == q["hours"]["status"]
    if ambiguous:
        assert q["status"] == "clarification_required"
    else:
        assert hours["status"] == "outside_posted_hours" and q["status"] == "candidate"


def test_presenter_rechecks_computed_outcome_after_graph(monkeypatch, tmp_path):
    _, _, run, workflow = asyncio.run(exercise(monkeypatch, tmp_path))

    # A forged sidecar cannot turn a known hours result into an unknown answer.
    altered = run.conversation.parts[0].model_copy(
        update={"status": "unknown", "reason_code": "not_found", "sentences": ()}
    )
    run = replace(run, conversation=ConversationalDraft(parts=(altered,)))
    # Use the original independently projected response, before local wire stripping.
    baseline = project_hours_response(
        run,
        catalog=workflow.hours_bindings.catalog,
        request_id=UUID(hex=run.result.request_id),
        bindings=workflow.hours_bindings,
    )
    assert isinstance(baseline, HoursChatResponse)
    with pytest.raises(ValueError, match="conversation_outcome_mismatch"):
        project_conversation(baseline, run)


def test_writer_cannot_promote_stale_hours_to_answer(monkeypatch, tmp_path):
    response, _, _, _ = asyncio.run(
        exercise(
            monkeypatch, tmp_path, clock=lambda: NOW + timedelta(days=8), failure="override_unknown"
        )
    )
    assert response.status_code == 502 and "answer" not in response.json()


def test_general_schedule_does_not_apply_todays_exception_to_whole_week(monkeypatch, tmp_path):
    response, seen, _, _ = asyncio.run(
        exercise(
            monkeypatch,
            tmp_path,
            fixture_args={
                "record_changes": {
                    "exceptions": (DatedHours(on_date=date(2026, 10, 16), state="closed"),)
                }
            },
        )
    )
    assert response.status_code == 200
    hours = seen[1][0]["parts"][0]["validated_hours"]
    assert hours["status"] == "schedule_available"
    assert not hours["dated_exception_applied"] and hours["dated_exceptions_unverified"]
    assert hours["schedules"][0]["exceptions"][0]["on_date"] == "2026-10-16"
