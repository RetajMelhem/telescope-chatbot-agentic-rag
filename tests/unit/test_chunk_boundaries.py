"""Synthetic source-layout regressions for bounded semantic groups and exact reuse."""

from datetime import UTC, datetime

import pytest

from telescope_rag.ingestion.deduplication import group_embedding_inputs
from telescope_rag.ingestion.extraction import extract_page
from telescope_rag.ingestion.models import RawPage, stable_id
from telescope_rag.ingestion.preparation import prepare_document


def prepared(html):
    page = RawPage(
        snapshot_id="synthetic-boundary",
        document_id="synthetic-boundary-document",
        canonical_url="https://telescopecenter.com/synthetic-boundary/",
        fetched_at=datetime(2026, 10, 15, tzinfo=UTC),
        content_hash=stable_id(html),
        html=html,
    )
    return prepare_document(extract_page(page))


def box(label, description=""):
    return (
        "<div class='e-con'><div class='elementor-icon-box-content'>"
        f"<h3>{label}</h3><p>{description}</p></div></div>"
    )


@pytest.mark.parametrize(
    "question, lead, first, second, closing",
    [
        (
            "What does the exam include?",
            "Assessment includes:",
            "Pressure",
            "Retina",
            "Tests depend on each individual's needs.",
        ),
        (
            "ماذا يشمل الفحص؟",
            "يشمل التقييم:",
            "ضغط العين",
            "الشبكية",
            "يتم تحديد الفحوصات حسب الحاجة لكل حالة.",
        ),
        (
            "How do we choose?",
            "Evaluation includes:",
            "History",
            "Scalp",
            "Based on this, a personalized plan is designed.",
        ),
        (
            "كيف نحدد العلاج؟",
            "يشمل التقييم:",
            "التاريخ الصحي",
            "فروة الرأس",
            "بناءً على ذلك، يتم تصميم خطة مخصصة.",
        ),
    ],
)
def test_narrative_question_list_and_closing_are_one_complete_answer(
    question, lead, first, second, closing
):
    result = prepared(
        "<main><h1>Care</h1><div class='e-con'>"
        f"<h2>{question}</h2><p>{lead}</p><ul><li>{first}</li><li>{second}</li></ul>"
        f"<p>{closing}</p></div><div class='e-con'><h2>Another section</h2>"
        "<p>Different facts.</p></div></main>"
    )
    answer = [c for c in result.chunks if first in c.retrieval_text]
    assert len(answer) == 1
    assert all(value in answer[0].retrieval_text for value in (question, lead, second, closing))
    assert answer[0].block_type == "faq"
    assert all(
        closing not in c.retrieval_text
        for c in result.chunks
        if "Different facts" in c.retrieval_text
    )


def test_narrative_section_does_not_merge_native_faq_questions():
    result = prepared(
        "<main><div class='e-con'><h2>Questions?</h2>"
        "<details><summary>First?</summary><p>First answer.</p><ul><li>First item.</li></ul>"
        "</details><details><summary>Second?</summary><p>Second answer.</p></details>"
        "</div></main>"
    )
    first = [c for c in result.chunks if "First answer." in c.retrieval_text]
    assert len(first) == 1
    assert "Second answer." not in first[0].retrieval_text


def test_oversized_narrative_answer_repeats_question_and_closing_qualifier():
    class SyntheticWordCounter:
        model = "qwen/qwen3-embedding-8b"
        version = "synthetic-word-counter-for-boundary-test"
        verified = True

        def count(self, text):
            return len(text.split())

    question = "What does assessment include?"
    closing = "Each test depends on the individual clinical needs."
    items = [f"Distinct assessment item {n} has a complete explanation." for n in range(5)]
    document = prepared(
        "<main><h1>Care</h1><div class='e-con'>"
        f"<h2>{question}</h2><p>Assessment includes:</p><ul>"
        + "".join(f"<li>{item}</li>" for item in items)
        + f"</ul><p>{closing}</p></div></main>"
    ).document
    result = prepare_document(document, counter=SyntheticWordCounter(), max_tokens=30)
    children = [c for c in result.chunks if "Distinct assessment item" in c.retrieval_text]
    assert len(children) >= 2
    assert all(question in c.retrieval_text and closing in c.retrieval_text for c in children)
    assert all(c.token_count <= 30 for c in result.chunks)
    assert all(any(item in c.retrieval_text for c in children) for item in items)


@pytest.mark.parametrize("unique", ["", "Unique parent condition."])
def test_nested_container_text_is_emitted_once_and_unique_parent_text_survives(unique):
    result = prepared(
        "<main><h1>Technology</h1><div class='e-con'><ul><li>Quality</li></ul>"
        f"<div>{unique}<div>Safety standards apply.</div><div>Follow-up is provided.</div>"
        "</div><img alt='Quality illustration'></div></main>"
    )
    text = "\n".join(c.retrieval_text for c in result.chunks)
    assert text.count("Safety standards apply.") == 1
    assert text.count("Follow-up is provided.") == 1
    if unique:
        assert unique in text


@pytest.mark.parametrize(
    "heading, lead, items, closing",
    [
        (
            "Should you seek immediate care?",
            "Seek immediate care for:",
            ("Severe sudden pain", "Sudden vision loss"),
            "Early intervention matters.",
        ),
        (
            "متى يجب مراجعة الطبيب فوراً؟",
            "يجب مراجعة الطبيب في حال:",
            ("ألم شديد ومفاجئ", "فقدان مفاجئ للنظر"),
            "التدخل المبكر مهم.",
        ),
        (
            "Is this suitable?",
            "You may be suitable if:",
            ("A stable prescription", "Over eighteen", "No underlying conditions"),
            "A detailed assessment determines the option.",
        ),
        (
            "هل يناسبك هذا الإجراء؟",
            "قد تكون مناسباً إذا:",
            ("درجة نظر مستقرة", "العمر فوق ثمانية عشر", "لا توجد أمراض كامنة"),
            "يتم تحديد الخيار بعد فحص دقيق.",
        ),
    ],
)
def test_icon_list_retains_complete_condition_group_and_closing_caveat(
    heading, lead, items, closing
):
    result = prepared(
        "<main><h1>Public care</h1><section class='e-con'>"
        f"<div class='e-con'><h2>{heading}</h2><div>{lead}</div></div>"
        "<div class='e-con'>" + "".join(box(item) for item in items) + "</div>"
        f"<div>{closing}</div></section><section class='e-con'>"
        "<h2>Unrelated facilities</h2><p>Visitor lounge.</p></section></main>"
    )
    matches = [c for c in result.chunks if items[0] in c.retrieval_text]
    assert matches
    assert all(
        all(value in c.retrieval_text for value in (heading, lead, *items, closing))
        for c in matches
    )
    assert all(
        lead not in c.retrieval_text for c in result.chunks if "Visitor lounge" in c.retrieval_text
    )


@pytest.mark.parametrize(
    "heading, limitation, first, second",
    [
        ("How is this treated?", "Treatment does not reverse existing damage.", "Drops", "Laser"),
        ("كيف يتم العلاج؟", "العلاج لا يعيد الضرر الحاصل.", "القطرات", "الليزر"),
    ],
)
def test_shared_limitation_survives_inverted_heading_levels_without_sibling_attribution(
    heading, limitation, first, second
):
    result = prepared(
        "<main><h1>Public care</h1><section class='e-con'>"
        f"<div class='e-con'><h4>{heading}</h4><p>{limitation}</p></div>"
        "<div class='e-con'>"
        + f"<div class='e-con'><h3>{first}</h3><p>First modality fact.</p></div>"
        + f"<div class='e-con'><h3>{second}</h3><p>Second modality fact.</p></div>"
        + "</div></section>"
        "<section class='e-con'><h2>Facilities</h2><p>Visitor lounge.</p></section></main>"
    )
    for fact, wrong in (("First modality fact", second), ("Second modality fact", first)):
        chunks = [c for c in result.chunks if fact in c.retrieval_text]
        assert chunks
        assert all(heading in c.retrieval_text and limitation in c.retrieval_text for c in chunks)
        assert all(wrong not in c.retrieval_text for c in chunks)
    assert all(
        limitation not in c.retrieval_text
        for c in result.chunks
        if "Visitor lounge" in c.retrieval_text
    )


@pytest.mark.parametrize("name, role", [("Procedure A", "Helps to:"), ("الإجراء أ", "يساعد على:")])
def test_nested_benefits_list_retains_its_explicit_procedure_name(name, role):
    result = prepared(
        "<main><h1>Services</h1><div class='e-con'>"
        f"<div class='e-con'><div><h5>{name}</h5></div><p>Procedure description.</p></div>"
        f"<div class='e-con'><h5>{role}</h5><ul><li>Specific benefit.</li></ul></div>"
        "</div><div class='e-con'><h5>Procedure B</h5><p>Different benefit.</p></div></main>"
    )
    chunks = [c for c in result.chunks if "Specific benefit" in c.retrieval_text]
    assert chunks and all(name in c.retrieval_text for c in chunks)
    assert all(
        name not in c.retrieval_text
        for c in result.chunks
        if "Different benefit" in c.retrieval_text
    )


def test_single_described_sibling_card_never_becomes_group_context():
    result = prepared(
        "<main><h1>Services</h1><section class='e-con'>"
        "<div class='e-con'><h3>Service One</h3><p>First description.</p></div>"
        "<div class='e-con'><h5>Service Two</h5><p>Second description.</p></div>"
        "</section></main>"
    )
    second = [c for c in result.chunks if "Second description" in c.retrieval_text]
    assert second and all("Service One" not in c.retrieval_text for c in second)


def test_exact_repeated_heading_alt_label_formats_once_but_keeps_both_sources():
    result = prepared(
        "<main><div class='e-con'><h2>Public facility</h2>"
        "<img alt='Public facility'><p>Ramps are available.</p></div></main>"
    )
    c = next(c for c in result.chunks if "Ramps" in c.retrieval_text)
    assert c.retrieval_text.count("Public facility") == 1
    spans = (*c.source_spans, *c.context_spans)
    assert any(s.attribute == "alt" and s.original_text == "Public facility" for s in spans)
    assert any(s.locator.endswith("h2:nth-of-type(1)") for s in spans)


def test_repeated_ordered_step_is_not_removed_as_duplicate():
    result = prepared(
        "<main><ol><li>Repeat measurement.</li><li>Repeat measurement.</li></ol></main>"
    )
    assert result.chunks[0].retrieval_text.count("Repeat measurement") == 2
    assert "1. Repeat" in result.chunks[0].retrieval_text
    assert "2. Repeat" in result.chunks[0].retrieval_text


def test_repeated_steps_inside_named_card_keep_every_occurrence():
    result = prepared(
        "<main><div class='e-con'><h2>Repeated procedure</h2>"
        "<ol><li>Repeat measurement.</li><li>Repeat measurement.</li></ol></div></main>"
    )
    assert result.chunks[0].retrieval_text.count("Repeat measurement") == 2
    assert "1. Repeat measurement." in result.chunks[0].retrieval_text
    assert "2. Repeat measurement." in result.chunks[0].retrieval_text


def test_two_doctors_with_identical_specialty_keep_both_independent_records():
    result = prepared(
        "<main><h1>Team</h1><div class='doctor-card'><h2>Dr. Example One</h2>"
        "<p>Same published specialty.</p></div>"
        "<div class='doctor-card'><h2>Dr. Example Two</h2>"
        "<p>Same published specialty.</p></div></main>"
    )
    doctors = [c for c in result.chunks if c.doctor_name]
    assert {c.doctor_name for c in doctors} == {"Dr. Example One", "Dr. Example Two"}
    assert len({c.doctor_id for c in doctors}) == 2
    assert len({c.point_id for c in doctors}) == 2
    assert all("Same published specialty." in c.retrieval_text for c in doctors)
    assert all(c.retrieval_text.count(c.doctor_name) == 1 for c in doctors)
    # Identical input text alone cannot override literal doctor ownership.
    identical = [
        c.model_copy(update={"retrieval_text": "Same published specialty."}) for c in doctors
    ]
    assert len(group_embedding_inputs(identical)) == 2
    for c in doctors:
        other = "Dr. Example Two" if c.doctor_name == "Dr. Example One" else "Dr. Example One"
        assert other not in c.retrieval_text


def test_described_services_keep_separate_cards_under_a_shared_header():
    result = prepared(
        "<main><h1>Public care</h1><section class='e-con'><div><h2>Services</h2></div>"
        "<div class='e-con'><div class='e-con'><h3>Service One</h3>"
        "<div>First clinical description.</div></div><div class='e-con'>"
        "<h3>Service Two</h3><div>Second clinical description.</div></div>"
        "</div></section></main>"
    )
    first = [c for c in result.chunks if "First clinical description" in c.retrieval_text]
    second = [c for c in result.chunks if "Second clinical description" in c.retrieval_text]
    assert first and second
    assert all("Services" in c.retrieval_text for c in (*first, *second))
    assert all("Second clinical description" not in c.retrieval_text for c in first)
    assert all("First clinical description" not in c.retrieval_text for c in second)


def test_nested_group_with_own_header_does_not_inherit_preceding_definition():
    result = prepared(
        "<main><h1>Public care</h1><section class='e-con'>"
        "<div class='e-con'><h2>What is this condition?</h2><p>Definition text.</p></div>"
        "<div class='e-con'><div class='e-con'><h4>How is it treated?</h4>"
        "<p>Existing damage is not reversed.</p></div><div class='e-con'>"
        "<div class='e-con'><h3>Drops</h3><p>Drop-specific fact.</p></div>"
        "<div class='e-con'><h3>Laser</h3><p>Laser-specific fact.</p></div>"
        "</div></div></section></main>"
    )
    treatment = [c for c in result.chunks if "Drop-specific fact" in c.retrieval_text]
    assert treatment
    assert all("Existing damage is not reversed." in c.retrieval_text for c in treatment)
    assert all("Definition text." not in c.retrieval_text for c in treatment)


def test_wrapped_benefits_heading_does_not_erase_the_named_procedure_context():
    result = prepared(
        "<main><h1>Services</h1><section class='e-con'>"
        "<div class='e-con'><div><h5>Procedure A</h5></div><div>Named description.</div></div>"
        "<div class='e-con'><div><h5>Helps to:</h5></div><div class='e-con'>"
        "<ul><li>Specific benefit.</li></ul></div></div></section></main>"
    )
    chunks = [c for c in result.chunks if "Specific benefit." in c.retrieval_text]
    assert chunks
    assert all(
        "Procedure A" in c.retrieval_text and "Named description." in c.retrieval_text
        for c in chunks
    )


def test_layout_spacer_cannot_hide_a_following_sections_independent_introduction():
    result = prepared(
        "<main><h1>Care</h1><section class='e-con'>"
        "<div class='e-con'><h2>Definition?</h2><p>Definition text.</p></div>"
        "<div class='e-con'><div class='e-con'><div class='elementor-widget-spacer'></div>"
        "<div class='e-con'><div><h4>Reasons?</h4></div><div>Published reasons:</div></div>"
        "<div class='e-con'><h5>First reason</h5><h5>Second reason</h5></div>"
        "</div></div></section></main>"
    )
    chunks = [c for c in result.chunks if "First reason" in c.retrieval_text]
    assert chunks and all("Definition text." not in c.retrieval_text for c in chunks)
    assert all("Reasons?" in c.retrieval_text for c in chunks)


def test_doctor_name_authored_as_list_label_is_not_repeated_by_heading_context():
    result = prepared(
        "<main><h1>Dr. Example Founder</h1><div class='e-con'>"
        "<ul><li>Dr. Example Founder</li></ul><p>Founder role.</p></div></main>"
    )
    assert all(c.retrieval_text.count("Dr. Example Founder") == 1 for c in result.chunks)


def test_definition_does_not_cross_into_following_independent_list_section():
    result = prepared(
        "<main><h1>Care</h1><section class='e-con'><div class='e-con'>"
        "<h2>Definition?</h2><p>Definition text.</p></div><div class='e-con'>"
        "<div class='e-con'><h4>Reasons?</h4><div>Reasons include:</div>"
        "<ul><li>Specific reason.</li></ul></div><div class='e-con'>"
        "<h4>Separate technique</h4><div>Another source fact.</div>"
        "<h4>Anesthesia</h4><div>Another separate fact.</div></div></div></section></main>"
    )
    chunks = [c for c in result.chunks if "Specific reason." in c.retrieval_text]
    assert chunks and all("Definition text." not in c.retrieval_text for c in chunks)
    assert all("Reasons?" in c.retrieval_text for c in chunks)
