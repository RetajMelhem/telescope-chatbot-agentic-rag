"""Synthetic source fixtures verify relationship and provenance preservation."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from telescope_rag.ingestion.extraction import extract_page, normalize_text
from telescope_rag.ingestion.models import RawPage, stable_id
from telescope_rag.ingestion.preparation import prepare_document
from telescope_rag.providers.contracts import EmbeddingFormat

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingestion"


class SyntheticCounter:
    """Fixture-only count; never a production tokenizer or compatibility assertion."""

    model = "qwen/qwen3-embedding-8b"
    version = "synthetic-word-units-v1"
    verified = True

    def __init__(self):
        self.inputs = []

    def count(self, text):
        self.inputs.append(text)
        return len(text.split())


def test_oversized_icon_condition_group_repeats_governing_and_closing_source_context():
    html = (
        "<main><section class='e-con'><div class='e-con'><h2>Conditions</h2>"
        "<div>May apply only if:</div></div><div class='e-con'>"
        + "".join(
            f"<div class='e-con'><div class='elementor-icon-box-content'><h3>"
            f"Condition {n} with complete literal qualifier "
            "and several source words.</h3></div></div>"
            for n in range(5)
        )
        + "</div><div>Assessment remains necessary.</div></section></main>"
    )
    result = prepare_document(
        extract_page(page(html)),
        max_tokens=30,
        counter=SyntheticCounter(),
        embedding_format=format_profile(),
    )
    assert len(result.chunks) > 1 and not result.gaps
    assert all(c.token_count <= 30 for c in result.chunks)
    assert all(
        "May apply only if:" in c.retrieval_text
        and "Assessment remains necessary." in c.retrieval_text
        for c in result.chunks
    )
    assert all(
        any(s.original_text == "Assessment remains necessary." for s in c.context_spans)
        for c in result.chunks
    )


def page(html):
    return RawPage(
        snapshot_id="synthetic-snapshot",
        document_id="synthetic-document",
        canonical_url="https://telescopecenter.com/synthetic-fixture/",
        fetched_at=datetime(2026, 10, 14, tzinfo=UTC),
        content_hash=stable_id(html),
        html=html,
    )


def format_profile(prefix=""):
    return EmbeddingFormat(
        version="synthetic-fixture-format-v1", verified=True, document_prefix=prefix
    )


def prepare(html, *, max_tokens=1200, prefix=""):
    return prepare_document(
        extract_page(page(html)),
        max_tokens=max_tokens,
        counter=SyntheticCounter(),
        embedding_format=format_profile(prefix),
    )


def codes(items):
    return {item.code for item in items}


def test_doctors_are_isolated_by_literal_profile_and_main_boundaries():
    doc = extract_page(page((FIXTURES / "structured.html").read_text(encoding="utf-8")))
    doctors = [unit for unit in doc.units if unit.kind == "doctor"]
    assert [doctor.doctor_name for doctor in doctors] == [
        "Prof. Dr. Example One",
        "Dr. Example Two",
        "الدكتورة مثال",
    ]
    assert len({doctor.doctor_id for doctor in doctors}) == 3
    assert "Does not offer" in doctors[0].segments[0].text
    assert "only after assessment" in doctors[1].segments[0].text
    assert normalize_text("لا تُقدِّم") in doctors[2].segments[0].text
    assert doctors[2].language == "ar"
    generic = next(
        unit for unit in doc.units if any("Generic clinic" in s.text for s in unit.segments)
    )
    assert generic.doctor_id is None
    assert all("Unrelated mega navigation" not in s.text for u in doc.units for s in u.segments)
    assert any(
        unit.kind == "contact" and "Friday contact desk" in " ".join(s.text for s in unit.segments)
        for unit in doc.units
    )


def test_removals_are_audited_without_dropping_meaningful_footer():
    doc = extract_page(page((FIXTURES / "structured.html").read_text(encoding="utf-8")))
    assert {
        "executable_content",
        "navigation",
        "form_submission_content",
        "patient_testimonial",
        "placeholder_content",
    } <= codes(doc.removed)
    text = " ".join(s.text for unit in doc.units for s in unit.segments)
    assert "private entry" not in text
    assert "Patient Person" not in text
    assert "Lorem ipsum" not in text
    assert "Public contact: 000-000" in text
    assert doc.page.html == (FIXTURES / "structured.html").read_text(encoding="utf-8")


def test_closed_faq_keeps_question_and_all_answer_components():
    doc = extract_page(page((FIXTURES / "structured.html").read_text(encoding="utf-8")))
    faqs = [unit for unit in doc.units if unit.kind == "faq"]
    assert len(faqs) == 2
    assert "What are the working hours?" in [s.text for s in faqs[0].context]
    assert [s.text for s in faqs[0].segments] == [
        "Clinic hours:",
        "Friday 10 AM–2 PM.",
        "Except public holidays.",
    ]
    assert faqs[0].doctor_id is None
    assert "لا، هذه الخدمة غير متوفرة." == faqs[1].segments[0].text


def test_table_format_preserves_labels_rows_caption_and_footnote_provenance():
    doc = prepare((FIXTURES / "structured.html").read_text(encoding="utf-8"))
    table = next(chunk for chunk in doc.chunks if chunk.block_type == "table")
    assert "Day: Friday; Hours: 10 AM–2 PM" in table.retrieval_text
    assert "Day: Saturday; Hours: Closed" in table.retrieval_text
    assert "Public hours" in table.retrieval_text
    assert "Hours exclude public holidays." in table.retrieval_text
    assert len(table.source_spans) == 6  # each row and its independently mapped cells
    context_text = " ".join(s.original_text[s.start : s.end] for s in table.context_spans)
    assert "Day" in context_text and "Hours" in context_text
    assert "Hours exclude public holidays." in context_text


@pytest.mark.parametrize(
    "html, expected",
    [
        (
            "<main><table><tr><th colspan='2'>Hours</th></tr>"
            "<tr><td>A</td><td>B</td></tr></table></main>",
            "ambiguous_table_span",
        ),
        ("<main><table><tr><td>A</td><td>B</td></tr></table></main>", "table_headers_unresolved"),
        (
            "<main><table><tr><th>A</th><th>B</th></tr><tr><td>Only one</td></tr></table></main>",
            "table_row_width_mismatch",
        ),
        ("<main><details><summary>Question?</summary></details></main>", "faq_pair_incomplete"),
        ("<main><ol reversed><li>A</li></ol></main>", "list_numbering_unresolved"),
        ("<main><ol><li value='5'>A</li></ol></main>", "list_numbering_unresolved"),
    ],
)
def test_ambiguous_structure_is_quarantined_with_visible_gap(html, expected):
    doc = prepare(html)
    assert expected in codes(doc.gaps)
    assert doc.chunks == ()
    assert not doc.embedding_ready


def test_no_token_guess_or_implicit_format_verification():
    extracted = extract_page(page("<main><h1>Hours</h1><p>Friday 10 AM.</p></main>"))
    draft = prepare_document(extracted)
    assert len(draft.chunks) == 1
    assert draft.chunks[0].token_count is None
    assert not draft.chunks[0].embedding_ready
    assert {"token_count_unavailable", "embedding_format_unverified"} <= codes(draft.gaps)
    counted_draft = prepare_document(extracted, counter=SyntheticCounter())
    assert counted_draft.chunks[0].token_count is not None
    assert not counted_draft.embedding_ready


def test_full_input_including_context_and_prefix_is_counted_and_versioned():
    extracted = extract_page(
        page("<title>Clinic</title><main><h1>Information</h1><p>Public fact.</p></main>")
    )
    counter = SyntheticCounter()
    profile = format_profile("DOCUMENT instruction: ")
    result = prepare_document(extracted, counter=counter, embedding_format=profile)
    assert result.embedding_ready
    chunk = result.chunks[0]
    assert counter.inputs == ["DOCUMENT instruction: " + chunk.retrieval_text]
    assert chunk.token_count == len(counter.inputs[0].split())
    assert chunk.embedding_format_version == profile.version
    assert chunk.embedding_format_hash == stable_id(
        "embedding-format-v1", profile.model_dump_json()
    )
    assert not chunk.retrieval_text.startswith(
        "DOCUMENT instruction:"
    )  # adapter applies it exactly once


def test_format_prefix_conflict_is_rejected():
    with pytest.raises(ValueError, match="conflicts"):
        prepare_document(
            extract_page(page("<p>A fact.</p>")),
            document_prefix="A",
            embedding_format=format_profile("B"),
        )


def test_complete_small_faqs_are_not_padded_or_combined():
    result = prepare(
        "<main><details><summary>First?</summary><p>Yes.</p></details><details><summary>Second?</summary><p>No.</p></details></main>"
    )
    assert len(result.chunks) == 2
    assert [chunk.token_count for chunk in result.chunks] == [2, 2]
    assert "Second?" not in result.chunks[0].retrieval_text


def test_overflow_splits_complete_paragraphs_with_repeated_owner_and_context():
    result = prepare(
        "<main><h1>Team</h1><div class='doctor-card'><h4>Dr. Example</h4>"
        "<p>First complete paragraph has several words.</p>"
        "<p>Second complete paragraph has several words.</p></div></main>",
        max_tokens=10,
    )
    assert len(result.chunks) == 2
    assert result.embedding_ready
    assert len({chunk.parent_block_id for chunk in result.chunks}) == 1
    assert len({chunk.doctor_id for chunk in result.chunks}) == 1
    assert all(
        chunk.token_count <= 10 and "Dr. Example" in chunk.retrieval_text for chunk in result.chunks
    )
    assert "Second" not in result.chunks[0].retrieval_text
    assert "First" not in result.chunks[1].retrieval_text


def test_oversized_faq_sentences_retain_question_and_exact_extracted_offsets():
    result = prepare(
        "<main><details><summary>Working hours?</summary>"
        "<p>Friday closes early. Saturday opens late. Sunday is closed.</p></details></main>",
        max_tokens=6,
    )
    assert len(result.chunks) == 3
    assert all("Working hours?" in chunk.retrieval_text for chunk in result.chunks)
    original = "Friday closes early. Saturday opens late. Sunday is closed."
    assert (
        "".join(
            span.original_text[span.start : span.end]
            for chunk in result.chunks
            for span in chunk.source_spans
        )
        == original
    )
    assert all(chunk.source_spans[0].original_text == original for chunk in result.chunks)
    assert all(chunk.token_count <= 6 for chunk in result.chunks)


def test_qualifying_sentence_is_not_detached_when_overflow_would_lose_exception():
    result = prepare(
        "<main><p>Clinic is open every Friday. Except public holidays.</p></main>", max_tokens=5
    )
    assert result.chunks == ()
    assert "indivisible_unit_overflow" in codes(result.gaps)


def test_context_itself_too_large_never_emits_oversize_or_empty_children():
    result = prepare(
        "<main><details><summary>This question context itself has many words?</summary>"
        "<p>Yes.</p></details></main>",
        max_tokens=3,
    )
    assert result.chunks == ()
    assert "indivisible_unit_overflow" in codes(result.gaps)


def test_large_table_splits_rows_and_repeats_labels_and_notes():
    html = (
        "<main><table><caption>Hours</caption><tr><th>Day</th><th>Hours</th></tr>"
        "<tr><td>Friday</td><td>Closed</td></tr><tr><td>Saturday</td><td>Closed</td></tr>"
        "<tfoot><tr><td>Except holidays.</td><td>Ask reception.</td></tr></tfoot></table></main>"
    )
    result = prepare(html, max_tokens=12)
    assert len(result.chunks) == 2
    assert all(
        "Except holidays." in chunk.retrieval_text and "Day:" in chunk.retrieval_text
        for chunk in result.chunks
    )
    assert "Saturday" not in result.chunks[0].retrieval_text
    assert all(chunk.token_count <= 12 for chunk in result.chunks)


def test_indivisible_table_row_is_quarantined_without_arbitrary_cut():
    result = prepare(
        "<main><table><tr><th>Condition</th><th>Restriction</th></tr><tr><td>Example</td>"
        "<td>Do not perform this procedure except after a complete medical assessment.</td>"
        "</tr></table></main>",
        max_tokens=7,
    )
    assert result.chunks == ()
    assert "indivisible_unit_overflow" in codes(result.gaps)


def test_original_occurrences_and_duplicate_names_are_not_collapsed():
    html = (
        "<main><div class='doctor-card'><h4>Dr. Same</h4><p>Identical description.</p></div>"
        "<div class='doctor-card'><h4>Dr. Same</h4><p>Identical description.</p></div></main>"
    )
    first = prepare(html)
    second = prepare(html)
    assert len(first.chunks) == 2
    assert first == second
    assert len({c.doctor_id for c in first.chunks}) == 2
    assert len({c.point_id for c in first.chunks}) == 2
    assert all(UUID(c.point_id).version == 5 for c in first.chunks)
    assert first.chunks[0].source_spans[0].locator != first.chunks[1].source_spans[0].locator


def test_multiple_doctor_list_items_preserve_each_owner():
    doc = extract_page(
        page(
            "<main><ul><li><strong>Dr. One</strong> Founder.</li>"
            "<li><strong>Dr. Two</strong> Specialist.</li></ul></main>"
        )
    )
    assert [unit.doctor_name for unit in doc.units] == ["Dr. One", "Dr. Two"]
    assert all(unit.kind == "doctor" for unit in doc.units)
    assert doc.units[0].doctor_id != doc.units[1].doctor_id


def test_conservative_normalization_preserves_arabic_and_original_spans():
    original = "  لا\u00a0 تُقدِّم\n العلاج  يوم الجمعة ١٠ صباحًا.  "
    doc = prepare("<main><p>" + original + "</p></main>")
    assert doc.chunks[0].original_text == original
    assert doc.chunks[0].retrieval_text == normalize_text("لا تُقدِّم العلاج يوم الجمعة ١٠ صباحًا.")
    span = doc.chunks[0].source_spans[0]
    assert span.start == 0 and span.end == len(original)
    assert normalize_text(span.original_text) == doc.chunks[0].retrieval_text


def test_fabricated_normalized_text_cannot_enter_preparation():
    extracted = extract_page(page("<main><p>Clinic closes Friday.</p></main>"))
    unit = extracted.units[0]
    fake = unit.segments[0].model_copy(update={"text": "Clinic opens Friday."})
    extracted = extracted.model_copy(
        update={"units": (unit.model_copy(update={"segments": (fake,)}),)}
    )
    result = prepare_document(
        extracted, counter=SyntheticCounter(), embedding_format=format_profile()
    )
    assert result.chunks == ()
    assert "source_mapping_invalid" in codes(result.gaps)


@pytest.mark.parametrize("counter_value", [None, 0, -1, True, 3.5])
def test_invalid_counter_output_fails_closed(counter_value):
    class BrokenCounter(SyntheticCounter):
        def count(self, text):
            return counter_value

    result = prepare_document(
        extract_page(page("<p>Public fact.</p>")),
        counter=BrokenCounter(),
        embedding_format=format_profile(),
    )
    assert result.chunks == ()
    assert "token_counter_failed" in codes(result.gaps)


def test_wrong_model_counter_stays_draft():
    counter = SyntheticCounter()
    counter.model = "unverified-model"
    result = prepare_document(
        extract_page(page("<p>Public fact.</p>")),
        counter=counter,
        embedding_format=format_profile(),
    )
    assert result.chunks[0].token_count is None
    assert not result.embedding_ready


def test_definition_faq_pairs_never_merge_questions():
    result = prepare(
        "<main><dl><dt>First?</dt><dd>First answer.</dd>"
        "<dt>Second?</dt><dd>Second answer.</dd></dl></main>"
    )
    assert len(result.chunks) == 2
    assert "First?" in result.chunks[0].retrieval_text
    assert "Second?" not in result.chunks[0].retrieval_text
    assert "First answer" not in result.chunks[1].retrieval_text


def test_profile_boundaries_do_not_absorb_unrelated_following_section():
    result = prepare(
        "<main><h2>Team</h2><div class='doctor-card'><h4>Dr. One</h4><p>Specific role.</p>"
        "</div><p>General facility facts.</p></main>"
    )
    assert len(result.chunks) == 2
    assert result.chunks[0].doctor_name == "Dr. One"
    assert result.chunks[1].doctor_name is None


def test_direct_details_answer_and_name_only_doctors_are_preserved():
    result = prepare(
        "<main><h4>Dr. Named</h4><h2>Questions</h2><details><summary>Hours?</summary>"
        "Except Fridays.<p>Open 9 AM–12 PM.</p></details></main>"
    )
    assert len(result.chunks) == 2
    assert result.chunks[0].doctor_name == "Dr. Named"
    assert result.chunks[0].retrieval_text.count("Dr. Named") == 1
    assert "Except Fridays." in result.chunks[1].retrieval_text
    assert "Open 9 AM–12 PM." in result.chunks[1].retrieval_text
    assert result.chunks[1].doctor_name is None


def test_ordered_steps_keep_original_order_labels_when_split():
    result = prepare(
        "<main><ol><li>Contact reception first.</li><li>Read leaflet second.</li></ol></main>",
        max_tokens=5,
    )
    assert len(result.chunks) == 2
    assert result.chunks[0].retrieval_text.startswith("1. Contact")
    assert result.chunks[1].retrieval_text.startswith("2. Read")


@pytest.mark.parametrize(
    "widget",
    [
        "elementor-widget-testimonial",
        "elementor-widget-testimonial-carousel",
        "elementor-testimonial",
        "elementor-widget-reviews",
        "comment-content",
        "wp-block-comments",
    ],
)
def test_identifiable_patient_testimonials_and_user_submissions_are_excluded(widget):
    result = prepare(
        f"<main><p>Public fact.</p><div class='{widget}'>"
        "<p>Named patient and medical detail.</p></div></main>"
    )
    assert len(result.chunks) == 1
    assert "Named patient" not in result.chunks[0].retrieval_text
    assert {"patient_testimonial", "user_submission"} & codes(result.removed)


def test_verified_dummy_headings_are_removed_from_repeated_context():
    result = prepare(
        "<title>Lorem Ipsum is simply dummy - Clinic</title><main>"
        "<h1>Medical team</h1><h2>Lorem Ipsum is simply dummy</h2>"
        "<div class='doctor-card'><h4>Dr. Example</h4><p>Published specialty.</p></div></main>"
    )
    assert len(result.chunks) == 1
    assert "Lorem Ipsum" not in result.chunks[0].retrieval_text
    assert {"placeholder_title", "placeholder_heading"} <= codes(result.removed)


def test_social_icon_labels_are_removed_without_a_false_source_mapping_gap():
    result = prepare(
        "<main><p>Public fact.</p></main><footer>"
        "<div class='elementor-widget-social-icons'><a><svg><title>facebook-fill</title>"
        "</svg><span>Facebook-fill</span></a></div><p>Contact reception.</p></footer>"
    )
    assert "external_social_navigation" in codes(result.removed)
    assert "source_mapping_invalid" not in codes(result.gaps)
    assert all("Facebook" not in chunk.retrieval_text for chunk in result.chunks)


def test_footer_only_does_not_hide_empty_placeholder_main_coverage():
    result = prepare(
        "<main><h1>Lorem ipsum dummy page</h1><p>Lorem ipsum dolor.</p></main>"
        "<footer><p>Contact clinic.</p></footer>"
    )
    assert "main_content_missing" in codes(result.gaps)
    assert not result.embedding_ready


def test_dummy_list_item_does_not_contaminate_or_drop_adjacent_meaningful_items():
    result = prepare(
        "<main><ul><li>Published contact number 000.</li>"
        "<li><a>Read Lorem Ipsum article.</a></li><li>Published address Amman.</li></ul></main>"
    )
    assert len(result.chunks) == 1
    assert "Published contact number 000." in result.chunks[0].retrieval_text
    assert "Published address Amman." in result.chunks[0].retrieval_text
    assert "Lorem Ipsum" not in result.chunks[0].retrieval_text
    assert "placeholder_content_quarantined" in codes(result.gaps)


def test_dummy_faq_context_never_enters_retrieval_text():
    result = prepare(
        "<main><details><summary>What is Lorem Ipsum?</summary>"
        "<p>Generic dummy answer.</p></details><p>Published contact fact.</p></main>"
    )
    assert len(result.chunks) == 1
    assert "Lorem Ipsum" not in result.chunks[0].retrieval_text
    assert "placeholder_context_quarantined" in codes(result.gaps)


@pytest.mark.parametrize("heading", ["Lorem Ipsum is simply dummy", ""])
def test_removed_heading_still_ends_doctor_ownership(heading):
    result = prepare(
        "<main><h4>Dr. One</h4><p>Specific published role.</p><h2>"
        + heading
        + "</h2><p>General clinic information.</p></main>"
    )
    assert len(result.chunks) == 2
    assert result.chunks[0].doctor_name == "Dr. One"
    assert result.chunks[1].doctor_name is None
    assert "Dr. One" not in result.chunks[1].retrieval_text


def test_observed_literal_broken_nbsp_dummy_text_is_excluded_without_rewriting_source():
    result = prepare(
        "<main><h2>Lorem Ipsumu00a0is simply dummy</h2><p>"
        "Lorem Ipsumu00a0is simply dummy text.</p><h4>Dr. One</h4>"
        "<p>Published role.</p></main>"
    )
    assert len(result.chunks) == 1
    assert "Lorem Ipsum" not in result.chunks[0].retrieval_text
    assert "Lorem Ipsumu00a0" in result.document.page.html


def test_wordpress_skip_link_is_audited_navigation_without_a_coverage_gap():
    document = extract_page(
        page(
            "<body><a class='skip-link screen-reader-text' href='#content'>Skip to content</a>"
            "<h1>Published archive</h1><p>Public clinic information.</p></body>"
        )
    )
    assert "navigation_skip_link" in codes(document.removed)
    assert document.gaps == ()
    assert all("Skip to content" not in s.text for u in document.units for s in u.segments)


def test_merged_css_grid_table_is_quarantined_with_original_locator():
    html = (
        "<main><h1>Techniques</h1><div class='grid'>"
        "<div class='cell category header'>Category</div>"
        "<div class='cell header'>Technique</div>"
        "<div class='cell header'>Recovery</div>"
        "<div class='cell category' style='grid-row: span 2;'>Example category</div>"
        "<div class='cell'>Example technique</div><div class='cell'>Only after assessment</div>"
        "<div class='cell'>Second technique</div><div class='cell'>Do not assume recovery</div>"
        "</div><p>Contact the clinic for public information.</p></main>"
    )
    result = prepare(html)
    gap = next(g for g in result.gaps if g.code == "unsupported_css_grid_table")
    assert gap.locator == "main:nth-of-type(1) > div:nth-of-type(1)"
    assert result.document.page.html == html
    assert len(result.chunks) == 1
    assert "Example technique" not in result.chunks[0].retrieval_text
    assert "Only after assessment" not in result.chunks[0].retrieval_text
    assert not result.embedding_ready


def test_generic_css_grid_layout_is_not_mistaken_for_a_table():
    result = prepare(
        "<main><div class='grid'><div><p>Public fact one.</p></div>"
        "<div><p>Public fact two.</p></div></div></main>"
    )
    assert "unsupported_css_grid_table" not in codes(result.gaps)
    assert len(result.chunks) == 1


@pytest.mark.parametrize("name", ["الأستاذ الدكتور مثال", "د مثال"])
def test_explicit_arabic_name_only_profile_headings_are_retained_without_inferred_bio(name):
    html = "<main><h1>" + name + "</h1></main>"
    result = prepare(html)
    assert "main_content_missing" not in codes(result.gaps)
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.block_type == "doctor"
    assert chunk.doctor_name == name
    assert chunk.retrieval_text == name
    assert chunk.original_text == name
    assert len(chunk.source_spans) == 1
    assert result.document.units[0].segments[0].source.locator.endswith("h1:nth-of-type(1)")


@pytest.mark.parametrize(
    "html,expected",
    [
        ("<div>" * 130 + "<p>Fact.</p>" + "</div>" * 130, "dom_complexity_limit"),
        ("<main>" + "<span>x</span>" * 20_001 + "</main>", "dom_complexity_limit"),
        ("<main>" + "x" * 2_000_001 + "</main>", "html_size_limit"),
    ],
    ids=["depth-limit", "node-limit", "byte-limit"],
)
def test_oversized_or_excessively_complex_html_is_bounded_and_quarantined(html, expected):
    document = extract_page(page(html))
    assert document.units == ()
    assert expected in codes(document.gaps)
