"""Synthetic regressions for semantic relationships found during the page-by-page audit.

These fixtures reproduce source layout shapes, not captured website pages. They use no
provider, tokenizer compatibility claim, network request, or approved source content.
"""

from datetime import UTC, datetime

import pytest

from telescope_rag.ingestion.extraction import extract_page, normalize_text
from telescope_rag.ingestion.models import RawPage, stable_id
from telescope_rag.ingestion.preparation import prepare_document


def prepare(html: str):
    page = RawPage(
        snapshot_id="synthetic-semantic-snapshot",
        document_id="synthetic-semantic-document",
        canonical_url="https://telescopecenter.com/synthetic-semantic-fixture/",
        fetched_at=datetime(2026, 10, 14, tzinfo=UTC),
        content_hash=stable_id(html),
        html=html,
    )
    return prepare_document(extract_page(page))


def containing(document, phrase: str):
    return [chunk for chunk in document.chunks if phrase in chunk.retrieval_text]


def test_heading_only_service_and_facility_names_remain_retrievable():
    result = prepare(
        "<main><h1>Public services</h1><section class='e-con'>"
        "<h2>Eye services</h2><div class='e-con'><h3>Vision assessment</h3></div>"
        "<div class='e-con'><h3>Child eye care</h3></div></section>"
        "<section class='e-con'><h2>Facilities</h2>"
        "<div class='e-con'><h4>Prayer room</h4></div>"
        "<div class='e-con'><h4>Accessible entrance</h4></div></section></main>"
    )
    for name in ("Vision assessment", "Child eye care", "Prayer room", "Accessible entrance"):
        assert containing(result, name), name
    facility = containing(result, "Accessible entrance")
    assert all("Eye services" not in chunk.section_path for chunk in facility)


def test_doctor_certification_heading_is_owned_without_inventing_a_degree_person():
    result = prepare(
        "<main><h1>Team</h1><div class='doctor-profile'><h2>Dr. Example One</h2>"
        "<p>A specialist with advanced training.</p><h3>Qualifications</h3>"
        "<div class='e-con'><h4>Doctor of Medicine</h4></div>"
        "<div class='e-con'><h4>Diploma in clinical leadership</h4></div>"
        "</div><div class='doctor-profile'><h2>Dr. Example Two</h2>"
        "<p>A different specialist.</p></div></main>"
    )
    for fact in ("Doctor of Medicine", "Diploma in clinical leadership"):
        chunks = containing(result, fact)
        assert chunks
        assert all(chunk.doctor_name == "Dr. Example One" for chunk in chunks)
        assert all("Dr. Example Two" not in chunk.retrieval_text for chunk in chunks)
    assert {chunk.doctor_name for chunk in result.chunks if chunk.doctor_name} == {
        "Dr. Example One",
        "Dr. Example Two",
    }


def test_sibling_treatments_with_different_heading_levels_do_not_inherit_prior_treatment():
    result = prepare(
        "<main><h1>Corneal services</h1><section class='e-con'>"
        "<h2>Treatments</h2><div class='e-con'><h3>Keratoprosthesis</h3>"
        "<p>A prosthetic option for selected complex cases.</p></div>"
        "<div class='e-con'><h5>Corneal cross linking</h5>"
        "<p>A separate technique used to strengthen tissue.</p></div>"
        "<div class='e-con'><h5>Surface laser treatment</h5>"
        "<p>Another separate procedure.</p></div></section></main>"
    )
    for phrase in ("strengthen tissue", "Another separate procedure"):
        chunks = containing(result, phrase)
        assert chunks
        assert all("Keratoprosthesis" not in chunk.retrieval_text for chunk in chunks)
        assert all("Keratoprosthesis" not in chunk.section_path for chunk in chunks)


def test_timeline_card_keeps_its_day_and_result_without_previous_event_context():
    result = prepare(
        "<main><h1>Recovery timeline</h1><section class='e-con'>"
        "<div class='e-con'><ul><li>First day:</li></ul><h4>Early improvement</h4></div>"
        "<div class='e-con'><ul><li>First week:</li></ul>"
        "<h4>Gradual stabilization with follow-up</h4></div>"
        "<div class='e-con'><ul><li>After several weeks:</li></ul>"
        "<h4>Final assessment</h4></div></section></main>"
    )
    for label, result_text, wrong in (
        ("First day:", "Early improvement", "First week:"),
        ("First week:", "Gradual stabilization with follow-up", "Early improvement"),
        ("After several weeks:", "Final assessment", "Gradual stabilization with follow-up"),
    ):
        chunks = containing(result, label)
        assert chunks
        assert any(result_text in chunk.retrieval_text for chunk in chunks)
        assert all(wrong not in chunk.retrieval_text for chunk in chunks)


def comparison_card(lens: str, distance: str, glasses: str, suitability: str) -> str:
    fields = (
        ("Lens type", lens),
        ("Vision range", distance),
        ("Glasses", glasses),
        ("Suitable for", suitability),
    )
    return (
        "<div class='e-con'>"
        + "".join(
            "<div class='e-con'><div class='elementor-icon-box-content'>"
            f"<h3>{label}</h3><p>{value}</p></div></div>"
            for label, value in fields
        )
        + "</div>"
    )


def test_comparison_card_keeps_all_fields_with_the_same_lens_identity():
    result = prepare(
        "<main><h1>Lens comparison</h1><section class='e-con'>"
        + comparison_card("Single-focus lens", "One distance", "Reading glasses", "Selected cases")
        + comparison_card(
            "Extended-range lens", "Far and intermediate", "May need readers", "Other cases"
        )
        + "</section></main>"
    )
    for identity, values, wrong_identity in (
        (
            "Single-focus lens",
            ("One distance", "Reading glasses", "Selected cases"),
            "Extended-range lens",
        ),
        (
            "Extended-range lens",
            ("Far and intermediate", "May need readers", "Other cases"),
            "Single-focus lens",
        ),
    ):
        chunks = containing(result, identity)
        assert chunks
        assert any(all(value in chunk.retrieval_text for value in values) for chunk in chunks)
        assert all(wrong_identity not in chunk.retrieval_text for chunk in chunks)
        assert all(chunk.doctor_id is None for chunk in chunks)


def test_one_item_facility_label_and_description_form_one_retrievable_card():
    result = prepare(
        "<main><h1>Facilities</h1><section class='e-con'>"
        "<div class='e-con'><ul><li>Accessible entrance</li></ul>"
        "<p>Ramps and wide corridors make access easier.</p></div>"
        "<div class='e-con'><ul><li>Visitor café</li></ul>"
        "<p>Light meals and drinks are available.</p></div></section></main>"
    )
    entrance = containing(result, "Ramps and wide corridors")
    assert entrance
    assert all("Accessible entrance" in chunk.retrieval_text for chunk in entrance)
    assert all("Visitor café" not in chunk.retrieval_text for chunk in entrance)
    cafe = containing(result, "Light meals and drinks")
    assert cafe
    assert all("Visitor café" in chunk.retrieval_text for chunk in cafe)
    assert all("Accessible entrance" not in chunk.retrieval_text for chunk in cafe)


def test_founder_list_name_owns_attached_title_education_and_biography():
    result = prepare(
        "<main><h1>Our team</h1><div class='e-con'>"
        "<ul><li><span>Dr. Example Founder</span></li></ul>"
        "<p>Founder and chair</p><p>Holds a leadership degree from Example University.</p>"
        "<p>Established the center.</p></div>"
        "<section class='e-con'><h2>Facilities</h2><p>There is a public lounge.</p>"
        "</section></main>"
    )
    for fact in ("Founder and chair", "Example University", "Established the center"):
        chunks = containing(result, fact)
        assert chunks
        assert all(chunk.doctor_name == "Dr. Example Founder" for chunk in chunks)
    assert all(chunk.doctor_name is None for chunk in containing(result, "public lounge"))


def test_named_partner_image_alt_is_captured_with_attribute_provenance():
    result = prepare(
        "<main><h1>Public information</h1><section class='e-con'>"
        "<h2>Insurance partners</h2><img src='/a.svg' alt='Example Health Network'>"
        "<img src='/b.svg' alt='Sample Insurance'><img src='/icon.svg' alt='image 1'>"
        "</section></main>"
    )
    for name in ("Example Health Network", "Sample Insurance"):
        chunks = containing(result, name)
        assert chunks
        assert any("Insurance partners" in chunk.retrieval_text for chunk in chunks)
        spans = [span for chunk in chunks for span in chunk.source_spans]
        assert any(
            span.attribute == "alt"
            and span.locator.endswith("::attr(alt)")
            and span.original_text[span.start : span.end] == name
            for span in spans
        )
    assert not containing(result, "image 1")


@pytest.mark.parametrize(
    "heading, lead_in, first, second",
    [
        (
            "When do results appear?",
            "Results vary depending on the case, but generally:",
            "Improvement may begin within weeks",
            "Density may improve over several months",
        ),
        (
            "متى تظهر النتائج؟",
            "تختلف النتائج حسب الحالة ونوع العلاج، لكن غالباً:",
            "قد يبدأ التحسن خلال أسابيع",
            "قد تتحسن الكثافة خلال عدة أشهر",
        ),
    ],
)
def test_result_list_keeps_source_variability_qualifier(heading, lead_in, first, second):
    result = prepare(
        f"<main><h1>Hair care</h1><h2>{heading}</h2><p>{lead_in}</p>"
        f"<ul><li>{first}</li><li>{second}</li></ul></main>"
    )
    chunks = containing(result, first)
    assert chunks
    assert all(normalize_text(lead_in) in chunk.retrieval_text for chunk in chunks)
    assert all(second in chunk.retrieval_text for chunk in chunks)


def test_acute_warning_stays_with_symptoms_and_does_not_bleed_into_next_section():
    result = prepare(
        "<main><h1>Eye care</h1><section class='e-con'><h2>Emergency symptoms</h2>"
        "<p>Seek immediate medical attention if any of the following occur:</p>"
        "<ul><li>Sudden loss of vision</li><li>A new curtain in your vision</li></ul>"
        "</section><section class='e-con'><h2>Routine facilities</h2>"
        "<ul><li>Waiting lounge</li></ul></section></main>"
    )
    warning = containing(result, "Sudden loss of vision")
    assert warning
    assert all("Seek immediate medical attention" in chunk.retrieval_text for chunk in warning)
    assert all("A new curtain in your vision" in chunk.retrieval_text for chunk in warning)
    assert all(
        "Seek immediate medical attention" not in chunk.retrieval_text
        for chunk in containing(result, "Waiting lounge")
    )


def test_dummy_post_card_is_removed_as_a_whole_without_removing_adjacent_real_content():
    result = prepare(
        "<main><h1>Clinic updates</h1><article class='elementor-post'>"
        "<h3>Lorem Ipsum is simply dummy text.</h3><ul><li>Medical</li>"
        "<li>24 February 2026</li></ul><p>It is a long established fact that a reader "
        "will be distracted by the readable content of a page when</p></article>"
        "<article><h2>Actual public announcement</h2>"
        "<p>A new public information desk is available.</p></article></main>"
        "<footer><h2>Phone</h2><p>000-000</p></footer>"
    )
    text = " ".join(chunk.retrieval_text for chunk in result.chunks)
    for placeholder in ("Lorem Ipsum", "long established fact", "Medical", "24 February 2026"):
        assert placeholder not in text
    assert "new public information desk" in text
    assert "000-000" in text
    assert any(item.code == "placeholder_article_or_step" for item in result.removed)


def test_quoted_personal_carousel_is_excluded_while_public_facilities_are_retained():
    result = prepare(
        "<main><h1>About the center</h1><div class='custom-carousel'>"
        "<div class='elementor-image-box-content'><h3 class='elementor-image-box-title'>"
        "Example Patient</h3><p>“My private treatment story.”</p></div></div>"
        "<section class='e-con'><h2>Facilities</h2><h3>Public prayer room</h3>"
        "</section></main>"
    )
    text = " ".join(chunk.retrieval_text for chunk in result.chunks)
    assert "Example Patient" not in text
    assert "private treatment story" not in text
    assert "Public prayer room" in text
    assert any(item.code == "personal_testimonial_carousel" for item in result.removed)


def test_footer_contacts_do_not_inherit_booking_question_or_doctor_ownership():
    result = prepare(
        "<body><h1>Information</h1><h2>Ready to arrange a visit?</h2>"
        "<p>Contact the center directly.</p><footer><h3>Email</h3>"
        "<p>public@example.invalid</p><h3>Phone</h3><p>000-000</p></footer></body>"
    )
    contacts = containing(result, "public@example.invalid") + containing(result, "000-000")
    assert contacts
    assert all(chunk.block_type == "contact" for chunk in contacts)
    assert all(chunk.doctor_id is None for chunk in contacts)
    assert all("Ready to arrange a visit?" not in chunk.retrieval_text for chunk in contacts)


def test_image_only_partner_carousel_retains_its_source_category():
    result = prepare(
        "<main><section class='e-con'><div class='e-con'><h2>Insurance partners</h2></div>"
        "<div class='e-con'><div><img alt='Example partner one'/></div>"
        "<div><img alt='Example partner two'/></div></div></section></main>"
    )
    for name in ("Example partner one", "Example partner two"):
        assert containing(result, name)
        assert all("Insurance partners" in c.retrieval_text for c in containing(result, name))


def test_qualifying_prose_survives_nested_widget_boundaries_before_a_list():
    result = prepare(
        "<main><section class='e-con'><h2>Expected results</h2>"
        "<div class='e-con'><p>Results vary by condition; usually:</p></div>"
        "<div class='e-con'><ul><li>Gradual change over several months</li>"
        "<li>Follow-up may be needed</li></ul></div></section></main>"
    )
    assert all(
        "Results vary by condition; usually:" in c.retrieval_text
        for c in containing(result, "Gradual change over several months")
    )


def test_sibling_heading_only_cards_are_not_children_of_the_first_card():
    result = prepare(
        "<main><div class='e-con e-grid'><div class='e-con'><h3>First service</h3></div>"
        "<div class='e-con'><h3>Second service</h3></div></div></main>"
    )
    assert containing(result, "Second service")
    assert all("First service" not in c.section_path for c in containing(result, "Second service"))


def test_supported_css_table_rows_are_formatted_with_all_source_labels_and_group_context():
    result = prepare(
        "<main><h1>Techniques</h1><div class='grid'>"
        "<div class='cell category header'>Category</div><div class='cell header'>Technique</div>"
        "<div class='cell header'>Method</div><div class='cell header'>Recovery</div>"
        "<div class='cell header'>For whom</div>"
        "<div class='cell category' style='grid-row: span 2;'>Group</div>"
        "<div class='cell'>First</div><div class='cell'>Method one</div>"
        "<div class='cell'>Slow</div><div class='cell'>Selected cases</div>"
        "<div class='cell'>Second</div><div class='cell'>Method two</div>"
        "<div class='cell'>Fast</div><div class='cell'>Other cases</div></div></main>"
    )
    rows = [c for c in result.chunks if c.block_type == "table"]
    assert len(rows) == 2
    assert (
        "Category: Group; Technique: First; Method: Method one; "
        "Recovery: Slow; For whom: Selected cases" in rows[0].retrieval_text
    )
    assert (
        "Category: Group; Technique: Second; Method: Method two; "
        "Recovery: Fast; For whom: Other cases" in rows[1].retrieval_text
    )
    assert len(rows[0].context_spans) >= 5 and len(rows[1].source_spans) == 6
    assert "unsupported_css_grid_table" not in {g.code for g in result.gaps}


def test_placeholder_article_main_is_removed_with_its_metadata_but_footer_remains():
    result = prepare(
        "<title>Lorem Ipsum article</title><body><main class='post type-post'>"
        "<h1>Lorem Ipsum</h1><p>It is a long established fact that a reader</p>"
        "<p>Template filler without the placeholder keyword.</p></main>"
        "<footer><h3>Contact</h3><p>public@example.invalid</p></footer></body>"
    )
    text = " ".join(c.retrieval_text for c in result.chunks)
    assert "Template filler" not in text and "public@example.invalid" in text


def test_publication_status_is_preserved_without_template_article_content():
    result = prepare(
        "<main><h1>Coming soon</h1><p>Public information will be added here.</p></main>"
    )
    assert containing(result, "Coming soon")


def test_hidden_all_viewports_is_excluded_but_mobile_and_animated_content_survive():
    result = prepare(
        "<main><div class='elementor-hidden-desktop elementor-hidden-tablet "
        "elementor-hidden-mobile'>"
        "<h2>Inactive prototype</h2><p>Unpublished copy.</p></div>"
        "<div class='e-con elementor-hidden-desktop'><h2>Mobile information</h2>"
        "<p>Public mobile copy.</p></div><div class='e-con elementor-invisible'>"
        "<h2>Animated information</h2><p>Real source copy.</p></div></main>"
    )
    assert not containing(result, "Unpublished copy")
    assert containing(result, "Public mobile copy") and containing(result, "Real source copy")


def test_bilingual_title_does_not_mislabel_english_evidence():
    result = prepare(
        "<title>Public clinic مركز طبي</title><main><h1>Services</h1>"
        "<p>English evidence.</p></main>"
    )
    assert all(c.language == "en" for c in containing(result, "English evidence"))
