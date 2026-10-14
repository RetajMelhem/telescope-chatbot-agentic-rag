"""Cleaning and exact reuse must preserve facts and every occurrence's provenance."""

import unicodedata
from datetime import UTC, datetime

import pytest

from telescope_rag.ingestion.deduplication import draft_input_plan, embedding_input_key
from telescope_rag.ingestion.extraction import extract_page, normalize_text
from telescope_rag.ingestion.models import RawPage, stable_id
from telescope_rag.ingestion.preparation import prepare_document


def prepare(html: str):
    return prepare_document(
        extract_page(
            RawPage(
                snapshot_id="synthetic-quality",
                document_id="synthetic-quality-doc",
                canonical_url="https://telescopecenter.com/synthetic-quality/",
                fetched_at=datetime(2026, 10, 15, tzinfo=UTC),
                content_hash=stable_id(html),
                html=html,
            )
        )
    )


def test_presentation_marks_normalize_without_folding_arabic_or_joiners():
    original = "\u061c\u200fلا تُقدِّم\u200e العلاج\u200b يوم الجمعة ١٠ صباحًا."
    assert normalize_text(original) == unicodedata.normalize(
        "NFC", "لا تُقدِّم العلاج يوم الجمعة ١٠ صباحًا."
    )
    assert normalize_text("أ إ آ ا ة ه ى ي س\u200cلام س\u200dلام") == (
        "أ إ آ ا ة ه ى ي س\u200cلام س\u200dلام"
    )
    result = prepare(f"<main><p>{original}</p></main>")
    assert result.chunks[0].source_spans[0].original_text == original
    assert result.chunks[0].retrieval_text == normalize_text(original)


@pytest.mark.parametrize(
    "label",
    [
        "Telescope Medical Center Logo White",
        "Telescope Medical Center Logo Color",
        "Telescope Medical Center CTA",
        "Telescope Image",
        "testimonial cover image",
        "transparent eye image",
        "company logo 1",
        "header-smile-pro-1.jpg",
    ],
)
def test_decorative_or_filename_alt_is_excluded_but_adjacent_facts_survive(label):
    result = prepare(
        f"<main><h1>Public services</h1><img alt='{label}'><p>Published clinic fact.</p></main>"
    )
    assert all(label not in c.retrieval_text for c in result.chunks)
    assert any("Published clinic fact." in c.retrieval_text for c in result.chunks)
    assert any(r.code in {"decorative_image", "image_asset_filename"} for r in result.removed)


@pytest.mark.parametrize(
    "label", ["Health 360°", "MSH MENA", "ATM 1", "No-Shave Technique_converted"]
)
def test_meaningful_alt_with_numbers_or_asset_suffix_is_not_guessed_or_erased(label):
    result = prepare(f"<main><h1>Public information</h1><img alt='{label}'></main>")
    assert any(label in c.retrieval_text for c in result.chunks)
    assert any(
        s.attribute == "alt" and s.original_text == label
        for c in result.chunks
        for s in c.source_spans
    )


def test_footer_uses_its_own_scope_and_metadata_retains_page_title():
    result = prepare(
        "<html><head><title>Dr. Example Profile</title></head><body><main>"
        "<h1>Dr. Example</h1><p>Profile fact.</p></main><footer>"
        "<h2>Clinic phone</h2><p>+962 6 000 0000</p></footer></body></html>"
    )
    footer = [c for c in result.chunks if "+962" in c.retrieval_text]
    assert footer and all(c.doctor_id is None for c in footer)
    assert all("Dr. Example" not in c.retrieval_text for c in footer)
    assert all(c.page_title == "Dr. Example Profile" for c in footer)


def test_exact_reuse_retains_all_occurrences_and_separates_owner_language_and_qualifiers():
    base = prepare("<main><p>Published service.</p></main>").chunks[0]
    same = base.model_copy(
        update={"chunk_id": "second", "canonical_url": "https://telescopecenter.com/other/"}
    )
    different = [
        base.model_copy(update={"chunk_id": "owner-one", "doctor_id": "one"}),
        base.model_copy(update={"chunk_id": "owner-two", "doctor_id": "two"}),
        base.model_copy(update={"chunk_id": "language", "language": "ar"}),
        base.model_copy(
            update={"chunk_id": "qualifier", "retrieval_text": "Published service, except Fridays."}
        ),
    ]
    plan = draft_input_plan([base, same, *different], "bound-digest")
    assert plan["prepared_digest"] == "bound-digest"
    assert plan["occurrence_count"] == 6 and plan["unique_input_count"] == 5
    assert plan["inputs"][0]["occurrence_chunk_ids"] == [base.chunk_id, "second"]
    assert {i for group in plan["inputs"] for i in group["occurrence_chunk_ids"]} == {
        base.chunk_id,
        "second",
        *(c.chunk_id for c in different),
    }
    assert embedding_input_key(base, "config-one") != embedding_input_key(base, "config-two")
    with pytest.raises(ValueError, match="duplicate_chunk_occurrence"):
        draft_input_plan([base, base], "digest")
