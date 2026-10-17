"""Occurrence-scoped metadata and authored bilingual controls, not model accuracy tests."""

import asyncio
import json

import httpx2 as httpx
import pytest
from test_anchored_workflow import part, wire
from test_hours_graph import NOW, fixtures
from test_hours_service_profiles import ForbiddenChat, configuration, public_weekly
from test_offline_service import RecordingChat
from test_offline_workflow import FakeRetriever, SyntheticCounter, catalog, source
from test_source_scope_profile import fixtures as source_fixtures

from telescope_rag.api.hours_service import HoursChatService
from telescope_rag.api.main import create_app
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft
from telescope_rag.graph.hours_contract import ContractHoursPlannerPart, ContractHoursPlannerReply
from telescope_rag.knowledge.hours import hours_plan_digest
from telescope_rag.providers.openrouter import OpenRouterProviders

CODE = "name_only_profile_no_specialty_or_biography_claim"


def bindings_for(*items):
    original, _, authority = source_fixtures()
    evidence = catalog(*original, *items)
    return SourceBindings(
        evidence,
        include_block_types=True,
        purpose_contract=True,
        directory_authority=authority.model_copy(
            update={"prepared_digest": evidence.prepared_digest}
        ),
    )


def test_annotation_does_not_transfer_across_owner_document_language_or_block():
    flagged = source(
        100,
        "اسم تجريبي فقط",
        document="mixed",
        doctor_id="a",
        doctor_name="أ",
        canonical_doctor_id="confirmed-a",
        canonical_doctor_name="أ",
        source_issue_codes=(CODE,),
    ).model_copy(update={"language": "ar", "block_type": "doctor"})
    # Same owner/canonical person elsewhere and a different owner on the same page
    # do not inherit the limitation. Neither does another language/block on that page.
    other_page = flagged.model_copy(
        update={
            "chunk_id": "other-page",
            "document_id": "informative",
            "point_id": "00000000-0000-0000-0000-000000000101",
            "canonical_url": "https://telescopecenter.com/synthetic-informative/",
            "source_issue_codes": (),
        }
    )
    other_owner = source(102, document="mixed", doctor_id="b", doctor_name="ب")
    other_language = source(103, document="mixed", doctor_id="a", doctor_name="أ")
    other_block = source(104, document="mixed", doctor_id="a", doctor_name="أ").model_copy(
        update={"language": "ar", "block_type": "faq"}
    )
    b = bindings_for(flagged, other_page, other_owner, other_language, other_block)
    original = b.manifest_json
    annotated = json.loads(b.with_reviewed_profile_limitations())
    view = annotated.pop("reviewed_profile_limitations")
    assert json.dumps(annotated, ensure_ascii=False) == original == b.manifest_json
    assert view["issue_code"] == CODE
    assert len(view["occurrences"]) == 1
    row = view["occurrences"][0]
    assert row["chunk_id"] == flagged.chunk_id
    assert b.documents[row["document_handle"]] == "mixed"
    assert b.owners[row["literal_owner_handle"]] == ("literal", "a")
    assert b.owners[row["canonical_owner_handle"]] == ("canonical", "confirmed-a")
    assert row["source_language"] == "ar" and row["block_type"] == "doctor"
    # Returning a new value prevents one request's mutations contaminating others.
    row["literal_owner_handle"] = "tampered"
    assert "tampered" not in b.with_reviewed_profile_limitations()


def test_flag_presence_is_literal_not_inferred_from_name_text_or_another_issue():
    name_only_without_review = source(100, "A name only.", doctor_id="a", doctor_name="A")
    unrelated_flag = source(101, "A", source_issue_codes=("synthetic-other-issue",))
    # Null owner is preserved, never assigned from neighboring labels.
    unowned = source(102, "Reviewed label.", source_issue_codes=(CODE,))
    b = bindings_for(name_only_without_review, unrelated_flag, unowned)
    rows = json.loads(b.with_reviewed_profile_limitations())["reviewed_profile_limitations"][
        "occurrences"
    ]
    assert len(rows) == 1 and rows[0]["chunk_id"] == unowned.chunk_id
    assert rows[0]["literal_owner_handle"] is rows[0]["canonical_owner_handle"] is None


@pytest.mark.parametrize("authority,contract", [(False, True), (True, False), (False, False)])
def test_view_requires_existing_source_contract_and_reviewed_authority(authority, contract):
    _, evidence, reviewed = source_fixtures()
    b = SourceBindings(
        evidence, directory_authority=reviewed if authority else None, purpose_contract=contract
    )
    with pytest.raises(ValueError, match="^profile_limitations_require_source_contract$"):
        b.with_reviewed_profile_limitations()


def test_large_view_respects_existing_manifest_bound_without_truncating_or_mutating():
    items = tuple(
        source(100 + n, "A", document="same", source_issue_codes=(CODE,)) for n in range(600)
    )
    b = bindings_for(*items)
    before = b.manifest_json
    with pytest.raises(ValueError, match="^planner_source_manifest_exceeds_bound$"):
        b.with_reviewed_profile_limitations()
    assert b.manifest_json == before


def composition(chat, *, enabled=False, profile="contracts_v14", language="en", config=None):
    evidence, authority, plan, _ = fixtures()
    items = list(evidence.chunks.values())
    sparse = source(
        100,
        "Synthetic A" if language == "en" else "الطبيب أ",
        document="sparse-profile",
        doctor_id="a",
        doctor_name="Synthetic A" if language == "en" else "الطبيب أ",
        source_issue_codes=(CODE,),
    ).model_copy(update={"language": language, "block_type": "doctor"})
    informative = source(
        101,
        "Synthetic B: explicit training; scope limited to this source."
        if language == "en"
        else "الطبيب ب: تدريب مذكور صراحة؛ النطاق محدود بهذا المصدر.",
        document="informative-profile",
        doctor_id="b",
        doctor_name="Synthetic B" if language == "en" else "الطبيب ب",
    ).model_copy(update={"language": language, "block_type": "doctor"})
    evidence = catalog(*items, sparse, informative)
    plan = plan.model_copy(update={"prepared_digest": evidence.prepared_digest})
    authority = authority.model_copy(update={"prepared_digest": evidence.prepared_digest})
    retriever = FakeRetriever(lambda i, q: ())
    service = HoursChatService(
        settings=config or configuration(),
        chat=chat,
        retriever=retriever,
        catalog=evidence,
        counter=SyntheticCounter(),
        directory_authority=authority,
        hours_plan=plan,
        expected_hours_plan_digest=hours_plan_digest(plan),
        token_basis="synthetic_test",
        clock=lambda: NOW,
        hours_profile=profile,
        reviewed_profile_limitations=enabled,
    )
    return service, retriever, sparse, informative


@pytest.mark.parametrize(
    "profile,enabled",
    [("v12", True), ("identity_links_v13", True), ("contracts_v14", 1), ("contracts_v14", "true")],
)
def test_invalid_trusted_options_fail_before_provider_dispatch(profile, enabled):
    with pytest.raises(ValueError, match="^profile_limitations_require_contracts_v14$"):
        composition(ForbiddenChat(), profile=profile, enabled=enabled)


TEXTS = {
    "en": {
        "general_roles": "Compare the published roles of A and B, keeping their owners separate.",
        "profile_only": "Use only A's profile to give A's specialty; do not use the directory.",
        "informative": "What training does B's profile explicitly publish?",
        "literal_name": "Quote the name on A's profile only.",
    },
    "ar": {
        "general_roles": "قارن الأدوار المنشورة للطبيب أ والطبيب ب، وافصل بينهما.",
        "profile_only": "استخدم ملف الطبيب أ فقط لذكر تخصصه؛ لا تستخدم دليل الأطباء.",
        "informative": "ما التدريب المذكور صراحة في ملف الطبيب ب؟",
        "literal_name": "انقل الاسم في ملف الطبيب أ فقط.",
    },
    "ar-JO": {
        "general_roles": "قارن الأدوار المكتوبة للدكتور أ والدكتور ب، وخلي كل واحد لحاله.",
        "profile_only": "بس من صفحة الدكتور أ احكي تخصصه؛ ما تستخدم دليل الدكاترة.",
        "informative": "شو التدريب المكتوب بصفحة الدكتور ب؟",
        "literal_name": "انقل الاسم من صفحة الدكتور أ بس.",
    },
}


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("language", TEXTS)
@pytest.mark.parametrize("kind", TEXTS["en"])
def test_authored_http_controls_preserve_profile_restrictions_and_positive_sources(
    enabled, language, kind
):
    async def run():
        config, seen = configuration(), []
        text = TEXTS[language][kind]
        selected = []

        def handler(request):
            payload = json.loads(request.read())
            body = json.loads(payload["messages"][-1]["content"])
            seen.append(payload)
            w = service._workflow
            if "max_parts" in body:
                manifest = body["source_manifest"]
                assert ("reviewed_profile_limitations" in manifest) is enabled
                assert (
                    payload["response_format"]["json_schema"]["name"] == "ContractHoursPlannerReply"
                )
                assert "reasoning" not in payload and payload["max_completion_tokens"] == 1000
                doc = (
                    "main"
                    if kind == "general_roles"
                    else "informative-profile"
                    if kind == "informative"
                    else "sparse-profile"
                )
                handle = next(h for h, d in w._bindings.documents.items() if d == doc)
                selected.extend(c for c in w._catalog.chunks.values() if c.document_id == doc)
                # This is an authored choice, never an asserted model decision.
                proposal = ContractHoursPlannerPart(
                    **part(
                        text,
                        operation="read_source",
                        retrieval_query=None,
                        document_handles=(handle,),
                        block_types=("doctor",),
                        intended_use="doctor_role"
                        if kind in {"general_roles", "profile_only"}
                        else "profile_detail"
                        if kind == "informative"
                        else "general_excerpt",
                        constraint_quotes=(text,) if kind == "profile_only" else (),
                    ).model_dump(),
                    hours=None,
                )
                return wire(ContractHoursPlannerReply(language=language, parts=(proposal,)))
            # The view changes the planner input only; the draft retains its old manifest.
            assert "reviewed_profile_limitations" not in body["source_manifest"]
            assert body["parts"][0]["eligible_quote_chunk_ids"] == [c.chunk_id for c in selected]
            return wire(
                AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=body["parts"][0]["part_id"],
                            status="candidate",
                            quotes=tuple(
                                QuoteDraft(chunk_id=c.chunk_id, quote=c.retrieval_text)
                                for c in selected
                            ),
                            reason_code=None,
                        ),
                    )
                )
            )

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            chat = RecordingChat(providers.chat)
            service, retriever, _, _ = composition(
                chat, enabled=enabled, language="en" if language == "en" else "ar", config=config
            )
            app = create_app(config, offline_chat_service=service, offline_response_format="hours")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/chat",
                    json={"query": text, "language": "en" if language == "en" else "ar"},
                )
        assert response.status_code == 200, response.text
        question = response.json()["questions"][0]
        assert question["question"] == text and not retriever.calls
        assert len(chat.calls) == len(seen) == (1 if kind == "profile_only" else 2)
        assert all(b is chat.calls[0][1] for _, b in chat.calls)
        citations = response.json()["citations"]
        if kind == "profile_only":
            assert question["status"] == "unknown" and not citations
            assert question["reason_code"] == "context_only"
        else:
            assert question["status"] == "candidate"
            assert {c["chunk_id"] for c in citations} == {c.chunk_id for c in selected}
            assert len(citations) == (2 if kind == "general_roles" else 1)
            assert {c["literal_owner_id"] for c in citations} == {c.doctor_id for c in selected}
            assert all(c["question_id"] == question["id"] for c in citations)
        assert not response.json()["semantic_grounding_verified"]

    asyncio.run(run())


def test_public_request_cannot_enable_the_view_and_default_api_stays_closed():
    async def run():
        config = configuration()
        service, retriever, _, _ = composition(ForbiddenChat(), enabled=True, config=config)
        app = create_app(config, offline_chat_service=service, offline_response_format="hours")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/chat", json={"query": "Synthetic?", "reviewed_profile_limitations": True}
            )
            assert response.status_code == 422
            assert (await client.get("/health/ready")).status_code == 503
        assert not retriever.calls
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_app(config)), base_url="http://test"
        ) as client:
            assert (
                await client.post("/api/v1/chat", json={"query": "Synthetic?"})
            ).status_code == 503

    asyncio.run(run())


def test_concurrent_opt_in_and_control_services_keep_manifests_and_budgets_separate():
    async def run():
        config, seen, services = configuration(), [], {}
        both_entered = asyncio.Event()

        async def handler(request):
            body = json.loads(json.loads(request.read())["messages"][-1]["content"])
            enabled = "reviewed_profile_limitations" in body["source_manifest"]
            seen.append(enabled)
            if len(seen) == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=2)
            proposed = public_weekly(services[enabled])
            return wire(ContractHoursPlannerReply.model_validate_json(proposed.model_dump_json()))

        async with OpenRouterProviders(config, transport=httpx.MockTransport(handler)) as providers:
            chat = RecordingChat(providers.chat)
            clients = []
            for enabled in (False, True):
                services[enabled], _, _, _ = composition(chat, enabled=enabled, config=config)
                app = create_app(
                    config, offline_chat_service=services[enabled], offline_response_format="hours"
                )
                clients.append(
                    httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")
                )
            try:
                responses = await asyncio.gather(
                    *(
                        c.post("/api/v1/chat", json={"query": "When does the center open?"})
                        for c in clients
                    )
                )
            finally:
                for client in clients:
                    await client.aclose()
        assert all(r.status_code == 200 for r in responses)
        assert set(seen) == {False, True} and len(seen) == 2
        assert len({r.json()["request_id"] for r in responses}) == 2
        assert len(chat.calls) == 2 and chat.calls[0][1] is not chat.calls[1][1]

    asyncio.run(run())
