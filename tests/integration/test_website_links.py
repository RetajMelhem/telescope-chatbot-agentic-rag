"""Authored website-link decisions; protocol tests, not model semantic acceptance."""

import asyncio
import hashlib
import json

import httpx2 as httpx
import pytest
from test_anchored_workflow import part
from test_hours_graph import NOW, fixtures
from test_local_mvp import compose

from telescope_rag.graph.contracts import (
    WebsiteAnswerSentence,
    WebsiteConversationalDraft,
    WebsiteConversationalPart,
)
from telescope_rag.graph.source_choices import SourceChoicePlannerPart, SourceChoicePlannerReply
from telescope_rag.ingestion.models import RawPage, stable_id
from telescope_rag.knowledge.public_links import (
    PublicLinksCatalog,
    WebsiteLink,
    WebsiteLinksPlan,
    links_digest,
)
from telescope_rag.providers.contracts import StructuredResult
from telescope_rag.providers.validation import output_schema
from telescope_rag.retrieval.assembly import RequestPart, SourceScope


def fixture_plan():
    html = '<footer><a href="https://www.facebook.com/synthetic-only">Facebook</a></footer>'
    page = RawPage(
        snapshot_id="synthetic",
        document_id="contact",
        canonical_url="https://telescopecenter.com/contact/",
        fetched_at=NOW,
        content_hash=hashlib.sha256(html.encode()).hexdigest(),
        html=html,
    )
    link = WebsiteLink(
        link_id=stable_id(
            "website-link-v1",
            page.document_id,
            page.content_hash,
            "footer > a",
            "Facebook",
            "https://www.facebook.com/synthetic-only",
        ),
        platform="Facebook",
        target_url="https://www.facebook.com/synthetic-only",
        literal_label="Facebook",
        source_url=page.canonical_url,
        document_id=page.document_id,
        snapshot_id=page.snapshot_id,
        fetched_at=page.fetched_at,
        source_content_hash=page.content_hash,
        source_language="en",
        locator="footer > a",
    )
    plan = WebsiteLinksPlan(base_prepared_digest=fixtures()[0].prepared_digest, links=(link,))
    return page, plan


def link_catalog():
    page, plan = fixture_plan()
    return PublicLinksCatalog(
        plan,
        expected_digest=links_digest(plan),
        base_prepared_digest=plan.base_prepared_digest,
        pages=(page,),
    )


def test_closed_website_schema_requires_every_property():
    assert output_schema(WebsiteConversationalDraft)["strict"]
    with pytest.raises(ValueError, match="sentence_requires_support"):
        WebsiteAnswerSentence(text="Unsupported.", chunk_ids=(), website_link_ids=())


@pytest.mark.parametrize("failure", ["digest", "base", "html", "href", "label", "duplicate"])
def test_source_proof_rejects_tampering(failure):
    page, plan = fixture_plan()
    if failure == "html":
        page = page.model_copy(update={"html": page.html + "changed"})
    if failure in {"href", "label"}:
        link = plan.links[0].model_dump()
        link["target_url" if failure == "href" else "literal_label"] += "changed"
        link["link_id"] = stable_id(
            "website-link-v1",
            link["document_id"],
            link["source_content_hash"],
            link["locator"],
            link["literal_label"],
            link["target_url"],
        )
        plan = plan.model_copy(update={"links": (WebsiteLink(**link),)})
    if failure == "duplicate":
        plan = plan.model_copy(update={"links": plan.links * 2})
    with pytest.raises(ValueError):
        PublicLinksCatalog(
            plan,
            expected_digest="wrong" if failure == "digest" else links_digest(plan),
            base_prepared_digest="wrong" if failure == "base" else plan.base_prepared_digest,
            pages=(page,),
        )


@pytest.mark.parametrize(
    "target",
    [
        "http://www.facebook.com/synthetic-only",
        "https://www.facebook.com.evil.test/synthetic-only",
        "https://user@www.facebook.com/synthetic-only",
        "https://www.facebook.com:443/synthetic-only",
        "https://www.facebook.com/synthetic-only?next=evil",
        "javascript:alert(1)",
        "https://www.facebook.com/",
    ],
)
def test_external_navigation_is_narrowly_validated(target):
    _, plan = fixture_plan()
    fields = plan.links[0].model_dump()
    fields.update(
        target_url=target,
        link_id=stable_id(
            "website-link-v1",
            fields["document_id"],
            fields["source_content_hash"],
            fields["locator"],
            fields["literal_label"],
            target,
        ),
    )
    with pytest.raises(ValueError):
        WebsiteLink(**fields)


@pytest.mark.parametrize(
    "changes,operation,expected",
    [
        ({}, "search", True),
        ({"scope": SourceScope(document_ids=("contact",), complete=True)}, "read_source", True),
        ({"scope": SourceScope(document_ids=("faq-ar",))}, "search", False),
        ({"scope": SourceScope(owner_id="a")}, "search", False),
        ({"scope": SourceScope(language="ar")}, "search", False),
        ({"scope": SourceScope(block_types=("faq",))}, "search", False),
        ({"intended_use": "doctor_role"}, "search", False),
        ({"state": "excluded", "reason": "private"}, "search", False),
        ({"state": "clarification_required", "reason": "ambiguous"}, "search", False),
        ({}, "time_comparison", False),
    ],
)
def test_link_capabilities_preserve_part_source_owner_and_operation(changes, operation, expected):
    value = RequestPart(part_id="p1", start=0, end=1, **changes)
    assert bool(link_catalog().eligible(value, operation)) is expected


async def exercise(monkeypatch, root, *, language="en", failure=None, unknown=False):
    links = link_catalog()
    app, provider, _ = compose(monkeypatch, root, website_links=links)
    segments = {
        "en": ["Do you have Facebook?", " Book a private appointment.", " Do you have TikTok?"],
        "ar": ["هل عندكم صفحة فيسبوك؟", " احجز موعدًا خاصًا.", " هل عندكم تيك توك؟"],
        "ar-JO": ["عندكم فيسبوك؟", " واحجزلي موعد خاص.", " وعندكم تيك توك؟"],
    }[language]
    calls, budgets = [], []

    async def complete(messages, output_model, *, budget, **kwargs):
        body = json.loads(messages[-1].content)
        calls.append(body)
        budgets.append(budget)
        if output_model is SourceChoicePlannerReply:
            proposed = []
            for i, text in enumerate(segments):
                fields = part(text).model_dump()
                if i == 1:
                    fields.update(state="excluded", reason="Private action.", retrieval_query=None)
                proposed.append(SourceChoicePlannerPart(**fields, hours=None, clarification=None))
            return StructuredResult(
                SourceChoicePlannerReply(language=language, parts=tuple(proposed)), ()
            )
        assert output_model is WebsiteConversationalDraft
        assert len(body["untrusted_website_links"]) == 1
        assert not body["parts"][1]["eligible_website_link_ids"]
        selected = body["parts"][0]["eligible_website_link_ids"]
        if failure == "unknown_id":
            selected = ["unissued"]
        elif failure == "duplicate_id":
            selected *= 2
        proposed = []
        for i, item in enumerate(body["parts"]):
            candidate = i == 0 and not unknown
            if failure == "override_excluded" and i == 1:
                candidate = True
            proposed.append(
                WebsiteConversationalPart(
                    part_id=item["part_id"],
                    status="candidate" if candidate else "excluded" if i == 1 else "unknown",
                    sentences=(
                        WebsiteAnswerSentence(
                            text="Yes, here is our Facebook page."
                            if language == "en"
                            else "نعم، عنا صفحة فيسبوك.",
                            chunk_ids=(),
                            website_link_ids=tuple(selected),
                        ),
                    )
                    if candidate
                    else (),
                    reason_code=None if candidate else "scope_excluded" if i == 1 else "not_found",
                )
            )
        return StructuredResult(WebsiteConversationalDraft(parts=tuple(proposed)), ())

    provider.complete = complete
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            result = await client.post("/api/v1/chat", json={"query": "".join(segments)})
    assert len(calls) == 2 and budgets[0] is budgets[1]
    return result, links


@pytest.mark.parametrize("language", ["en", "ar", "ar-JO"])
def test_social_link_answer_and_mixed_unknown_private_parts(monkeypatch, tmp_path, language):
    response, links = asyncio.run(exercise(monkeypatch, tmp_path, language=language))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "draft_ready"
    assert [p["status"] for p in data["questions"]] == ["candidate", "excluded", "unknown"]
    assert len(data["unresolved_questions"]) == 2
    assert not data["citations"]  # No fabricated vector-chunk quotation.
    assert len(data["website_links"]) == 1
    assert data["website_links_digest"] == links.digest
    assert data["website_links"][0]["question_id"] == data["questions"][0]["id"]
    assert data["website_links"][0]["target_url"] == next(iter(links.links.values())).target_url
    assert data["website_links"][0]["source_content_hash"]
    assert "[" not in data["answer"] and "https:" not in data["answer"]


@pytest.mark.parametrize("failure", ["unknown_id", "duplicate_id", "override_excluded"])
def test_invalid_link_citations_fail_closed_without_retry(monkeypatch, tmp_path, failure):
    response, _ = asyncio.run(exercise(monkeypatch, tmp_path, failure=failure))
    assert response.status_code == 502 and "answer" not in response.json()


def test_unrelated_or_unsupported_question_can_remain_unknown(monkeypatch, tmp_path):
    response, _ = asyncio.run(exercise(monkeypatch, tmp_path, unknown=True))
    assert response.status_code == 200
    assert not response.json()["website_links"]
    assert response.json()["questions"][0]["status"] == "unknown"


def test_normal_doctor_answer_with_supplement_keeps_owner_and_chunk_only_support(
    monkeypatch, tmp_path
):
    async def run():
        app, provider, _ = compose(monkeypatch, tmp_path, website_links=link_catalog())
        workflow = app.state.offline_chat_service._workflow
        bindings = workflow._bindings
        document = next(h for h, identity in bindings.documents.items() if identity == "main")
        owner = next(h for h, identity in bindings.owners.items() if identity == ("literal", "a"))

        async def complete(messages, output_model, **kwargs):
            body = json.loads(messages[-1].content)
            if output_model is SourceChoicePlannerReply:
                value = part(
                    body["original_query"],
                    operation="read_source",
                    retrieval_query=None,
                    document_handles=(document,),
                    owner_handle=owner,
                ).model_dump()
                return StructuredResult(
                    SourceChoicePlannerReply(
                        language="en",
                        parts=(SourceChoicePlannerPart(**value, hours=None, clarification=None),),
                    ),
                    (),
                )
            assert output_model is WebsiteConversationalDraft
            target = body["parts"][0]
            assert not target["eligible_website_link_ids"]
            return StructuredResult(
                WebsiteConversationalDraft(
                    parts=(
                        WebsiteConversationalPart(
                            part_id=target["part_id"],
                            status="candidate",
                            reason_code=None,
                            sentences=(
                                WebsiteAnswerSentence(
                                    text="A works in the stated field.",
                                    chunk_ids=(target["eligible_quote_chunk_ids"][0],),
                                    website_link_ids=(),
                                ),
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
                response = await client.post("/api/v1/chat", json={"query": "Tell me about A."})
        assert response.status_code == 200, response.text
        data = response.json()
        assert not data["website_links"]
        assert data["answer"] == "A works in the stated field."
        assert {c["literal_owner_id"] for c in data["citations"]} == {"a"}

    asyncio.run(run())
