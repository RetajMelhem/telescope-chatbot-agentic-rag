"""Authored plans through the actual graph/adapter; no measured model understanding or live I/O."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_anchored_workflow import part, wire
from test_offline_service import RecordingChat
from test_offline_workflow import FakeRetriever, SyntheticCounter, catalog, source
from test_public_hours import reference, rules

from telescope_rag.api.hours_presentation import project_hours_response
from telescope_rag.api.hours_service import HoursChatService
from telescope_rag.api.main import create_app
from telescope_rag.core.settings import Settings
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.contracts import (
    AnswerDraft,
    HistoryTurn,
    PartDraft,
    QuoteDraft,
    WorkflowRequest,
)
from telescope_rag.graph.hours_inputs import HoursPlannerPart, HoursPlannerReply
from telescope_rag.graph.hours_records import HoursFieldQuote, HoursInput
from telescope_rag.graph.hours_workflow import HoursRagWorkflow
from telescope_rag.knowledge.hours import (
    DatedHours,
    HoursInterval,
    HoursQuery,
    HoursSubject,
    PublicHoursPlan,
    PublishedHours,
    WeeklyHours,
    hours_plan_digest,
)
from telescope_rag.knowledge.source_authority import DirectoryAuthority
from telescope_rag.providers.openrouter import OpenRouterProviders

NOW = datetime(2026, 10, 16, 16, tzinfo=UTC)
REQUEST_ID = UUID(int=700)
OPENING = (
    ("en", "When does the center open?", "the center"),
    ("en", "What are the center's opening hours?", "the center"),
    ("ar", "متى يفتح المركز؟", "المركز"),
    ("ar-JO", "إيمتى بيفتح المركز؟", "المركز"),
)


def fixtures(*, record_changes=None, extra_records=(), duplicate=False):
    main = source(
        1,
        "Synthetic doctor A; same field as B.",
        document="main",
        doctor_id="a",
        doctor_name="Synthetic A",
    ).model_copy(update={"block_type": "doctor"})
    other = source(
        2,
        "Synthetic doctor B; same field as A.",
        document="main",
        doctor_id="b",
        doctor_name="Synthetic B",
    ).model_copy(update={"block_type": "doctor"})
    english = source(
        3,
        "Synthetic center and optics: 09:00 to ending midnight, "
        "Friday 14:00 to ending midnight. Pharmacy 24/7; advance booking recommended.",
        document="faq-en",
    ).model_copy(update={"block_type": "faq"})
    arabic = source(
        4,
        english.retrieval_text
        if duplicate
        else "نص تجريبي: المركز والبصريات من التاسعة حتى نهاية اليوم، الجمعة من الثانية. "
        "الصيدلية طوال اليوم؛ الحجز المسبق موصى به.",
        document="faq-ar",
    ).model_copy(update={"language": "en" if duplicate else "ar", "block_type": "faq"})
    contact = source(5, "Synthetic contact label.", document="contact")
    english = english.model_copy(update={"fetched_at": datetime(2026, 10, 14, tzinfo=UTC)})
    arabic = arabic.model_copy(update={"fetched_at": datetime(2026, 10, 14, tzinfo=UTC)})
    evidence = catalog(main, other, english, arabic, contact)
    authority = DirectoryAuthority(
        prepared_digest=evidence.prepared_digest,
        admission_policy_hash="synthetic-policy",
        primary_directory_document_ids=("main",),
    )
    records = tuple(
        PublishedHours(
            **(
                dict(
                    record_id=f"synthetic-{kind}-{item.language}-{i}",
                    subject=HoursSubject(kind=kind, id="synthetic-" + kind),
                    weekly=rules(always=kind == "pharmacy"),
                    evidence=(reference(item),),
                )
                | (record_changes or {})
            )
        )
        for i, item in enumerate((english, arabic))
        for kind in ("clinic", "optical_center", "pharmacy")
    )
    plan = PublicHoursPlan(
        prepared_digest=evidence.prepared_digest,
        snapshot_id=english.snapshot_id,
        schedules=records + extra_records,
        review_note="Synthetic authored mapping; not website knowledge.",
    )
    return evidence, authority, plan, contact


def quote(text, *, origin="part", history_index=None):
    return HoursFieldQuote(quote=text, origin=origin, history_index=history_index)


def inputs(workflow, *, kind="clinic", subject_text="the center", intent="schedule", **changes):
    handle = next(h for h, s in workflow.hours_bindings.subjects.items() if s.kind == kind)
    return HoursInput(
        **(
            dict(
                intent=intent,
                subject_handle=handle,
                subject_quote=quote(subject_text),
                date_value=None,
                date_quote=None,
                hour=None,
                minute=None,
                clock_basis=None,
                time_quote=None,
            )
            | changes
        )
    )


def hours_part(text, supplied, **changes):
    old = part(text, operation="time_comparison", retrieval_query=None, **changes)
    return HoursPlannerPart(**old.model_dump(), hours=supplied)


def ordinary(text, **changes):
    return HoursPlannerPart(**part(text, **changes).model_dump(), hours=None)


async def execute(
    request, propose, *, settings_changes=None, fixture_args=None, clock=None, plan_transform=None
):
    config = Settings(
        _env_file=None,
        app_env="test",
        openrouter_api_key="synthetic-only",
        **(settings_changes or {}),
    )
    evidence, authority, plan, contact = fixtures(**(fixture_args or {}))
    if plan_transform:
        plan = plan_transform(plan)
    seen = []
    retriever = FakeRetriever(lambda i, q: (contact.chunk_id,))

    def handler(request):
        payload = json.loads(request.read())
        body = json.loads(payload["messages"][-1]["content"])
        seen.append((payload, body))
        if "max_parts" in body:
            value = propose(workflow, body)
        else:
            value = AnswerDraft(
                parts=tuple(
                    PartDraft(
                        part_id=p["part_id"],
                        status="candidate"
                        if p["eligible_quote_chunk_ids"]
                        else p["state"]
                        if p["state"] != "public"
                        else "unknown",
                        quotes=(
                            QuoteDraft(chunk_id=contact.chunk_id, quote=contact.retrieval_text),
                        )
                        if p["eligible_quote_chunk_ids"]
                        else (),
                        reason_code=None
                        if p["eligible_quote_chunk_ids"]
                        else "scope_excluded"
                        if p["state"] == "excluded"
                        else "ambiguous_request"
                        if p["state"] == "clarification_required"
                        else "operation_unavailable",
                    )
                    for p in body["parts"]
                )
            )
        return wire(value)

    async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
        chat = RecordingChat(providers.chat)
        workflow = HoursRagWorkflow(
            settings=config,
            chat=chat,
            retriever=retriever,
            catalog=evidence,
            counter=SyntheticCounter(),
            directory_authority=authority,
            hours_plan=plan,
            expected_hours_plan_digest=hours_plan_digest(plan),
            token_basis="synthetic_test",
            clock=clock or (lambda: NOW),
        )
        run = await workflow.run(request, request_id=REQUEST_ID)
    return workflow, run, seen, retriever, chat.calls


def project(workflow, run):
    return project_hours_response(
        run, catalog=workflow._catalog, request_id=REQUEST_ID, bindings=workflow.hours_bindings
    )


@pytest.mark.parametrize("language,text,subject", OPENING)
def test_general_opening_questions_need_no_date_time_or_clarification(language, text, subject):
    def proposal(w, body):
        return HoursPlannerReply(
            language=language, parts=(hours_part(text, inputs(w, subject_text=subject)),)
        )

    workflow, run, seen, retriever, calls = asyncio.run(
        execute(WorkflowRequest(query=text), proposal)
    )
    response = project(workflow, run)
    q = response.questions[0]
    assert q.question == text and q.status == "candidate" and q.hours.status == "schedule_available"
    assert q.hours.local_candidates == () and q.hours.intent == "schedule"
    assert "09:00" in q.answer and "14:00" in q.answer and "24:00" in q.answer
    assert ("Friday" if language == "en" else "الجمعة") in q.answer
    assert len(q.hours.schedules) == len(response.citations) == 2
    assert response.citations[0].quote.endswith("advance booking recommended.")
    assert {c.source_language for c in response.citations} == {"en", "ar"}
    assert response.offline_only and not response.semantic_grounding_verified
    assert not q.hours.query_interpretation_verified and not q.hours.actual_attendance_verified
    assert (
        run.result.parts[0].reason_code == "operation_unavailable"
    )  # Earlier draft wire unchanged.
    assert len(seen) == len(calls) == 1 and not retriever.calls
    assert run.usage.logical_embedding_calls == 0 and run.usage.logical_chat_calls == 1
    body = seen[0][1]
    assert body["prompt_version"] == "offline-rag-planner-hours-v12"
    assert body["server_clock"] == {"now_utc": NOW.isoformat(), "timezone": "Asia/Amman"}
    assert body["original_query"] == text and "reasoning" not in seen[0][0]
    assert seen[0][0]["response_format"]["json_schema"]["name"] == "HoursPlannerReply"


@pytest.mark.parametrize(
    "basis,hour,status",
    [
        ("unspecified", 7, "clarification_required"),
        ("am", 7, "outside_posted_hours"),
        ("pm", 7, "within_posted_hours"),
        ("24h", 14, "within_posted_hours"),
        ("24h", 0, "outside_posted_hours"),
        ("unspecified", 12, "outside_posted_hours"),
    ],
)
def test_specific_times_preserve_explicit_inputs_and_am_pm_ambiguity(basis, hour, status):
    text = f"Is the center open on 2026-10-16 at {hour}:00 ({basis})?"

    def proposal(w, body):
        return HoursPlannerReply(
            language="en",
            parts=(
                hours_part(
                    text,
                    inputs(
                        w,
                        intent="local",
                        date_value="2026-10-16",
                        date_quote=quote("2026-10-16"),
                        hour=hour,
                        minute=0,
                        clock_basis=basis,
                        time_quote=quote(f"{hour}:00 ({basis})"),
                    ),
                ),
            ),
        )

    workflow, run, *_ = asyncio.run(execute(WorkflowRequest(query=text), proposal))
    response = project(workflow, run)
    summary = response.questions[0].hours
    assert summary.status == status and len(response.citations) == 2
    assert summary.clock_ambiguous == (basis == "unspecified")
    assert len(summary.local_candidates) == (2 if basis == "unspecified" else 1)
    assert summary.dated_exceptions_unverified
    assert run.computed_hours[0].field_bindings[-1].quote == f"{hour}:00 ({basis})"


@pytest.mark.parametrize("kind,reason", [(None, "ambiguous_subject"), ("doctor", "missing_hours")])
def test_missing_subject_and_doctor_schedule_cannot_inherit_center_hours(kind, reason):
    text = "When does the center open?" if kind is None else "When does Synthetic A work?"

    def proposal(w, body):
        supplied = inputs(
            w, kind=kind or "clinic", subject_text="the center" if kind is None else "Synthetic A"
        )
        if kind is None:
            supplied = supplied.model_copy(update={"subject_handle": None, "subject_quote": None})
        return HoursPlannerReply(language="en", parts=(hours_part(text, supplied),))

    workflow, run, *_ = asyncio.run(execute(WorkflowRequest(query=text), proposal))
    response = project(workflow, run)
    assert response.questions[0].hours.reason == reason and not response.citations
    assert response.questions[0].status == ("clarification_required" if kind is None else "unknown")


def test_now_uses_one_captured_authoritative_clock():
    text, clocks = "Is the center open now?", []

    def clock():
        clocks.append(NOW)
        return NOW

    def proposal(w, body):
        return HoursPlannerReply(
            language="en",
            parts=(hours_part(text, inputs(w, intent="now", time_quote=quote("now"))),),
        )

    workflow, run, *_ = asyncio.run(execute(WorkflowRequest(query=text), proposal, clock=clock))
    summary = project(workflow, run).questions[0].hours
    assert clocks == [NOW] and run.operation_clock == NOW
    assert summary.status == "within_posted_hours" and summary.local_candidates[0].hour == 19


@pytest.mark.parametrize("mode", ["history", "query_reference", "missing_date"])
def test_literal_references_and_dates_remain_request_owned(mode):
    prefix = "For the center, on 2026-10-16, do not book anything."
    question = " Is the center open Friday at 7?" if mode == "missing_date" else " Is it open at 7?"
    text = question if mode != "query_reference" else prefix + question
    request = WorkflowRequest(
        query=text, history=(HistoryTurn(role="user", content=prefix),) if mode == "history" else ()
    )

    def proposal(w, body):
        origin = "history" if mode == "history" else "query_reference"
        supplied = inputs(
            w,
            intent="local",
            subject_text="the center",
            hour=7,
            minute=0,
            clock_basis="unspecified",
            time_quote=quote("7"),
            subject_quote=quote(
                "the center", origin=origin, history_index=0 if mode == "history" else None
            ),
            date_value=None if mode == "missing_date" else "2026-10-16",
            date_quote=None
            if mode == "missing_date"
            else quote("2026-10-16", origin=origin, history_index=0 if mode == "history" else None),
        )
        if mode == "missing_date":
            supplied = supplied.model_copy(
                update={"subject_quote": quote("the center"), "date_quote": quote("Friday")}
            )
        parts = (
            hours_part(
                question,
                supplied,
                reference_text=prefix if mode != "missing_date" else None,
                history_indices=(0,) if mode == "history" else (),
            ),
        )
        if mode == "query_reference":
            parts = (
                ordinary(
                    prefix,
                    state="excluded",
                    retrieval_query=None,
                    reason="Context/prohibition, no action.",
                ),
            ) + parts
        return HoursPlannerReply(language="en", parts=parts)

    workflow, run, *_ = asyncio.run(execute(request, proposal))
    summary = project(workflow, run).questions[-1].hours
    assert summary.reason == ("missing_date" if mode == "missing_date" else "ambiguous_time")
    assert run.request == request
    if mode != "missing_date":
        binding = run.computed_hours[0].field_bindings[0]
        assert binding.origin == mode and binding.quote == "the center"


@pytest.mark.parametrize("restriction", ["document", "block", "language", "owner"])
def test_exact_scope_exclusion_never_falls_back_to_other_hours_sources(restriction):
    text = "When does the center open?"

    def proposal(w, body):
        docs = {v: k for k, v in w._bindings.documents.items()}
        changes = (
            {"document_handles": (docs["contact"],)}
            if restriction == "document"
            else {"block_types": ("section",)}
            if restriction == "block"
            else {"source_language": "und"}
            if restriction == "language"
            else {"owner_handle": next(iter(w._bindings.owners))}
        )
        return HoursPlannerReply(language="en", parts=(hours_part(text, inputs(w), **changes),))

    workflow, run, seen, retriever, *_ = asyncio.run(execute(WorkflowRequest(query=text), proposal))
    if restriction == "owner":
        # An impossible declared source filter or contradictory subject is refused before retrieval.
        assert run.result.outcome == "failed" and len(seen) == 1 and not retriever.calls
    else:
        response = project(workflow, run)
        assert response.questions[0].hours.reason == "missing_hours" and not response.citations


@pytest.mark.parametrize(
    "bad",
    [
        "handle",
        "anchor",
        "repeated",
        "history",
        "date",
        "scope_use",
        "ordinary_hours",
        "missing_hours",
    ],
)
def test_invalid_inputs_fail_before_any_retrieval_or_second_chat(bad):
    text = "When does the center open?" + (" the center" if bad == "repeated" else "")

    def proposal(w, body):
        supplied = inputs(w)
        if bad == "handle":
            supplied = supplied.model_copy(update={"subject_handle": "fabricated"})
        if bad == "anchor":
            supplied = supplied.model_copy(update={"subject_quote": quote("unasked doctor")})
        if bad == "history":
            supplied = supplied.model_copy(
                update={"subject_quote": quote("the center", origin="history", history_index=0)}
            )
        if bad == "date":
            supplied = inputs(
                w,
                intent="local",
                date_value="2026-99-99",
                date_quote=quote("the center"),
                hour=7,
                minute=0,
                clock_basis="pm",
                time_quote=quote("open"),
            )
        value = hours_part(
            text, supplied, intended_use="doctor_role" if bad == "scope_use" else "general_excerpt"
        )
        if bad == "ordinary_hours":
            value = value.model_copy(update={"operation": "search", "retrieval_query": text})
        if bad == "missing_hours":
            value = value.model_copy(update={"hours": None})
        return HoursPlannerReply(language="en", parts=(value,))

    _, run, seen, retriever, *_ = asyncio.run(execute(WorkflowRequest(query=text), proposal))
    assert run.result.outcome == "failed" and len(seen) == 1 and not retriever.calls


@pytest.mark.parametrize("mode", ["budget", "coalesced"])
def test_unoffered_or_hidden_source_proof_does_not_establish_a_time_answer(mode):
    text = "When does the center open?"

    def proposal(w, body):
        return HoursPlannerReply(language="en", parts=(hours_part(text, inputs(w)),))

    workflow, run, *_ = asyncio.run(
        execute(
            WorkflowRequest(query=text),
            proposal,
            settings_changes={"max_evidence_tokens": 1200} if mode == "budget" else None,
            fixture_args={"duplicate": mode == "coalesced"},
        )
    )
    response = project(workflow, run)
    assert response.questions[0].hours.reason == "scope_incomplete"
    assert not response.citations and not response.questions[0].hours.schedules


@pytest.mark.parametrize(
    "tamper", ["clock", "assessment", "fields", "missing", "duplicate", "subject"]
)
def test_hours_projection_independently_rebinds_computation_and_literal_receipts(tamper):
    text = "When does the center open?"

    def proposal(w, body):
        return HoursPlannerReply(language="en", parts=(hours_part(text, inputs(w)),))

    workflow, run, *_ = asyncio.run(execute(WorkflowRequest(query=text), proposal))
    record = run.computed_hours[0]
    if tamper == "clock":
        run = replace(run, operation_clock=NOW + timedelta(minutes=1))
    elif tamper == "missing":
        run = replace(run, computed_hours=())
    elif tamper == "duplicate":
        run = replace(run, computed_hours=(record, record))
    else:
        changed = (
            replace(
                record, assessment=record.assessment.model_copy(update={"reason": "missing_hours"})
            )
            if tamper == "assessment"
            else replace(record, field_bindings=())
            if tamper == "fields"
            else replace(record, query=record.query.model_copy(update={"subject": None}))
        )
        run = replace(run, computed_hours=(changed,))
    with pytest.raises(ValueError, match="offline_hours_response_invalid"):
        project(workflow, run)


@pytest.mark.parametrize("language", ["en", "ar", "ar-JO"])
def test_mixed_public_hours_source_private_and_ambiguous_parts_share_one_budget(language):
    texts = (
        (
            "When does the center open?",
            " Show the contact label.",
            " Book a private appointment.",
            " Which of these doctors?",
        )
        if language == "en"
        else ("متى يفتح المركز؟", " انقل نص التواصل.", " احجز موعداً خاصاً.", " أي من هؤلاء الأطباء؟")
    )
    text = "".join(texts)

    def proposal(w, body):
        docs = {v: k for k, v in w._bindings.documents.items()}
        return HoursPlannerReply(
            language=language,
            parts=(
                hours_part(
                    texts[0], inputs(w, subject_text="the center" if language == "en" else "المركز")
                ),
                ordinary(texts[1], document_handles=(docs["contact"],)),
                ordinary(
                    texts[2],
                    state="excluded",
                    retrieval_query=None,
                    reason="Private booking excluded.",
                ),
                ordinary(
                    texts[3],
                    state="clarification_required",
                    retrieval_query=None,
                    reason="Unresolved identity.",
                ),
            ),
        )

    workflow, run, seen, retriever, calls = asyncio.run(
        execute(WorkflowRequest(query=text), proposal)
    )
    response = project(workflow, run)
    assert tuple(q.question for q in response.questions) == texts
    assert tuple(q.status for q in response.questions) == (
        "candidate",
        "candidate",
        "excluded",
        "clarification_required",
    )
    assert len(seen) == 2 and calls[0][1] is calls[1][1]
    assert run.usage.logical_chat_calls == 2 and len(retriever.calls) == 1
    assert response.citations[-1].question_id == response.questions[0].id  # Separate owners/parts.
    assert all(q.hours is None for q in response.questions[1:])


def test_hours_schema_is_closed_required_and_old_schema_is_unchanged():
    schema = HoursPlannerReply.model_json_schema()
    for value in [schema, *schema["$defs"].values()]:
        if value.get("type") == "object":
            assert value["additionalProperties"] is False
            assert set(value["required"]) == set(value["properties"])
    assert "HoursInput" not in AnchoredPlannerReply.model_json_schema()["$defs"]


@pytest.mark.parametrize(
    "changes",
    [
        {"hour": 9},
        {"date_value": "2026-10-16"},
        {"time_quote": quote("now")},
        {"clock_basis": "am"},
    ],
)
def test_general_schedule_shape_rejects_unrequested_time_inputs(changes):
    with pytest.raises(ValidationError):
        HoursInput(
            intent="schedule",
            subject_handle=None,
            subject_quote=None,
            **(
                dict(
                    date_value=None,
                    date_quote=None,
                    hour=None,
                    minute=None,
                    clock_basis=None,
                    time_quote=None,
                )
                | changes
            ),
        )


@pytest.mark.parametrize("when", [datetime(2026, 10, 16), "2026-10-16"])
def test_invalid_authoritative_clock_is_refused_without_provider_dispatch(when):
    _, run, seen, *_ = asyncio.run(
        execute(WorkflowRequest(query="Open now?"), lambda w, b: None, clock=lambda: when)
    )
    assert run.result.outcome == "failed" and not seen


def test_schedule_listing_can_show_partial_week_without_filling_missing_days():
    async def run_test():
        text = "When does the center open?"

        def proposal(w, body):
            return HoursPlannerReply(language="en", parts=(hours_part(text, inputs(w)),))

        # The Friday server clock must not turn a Monday-only listing into a failed comparison.
        workflow, run, *_ = await execute(WorkflowRequest(query=text), proposal)
        plan = workflow.hours_bindings.plan
        monday = (
            WeeklyHours(
                weekday=0, state="intervals", intervals=(HoursInterval(opens=540, closes=1020),)
            ),
        )
        modified = plan.model_copy(
            update={
                "schedules": tuple(r.model_copy(update={"weekly": monday}) for r in plan.schedules)
            }
        )
        config = workflow._settings
        async with OpenRouterProviders(
            config, transport=httpx.MockTransport(lambda req: wire(proposal(new, {})))
        ) as providers:
            new = HoursRagWorkflow(
                settings=config,
                chat=providers.chat,
                retriever=FakeRetriever(lambda i, q: ()),
                catalog=workflow._catalog,
                counter=SyntheticCounter(),
                directory_authority=workflow._bindings.directory_authority,
                hours_plan=modified,
                expected_hours_plan_digest=hours_plan_digest(modified),
                token_basis="synthetic_test",
                clock=lambda: NOW,
            )
            result = await new.run(WorkflowRequest(query=text), request_id=REQUEST_ID)
        response = project(new, result)
        assert response.questions[0].hours.status == "schedule_available"
        assert (
            "Monday: 09:00" in response.answer
            and "Unlisted days remain unknown." in response.answer
        )

    asyncio.run(run_test())


def test_explicit_nonproduction_http_hours_format_and_default_service_boundaries():
    evidence, authority, plan, _ = fixtures()
    config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
    seen = []

    def handler(request):
        seen.append(json.loads(request.read()))
        return wire(
            HoursPlannerReply(
                language="en",
                parts=(hours_part("When does the center open?", inputs(service._workflow)),),
            )
        )

    async def run_test():
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            nonlocal service
            service = HoursChatService(
                settings=config,
                chat=providers.chat,
                retriever=FakeRetriever(lambda i, q: ()),
                catalog=evidence,
                counter=SyntheticCounter(),
                directory_authority=authority,
                hours_plan=plan,
                expected_hours_plan_digest=hours_plan_digest(plan),
                token_basis="synthetic_test",
                clock=lambda: NOW,
            )
            for mode in ("draft", "rendered"):
                with pytest.raises(ValueError, match="offline_response_configuration_invalid"):
                    create_app(config, offline_chat_service=service, offline_response_format=mode)
            app = create_app(config, offline_chat_service=service, offline_response_format="hours")
            with TestClient(app) as http:
                response = http.post("/api/v1/chat", json={"query": "When does the center open?"})
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["schema_version"] == "offline-hours-response-v1"
                assert body["questions"][0]["hours"]["status"] == "schedule_available"
                assert body["request_id"] == response.headers["X-Request-ID"]
                assert http.get("/health/ready").status_code == 503
                schema = http.get("/openapi.json").json()
                assert schema["paths"]["/api/v1/chat"]["post"]["responses"]["200"]["content"][
                    "application/json"
                ]["schema"]["$ref"].endswith("HoursChatResponse")
            with pytest.raises(ValueError, match="offline_chat_configuration_mismatch"):
                service.check_configuration(config.model_copy(update={"app_env": "production"}))
        with TestClient(create_app(config)) as http:
            assert (
                http.post("/api/v1/chat", json={"query": "When does the center open?"}).status_code
                == 503
            )
        with pytest.raises(ValueError):
            create_app(config, offline_response_format="hours")

    service = None
    asyncio.run(run_test())
    assert len(seen) == 1


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"conditional": True}, "conditional_hours"),
        ({"valid_from": date(2026, 10, 17)}, "outside_effective_dates"),
        ({"valid_through": date(2026, 10, 15)}, "outside_effective_dates"),
    ],
)
def test_schedule_qualifiers_cannot_be_dropped_to_obtain_an_answer(changes, reason):
    text = "When does the center open?"

    def proposal(w, body):
        return HoursPlannerReply(language="en", parts=(hours_part(text, inputs(w)),))

    workflow, run, *_ = asyncio.run(
        execute(WorkflowRequest(query=text), proposal, fixture_args={"record_changes": changes})
    )
    summary = project(workflow, run).questions[0].hours
    assert summary.status == "unknown" and summary.reason == reason
    assert len(summary.schedules) == 2


@pytest.mark.parametrize(
    "server_clock,reason",
    [
        (NOW + timedelta(days=8), "stale_hours"),
        (NOW - timedelta(days=3), "source_from_future"),
    ],
)
def test_schedule_listing_uses_existing_source_freshness_policy(server_clock, reason):
    text = "When does the center open?"

    def proposal(w, body):
        return HoursPlannerReply(language="en", parts=(hours_part(text, inputs(w)),))

    workflow, run, *_ = asyncio.run(
        execute(WorkflowRequest(query=text), proposal, clock=lambda: server_clock)
    )
    summary = project(workflow, run).questions[0].hours
    assert summary.status == "unknown" and summary.reason == reason


def test_disagreeing_weekly_rules_remain_unresolved_even_when_now_outcomes_agree():
    text = "When does the center open?"

    def proposal(w, body):
        return HoursPlannerReply(language="en", parts=(hours_part(text, inputs(w)),))

    def conflicting(plan):
        first, *rest = plan.schedules
        return plan.model_copy(
            update={
                "schedules": (
                    first.model_copy(update={"weekly": rules(hours=((600, 1440),))}),
                    *rest,
                )
            }
        )

    workflow, run, *_ = asyncio.run(
        execute(WorkflowRequest(query=text), proposal, plan_transform=conflicting)
    )
    assert run.computed_hours[0].assessment.status == "within_posted_hours"
    response = project(workflow, run)
    assert response.questions[0].hours.reason == "conflicting_hours"
    assert response.questions[0].status == "unknown" and len(response.citations) == 2
    assert response.questions[0].hours.schedules[0].weekly[0].intervals[0].opens == 600
    assert response.questions[0].hours.schedules[1].weekly[0].intervals[0].opens == 540


@pytest.mark.parametrize(
    "kind,subject",
    [("clinic", "the center"), ("optical_center", "the optics"), ("pharmacy", "the pharmacy")],
)
def test_separate_facilities_have_separate_handles_records_and_results(kind, subject):
    text = f"When does {subject} open?"

    def proposal(w, body):
        return HoursPlannerReply(
            language="en", parts=(hours_part(text, inputs(w, kind=kind, subject_text=subject)),)
        )

    workflow, run, *_ = asyncio.run(execute(WorkflowRequest(query=text), proposal))
    response = project(workflow, run)
    assert response.questions[0].hours.subject.kind == kind
    assert all(r.subject.kind == kind for r in response.questions[0].hours.schedules)
    assert ("00:00" in response.answer) == (kind == "pharmacy")
    assert ("14:00" in response.answer) == (kind != "pharmacy")


@pytest.mark.parametrize("source_language", ["en", "ar"])
def test_source_language_restrictions_select_exact_separate_claims(source_language):
    text = "When does the center open?"

    def proposal(w, body):
        return HoursPlannerReply(
            language="en", parts=(hours_part(text, inputs(w), source_language=source_language),)
        )

    workflow, run, *_ = asyncio.run(execute(WorkflowRequest(query=text), proposal))
    response = project(workflow, run)
    assert len(response.citations) == len(response.questions[0].hours.schedules) == 1
    assert response.citations[0].source_language == source_language


@pytest.mark.parametrize(
    "language,text,subject,negative",
    [
        (
            "en",
            "When does the center open? Do not book anything.",
            "the center",
            "Do not book anything",
        ),
        ("ar", "متى يفتح المركز؟ لا تحجز أي موعد.", "المركز", "لا تحجز أي موعد"),
        ("ar-JO", "إيمتى بيفتح المركز؟ ما تحجزلي موعد.", "المركز", "ما تحجزلي موعد"),
    ],
)
def test_negations_remain_literal_constraints_without_becoming_booking_actions(
    language, text, subject, negative
):
    def proposal(w, body):
        return HoursPlannerReply(
            language=language,
            parts=(
                hours_part(text, inputs(w, subject_text=subject), constraint_quotes=(negative,)),
            ),
        )

    workflow, run, seen, retriever, *_ = asyncio.run(execute(WorkflowRequest(query=text), proposal))
    assert run.request_anchors[0].constraints[0].quote == negative
    assert project(workflow, run).questions[0].question == text
    assert len(seen) == 1 and not retriever.calls


@pytest.mark.parametrize("selection", [(), ("unissued",), ["unissued"], ([],), (True,)])
def test_record_selection_never_falls_back_and_refuses_invalid_ids(selection):
    text = "When does the center open?"

    def proposal(w, body):
        return HoursPlannerReply(language="en", parts=(hours_part(text, inputs(w)),))

    workflow, run, *_ = asyncio.run(execute(WorkflowRequest(query=text), proposal))
    engine = workflow.hours_bindings.engine
    subject = run.computed_hours[0].query.subject
    if selection == ():
        assert len(engine.records_for(subject)) == 2
        assert engine.records_for(subject, record_ids=()) == ()
        assert (
            engine.evaluate(HoursQuery(subject=subject, mode="now"), now=NOW, record_ids=()).reason
            == "missing_hours"
        )
    else:
        with pytest.raises(ValueError, match="hours_record_selection_invalid"):
            engine.records_for(subject, record_ids=selection)


def test_listing_renders_reviewed_split_shifts_overnight_dated_rules_and_validity():
    text = "When does the center open?"

    def proposal(w, body):
        return HoursPlannerReply(language="en", parts=(hours_part(text, inputs(w)),))

    changes = {
        "weekly": rules(hours=((540, 720), (840, 1560))),
        "exceptions": (DatedHours(on_date=date(2026, 10, 18), state="closed"),),
        "valid_from": date(2026, 10, 14),
        "valid_through": date(2026, 10, 20),
    }
    workflow, run, *_ = asyncio.run(
        execute(WorkflowRequest(query=text), proposal, fixture_args={"record_changes": changes})
    )
    response = project(workflow, run)
    assert response.questions[0].hours.status == "schedule_available"
    for value in (
        "09:00",
        "12:00",
        "14:00",
        "02:00 (next day)",
        "2026-10-18: Published as closed",
        "Valid from: 2026-10-14",
        "Valid through: 2026-10-20",
    ):
        assert value in response.answer


@pytest.mark.parametrize("mode", ["provider", "cancellation", "production"])
def test_refusal_and_cancellation_have_no_fallback_dispatch(mode):
    async def run_test():
        evidence, authority, plan, _ = fixtures()
        config = Settings(
            _env_file=None,
            app_env="production" if mode == "production" else "test",
            openrouter_api_key="synthetic-only",
            qdrant_api_key="synthetic-read-only",
        )
        attempts = []
        entered = asyncio.Event()

        async def handler(request):
            attempts.append(1)
            if mode == "cancellation":
                entered.set()
                await asyncio.Event().wait()
            return httpx.Response(401, json={"error": {"message": "SYNTHETIC-SECRET-REJECTED"}})

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:

            def construct():
                return HoursRagWorkflow(
                    settings=config,
                    chat=providers.chat,
                    retriever=FakeRetriever(lambda i, q: ()),
                    catalog=evidence,
                    counter=SyntheticCounter(),
                    directory_authority=authority,
                    hours_plan=plan,
                    expected_hours_plan_digest=hours_plan_digest(plan),
                    token_basis="synthetic_test",
                    clock=lambda: NOW,
                )

            if mode == "production":
                with pytest.raises(ValueError):
                    construct()
                assert not attempts
            elif mode == "cancellation":
                task = asyncio.create_task(construct().run(WorkflowRequest(query="Open now?")))
                await asyncio.wait_for(entered.wait(), timeout=2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert len(attempts) == 1
            else:
                run = await construct().run(WorkflowRequest(query="Open now?"))
                assert len(attempts) == 1 and run.result.error_code == "provider_failed"
                assert "SYNTHETIC-SECRET" not in repr(run)

    asyncio.run(run_test())


def test_concurrent_hours_requests_keep_clocks_subjects_scopes_and_budgets_separate():
    async def run_test():
        evidence, authority, plan, _ = fixtures()
        config = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        cases = {
            "When does the center open?": ("clinic", "the center", "en"),
            "متى تفتح الصيدلية؟": ("pharmacy", "الصيدلية", "ar"),
        }
        planned, ready = [], asyncio.Event()

        async def handler(request):
            body = json.loads(json.loads(request.read())["messages"][-1]["content"])
            text = body["original_query"]
            kind, subject, language = cases[text]
            planned.append(text)
            if len(planned) == 2:
                ready.set()
            await ready.wait()
            return wire(
                HoursPlannerReply(
                    language=language,
                    parts=(
                        hours_part(
                            text, inputs(service._workflow, kind=kind, subject_text=subject)
                        ),
                    ),
                )
            )

        clocks = iter((NOW, NOW + timedelta(minutes=1)))
        retriever = FakeRetriever(lambda i, q: ())
        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            chat = RecordingChat(providers.chat)
            service = HoursChatService(
                settings=config,
                chat=chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                directory_authority=authority,
                hours_plan=plan,
                expected_hours_plan_digest=hours_plan_digest(plan),
                token_basis="synthetic_test",
                clock=lambda: next(clocks),
            )
            app = create_app(config, offline_chat_service=service, offline_response_format="hours")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                replies = await asyncio.gather(
                    *(client.post("/api/v1/chat", json={"query": text}) for text in cases)
                )
        values = [r.json() for r in replies]
        assert all(r.status_code == 200 for r in replies)
        assert (
            len({v["request_id"] for v in values})
            == len({v["questions"][0]["id"] for v in values})
            == 2
        )
        assert chat.calls[0][1] is not chat.calls[1][1] and not retriever.calls
        assert {v["questions"][0]["hours"]["evaluated_at"] for v in values} == {
            NOW.isoformat().replace("+00:00", "Z"),
            (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        }
        for text, value in zip(cases, values, strict=True):
            kind, _, language = cases[text]
            question = value["questions"][0]
            assert question["question"] == text and question["hours"]["subject"]["kind"] == kind
            assert value["language"] == language
            assert all(c["question_id"] == question["id"] for c in value["citations"])

    asyncio.run(run_test())


def test_two_facility_questions_share_source_proof_without_merging_their_schedules():
    first, second = "When does the center open?", " And when does the pharmacy open?"

    def proposal(w, body):
        return HoursPlannerReply(
            language="en",
            parts=(
                hours_part(first, inputs(w)),
                hours_part(second, inputs(w, kind="pharmacy", subject_text="the pharmacy")),
            ),
        )

    workflow, run, seen, retriever, *_ = asyncio.run(
        execute(
            WorkflowRequest(query=first + second),
            proposal,
        )
    )
    response = project(workflow, run)
    assert len(seen) == 1 and not retriever.calls and len(run.evidence.groups) == 2
    assert tuple(q.question for q in response.questions) == (first, second)
    assert "14:00" in response.questions[0].answer and "00:00" in response.questions[1].answer
    assert tuple(q.hours.subject.kind for q in response.questions) == ("clinic", "pharmacy")
    assert len({c.id for c in response.citations}) == 4
    for question in response.questions:
        assert len(question.citation_ids) == 2
        assert all(
            c.question_id == question.id
            for c in response.citations
            if c.id in question.citation_ids
        )
