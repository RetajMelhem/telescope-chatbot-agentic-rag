"""Synthetic relationship regressions for explicit Elementor comparison matrices."""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from bs4 import BeautifulSoup, Tag

from telescope_rag.ingestion.extraction import extract_page
from telescope_rag.ingestion.layouts import (
    UnsupportedElementorLayout,
    is_elementor_comparison,
    parse_elementor_comparison,
)
from telescope_rag.ingestion.models import RawPage, Segment, SourceSpan, stable_id
from telescope_rag.ingestion.preparation import prepare_document


def source(node: Tag) -> Segment:
    original = node.get_text(" ", strip=False)
    locator = "#" + str(node.get("id"))
    return Segment(
        text=" ".join(original.split()),
        source=SourceSpan(
            block_id=stable_id("synthetic-elementor-source", locator),
            locator=locator,
            original_text=original,
            end=len(original),
        ),
    )


def cell(value: str, identifier: str, *, heading: bool = True) -> str:
    value_tag = "h6" if heading else "p"
    widget = "elementor-widget-heading" if heading else "elementor-widget-text-editor"
    return (
        f"<div id='{identifier}' class='e-con' data-label=''>"
        f"<div class='elementor-widget {widget}'><{value_tag}>{value}</{value_tag}>"
        "</div></div>"
    )


def row(values: Sequence[str], identifier: str, *, classes: str = "") -> str:
    return (
        f"<div id='{identifier}' class='e-con {classes}'>"
        + "".join(cell(value, f"{identifier}-{number}") for number, value in enumerate(values))
        + "</div>"
    )


def headers(labels: Sequence[str], identifier: str = "headers", classes: str = "") -> str:
    return (
        f"<div id='{identifier}' class='e-con {classes}'>"
        + "".join(
            cell(value, f"{identifier}-{number}", heading=False)
            for number, value in enumerate(labels)
        )
        + "</div>"
    )


ENGLISH = ("Technique", "How It Works", "Recovery Time", "Best For")
ARABIC = ("التقنية", "كيف تتم", "سرعة التعافي", "الأنسب لمن")
FIRST = ("Example technique one", "No flap is created", "Very fast", "Selected cases only")
SECOND = ("Example technique two", "Surface treatment", "Slower", "Other assessed cases")


def document(html: str) -> Tag:
    soup = BeautifulSoup(html, "html.parser")
    return soup.find(id="matrix")


@pytest.mark.parametrize(
    "labels",
    [
        ENGLISH,
        ("Technique", "How It Is Performed", "Recovery Speed", "Best Suited For"),
        ("التقنية", "كيف يعمل", "Recovery Time", "الأنسب لمن"),
        ARABIC,
    ],
)
def test_four_column_rows_retain_every_header_cell_and_technique(labels):
    node = document(
        "<div id='matrix' class='e-con'>"
        + headers(labels)
        + "<div id='rows' class='e-con'>"
        + row(FIRST, "first")
        + row(SECOND, "second")
        + "</div></div>"
    )
    assert is_elementor_comparison(node)
    groups = parse_elementor_comparison(node, source)
    assert len(groups) == 1
    assert groups[0].context == ()
    assert [h.text for h in groups[0].headers] == list(labels)
    assert len(groups[0].rows) == 2
    for result, values, identifier in zip(
        groups[0].rows, (FIRST, SECOND), ("first", "second"), strict=True
    ):
        assert result.table_layout == "row"
        assert result.source.locator == "#" + identifier
        assert result.text == " ".join(values)
        assert [s.original_text[s.start : s.end].strip() for s in result.table_cells] == list(
            values
        )
        assert [s.original_text[s.start : s.end].strip() for s in result.table_headers] == list(
            labels
        )
        assert " ".join(result.source.original_text.split()) == " ".join(
            " ".join(s.original_text[s.start : s.end].split()) for s in result.table_cells
        )


def test_nested_header_group_keeps_later_nonlaser_rows_under_same_source_headers():
    node = document(
        "<div id='matrix' class='e-con'><div id='laser' class='e-con'>"
        + headers(ENGLISH)
        + row(FIRST, "first")
        + "</div><div id='nonlaser' class='e-con'>"
        + row(SECOND, "second")
        + "</div></div>"
    )
    assert is_elementor_comparison(node)
    groups = parse_elementor_comparison(node, source)
    assert len(groups) == 1
    assert [r.table_cells[0].original_text.strip() for r in groups[0].rows] == [
        FIRST[0],
        SECOND[0],
    ]


def test_table_inner_rows_keep_explicit_category_scope_and_blank_labels_do_not_invent_fields():
    node = document(
        "<div id='matrix' class='e-con'><div id='header-wrapper' class='e-con'>"
        "<div class='e-con'><div class='elementor-widget-spacer'></div></div>"
        + headers(ENGLISH, classes="table-header")
        + "</div><div id='category-one' class='e-con'>"
        "<div id='label-one' class='e-con table-section-title'><div class='e-con'>"
        "<div class='elementor-widget-heading'><h5>Laser techniques</h5></div></div></div>"
        "<div id='rows-one' class='e-con'>"
        + row(FIRST, "first", classes="table-inner")
        + "</div></div><div id='category-two' class='e-con'>"
        "<div id='label-two' class='e-con table-section-title'><div class='e-con'>"
        "<div class='elementor-widget-heading'><h5>Other techniques</h5></div></div></div>"
        "<div id='rows-two' class='e-con'>" + row(SECOND, "second") + "</div></div></div>"
    )
    assert is_elementor_comparison(node)
    groups = parse_elementor_comparison(node, source)
    assert len(groups) == 2
    assert [group.context[0].text for group in groups] == ["Laser techniques", "Other techniques"]
    assert groups[0].context[0].source.locator == "#label-one"
    assert groups[1].rows[0].table_cells[0].original_text.strip() == SECOND[0]
    assert len(groups[0].rows[0].table_headers) == 4


def test_repeated_complete_matrices_are_detected_separately():
    html = (
        "<div id='wrapper' class='e-con'>"
        + "".join(
            f"<div id='matrix-{n}' class='e-con'>"
            + headers(ENGLISH, identifier=f"header-{n}")
            + row(FIRST, f"row-{n}")
            + "</div>"
            for n in range(2)
        )
        + "</div>"
    )
    soup = BeautifulSoup(html, "html.parser")
    assert not is_elementor_comparison(soup.find(id="wrapper"))
    for n in range(2):
        node = soup.find(id=f"matrix-{n}")
        assert is_elementor_comparison(node)
        result = parse_elementor_comparison(node, source)[0].rows[0]
        assert result.source.locator == f"#row-{n}"


def test_generic_four_service_cards_do_not_establish_a_comparison_matrix():
    node = document(
        "<div id='matrix' class='e-con'>"
        + row(("Service one", "Service two", "Service three", "Service four"), "services")
        + "<p>Public service descriptions.</p></div>"
    )
    assert not is_elementor_comparison(node)
    with pytest.raises(UnsupportedElementorLayout):
        parse_elementor_comparison(node, source)


@pytest.mark.parametrize(
    "bad_data",
    [
        row(FIRST[:3], "incomplete"),
        row((*FIRST, "Unexpected fifth cell"), "wide"),
        row((FIRST[0], "", FIRST[2], FIRST[3]), "blank"),
        row(FIRST, "styled").replace("class='e-con '", "class='e-con ' style='order:2'", 1),
        row(FIRST, "nested").replace("No flap is created", "<table><tr><td>X</td></tr></table>"),
        row(FIRST, "multiple").replace(
            "No flap is created</h6>", "No flap is created</h6><p>Unresolved note</p>"
        ),
        row(FIRST[:3], "bad-inner", classes="table-inner"),
        "<p>Unlabeled extra clinical qualification.</p>" + row(FIRST, "first"),
        "Stray direct text" + row(FIRST, "first"),
    ],
)
def test_ambiguous_row_or_external_note_refuses_entire_candidate(bad_data):
    node = document("<div id='matrix' class='e-con'>" + headers(ENGLISH) + bad_data + "</div>")
    assert is_elementor_comparison(node)
    with pytest.raises(
        UnsupportedElementorLayout, match="^unsupported_elementor_comparison_table$"
    ):
        parse_elementor_comparison(node, source)


@pytest.mark.parametrize(
    "bad_headers",
    [
        ("Technique", "How It Works", "Recovery Time"),
        ("Technique", "Recovery Time", "How It Works", "Best For"),
        ("Technique", "How It Works", "Unknown metric", "Best For"),
        ("Technique", "How It Works", "Recovery Time", "Recovery Time"),
    ],
)
def test_incomplete_unknown_reordered_or_duplicate_headers_cannot_be_guessed(bad_headers):
    node = document(
        "<div id='matrix' class='e-con'>" + headers(bad_headers) + row(FIRST, "first") + "</div>"
    )
    assert is_elementor_comparison(node)
    with pytest.raises(UnsupportedElementorLayout):
        parse_elementor_comparison(node, source)


def test_a_row_before_the_header_cannot_be_admitted_using_later_labels():
    node = document(
        "<div id='matrix' class='e-con'><div class='e-con'>"
        + row(FIRST, "first")
        + headers(ENGLISH, classes="table-header")
        + "</div>"
        + row(SECOND, "second")
        + "</div>"
    )
    assert is_elementor_comparison(node)
    with pytest.raises(UnsupportedElementorLayout):
        parse_elementor_comparison(node, source)


def test_factory_row_text_must_match_all_its_original_cell_values():
    node = document(
        "<div id='matrix' class='e-con'>" + headers(ENGLISH) + row(FIRST, "first") + "</div>"
    )

    def invalid_factory(tag):
        result = source(tag)
        return (
            result.model_copy(update={"text": "invented"}) if tag.get("id") == "first" else result
        )

    with pytest.raises(UnsupportedElementorLayout):
        parse_elementor_comparison(node, invalid_factory)


def test_rows_are_bounded_without_returning_a_partially_valid_prefix():
    node = document(
        "<div id='matrix' class='e-con'>"
        + headers(ENGLISH)
        + "".join(row(FIRST, f"row-{n}") for n in range(257))
        + "</div>"
    )
    with pytest.raises(UnsupportedElementorLayout):
        parse_elementor_comparison(node, source)


def prepared(html: str):
    raw = RawPage(
        snapshot_id="synthetic-elementor-snapshot",
        document_id="synthetic-elementor-document",
        canonical_url="https://telescopecenter.com/synthetic-elementor/",
        fetched_at=datetime(2026, 10, 15, tzinfo=UTC),
        content_hash=stable_id(html),
        html=html,
    )
    return prepare_document(extract_page(raw))


def test_preparation_retrieves_each_complete_technique_row_with_its_own_values():
    result = prepared(
        "<main><h1>Comparison</h1><div id='matrix' class='e-con'>"
        + headers(ENGLISH)
        + row(FIRST, "first")
        + row(SECOND, "second")
        + "</div></main>"
    )
    tables = [chunk for chunk in result.chunks if chunk.block_type == "table"]
    assert len(tables) == 2
    assert (
        "Technique: Example technique one; How It Works: No flap is created"
        in tables[0].retrieval_text
    )
    assert "Recovery Time: Very fast; Best For: Selected cases only" in tables[0].retrieval_text
    assert "Example technique two" not in tables[0].retrieval_text
    assert (
        "Technique: Example technique two; How It Works: Surface treatment"
        in tables[1].retrieval_text
    )
    assert "Recovery Time: Slower; Best For: Other assessed cases" in tables[1].retrieval_text
    assert "Example technique one" not in tables[1].retrieval_text
    assert all(chunk.doctor_id is None for chunk in tables)
    assert not any(item.code == "invalid_source_mapping" for item in result.gaps)
    assert all(len(chunk.source_spans) == 5 for chunk in tables)


def test_integration_quarantines_incomplete_candidate_without_orphan_cell_fallback():
    result = prepared(
        "<main><h1>Comparison</h1><div id='matrix' class='e-con'>"
        + headers(ENGLISH)
        + row(FIRST[:3], "incomplete")
        + "</div><section class='e-con'><h2>Public contact</h2>"
        "<p>Contact the clinic directly.</p></section></main>"
    )
    assert any(item.code == "unsupported_elementor_comparison_table" for item in result.gaps)
    text = " ".join(chunk.retrieval_text for chunk in result.chunks)
    assert "Very fast" not in text
    assert "Example technique one" not in text
    assert "Contact the clinic directly" in text
