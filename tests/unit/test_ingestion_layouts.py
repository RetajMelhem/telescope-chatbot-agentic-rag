"""Supported CSS source relationships and refusal of ambiguous grid placement."""

import pytest
from bs4 import BeautifulSoup, Tag

from telescope_rag.ingestion.layouts import UnsupportedGridLayout, parse_css_grid
from telescope_rag.ingestion.models import Segment, SourceSpan


def _source(node: Tag) -> Segment:
    original = node.get_text(" ", strip=False)
    return Segment(
        text=" ".join(original.split()),
        source=SourceSpan(
            block_id=node["id"],
            locator=f'div[id="{node["id"]}"]',
            original_text=original,
            end=len(original),
        ),
    )


def _grid() -> Tag:
    # Synthetic labels and data; this is not collected clinic content.
    soup = BeautifulSoup(
        """<div class="grid">
        <div class="cell category header" id="h0">Category</div>
        <div class="cell header" id="h1">Method</div>
        <div class="cell header" id="h2">Process</div>
        <div class="cell header" id="h3">Time</div>
        <div class="cell header" id="h4">Qualifier</div>
        <div class="cell category" id="c0" style="grid-row: span 2;">Group A</div>
        <div class="cell" id="a1">Alpha</div>
        <div class="cell" id="a2">Process A</div>
        <div class="cell" id="a3">Fast</div>
        <div class="cell" id="a4">Some cases</div>
        <div class="cell" id="b1">Beta</div>
        <div class="cell" id="b2">Process B</div>
        <div class="cell" id="b3">Slow</div>
        <div class="cell" id="b4">Assessment required</div>
        <div class="cell category" id="c1" style="grid-row: span 1;">Group B</div>
        <div class="cell" id="d1">Gamma</div>
        <div class="cell" id="d2">Process C</div>
        <div class="cell" id="d3">Variable</div>
        <div class="cell" id="d4">Not for every case</div>
        </div>""",
        "html.parser",
    )
    return soup.div


def test_rows_retain_actual_cell_sources_and_explicit_category_span():
    grid = _grid()
    rows = parse_css_grid(grid, _source)
    assert len(rows) == 3
    assert [r.text for r in rows] == ["Group A", "Beta", "Group B"]
    assert [r.source.block_id for r in rows] == ["c0", "b1", "c1"]
    assert [[s.block_id for s in r.table_cells] for r in rows] == [
        ["c0", "a1", "a2", "a3", "a4"],
        ["c0", "b1", "b2", "b3", "b4"],
        ["c1", "d1", "d2", "d3", "d4"],
    ]
    assert all(r.table_layout == "grid_cells" for r in rows)
    for row in rows:
        assert row.source in row.table_cells
        assert [s.block_id for s in row.table_headers] == ["h0", "h1", "h2", "h3", "h4"]
        for source in (*row.table_cells, *row.table_headers):
            assert source.original_text == grid.select_one(source.locator).get_text(
                " ", strip=False
            )
            assert source.end == len(source.original_text)


def test_arabic_cells_preserve_negation_qualifier_and_original_whitespace():
    grid = _grid()
    grid.find(id="h0").string = "الفئة"
    grid.find(id="a1").string = "طريقة ألف"
    grid.find(id="a4").string = "  ليس لجميع الحالات\nبعد التقييم  "
    row = parse_css_grid(grid, _source)[0]
    assert row.table_cells[1].original_text == "طريقة ألف"
    assert row.table_cells[4].original_text == "  ليس لجميع الحالات\nبعد التقييم  "
    assert row.table_cells[4].start == 0
    assert row.table_cells[4].end == len(row.table_cells[4].original_text)


def test_inline_markup_and_comments_do_not_change_column_ownership():
    grid = _grid()
    grid.find(id="a4").clear()
    qualifier = BeautifulSoup("<!-- note --><strong>Some</strong> cases<br/>only", "html.parser")
    for child in list(qualifier.children):
        grid.find(id="a4").append(child)
    row = parse_css_grid(grid, _source)[0]
    assert row.table_cells[4].original_text == "Some  cases only"


@pytest.mark.parametrize(
    "span",
    [
        "",
        "grid-row: span 0;",
        "grid-row: span -1;",
        "grid-row: span 1.5;",
        "grid-row: span 257;",
        "grid-row: 2 / 4;",
        "grid-row: span 2 !important;",
        "grid-row: span 2; grid-column: 2;",
        "grid-row: span 3;",
        "grid-row: span 1;",
        "order: 1;",
    ],
)
def test_inexact_or_inconsistent_category_placement_refuses_whole_grid(span):
    grid = _grid()
    grid.find(id="c0")["style"] = span
    with pytest.raises(UnsupportedGridLayout, match="^unsupported_css_grid_table$"):
        parse_css_grid(grid, _source)


@pytest.mark.parametrize(
    "change",
    [
        "missing_cell",
        "extra_cell",
        "header_among_data",
        "category_inside_row",
        "empty_cell",
        "nested_cell",
        "extra_direct_text",
        "non_cell_child",
        "column_override",
        "grid_override",
        "wrong_header_count",
        "second_category_header",
        "duplicate_header",
        "empty_data",
    ],
)
def test_ambiguous_grid_structure_returns_no_partial_rows(change):
    grid = _grid()
    if change == "missing_cell":
        grid.find(id="a3").decompose()
    elif change == "extra_cell":
        extra = BeautifulSoup('<div class="cell" id="x">Orphan</div>', "html.parser").div
        grid.append(extra)
    elif change == "header_among_data":
        grid.find(id="b2")["class"] = ["cell", "header"]
    elif change == "category_inside_row":
        grid.find(id="b2")["class"] = ["cell", "category"]
    elif change == "empty_cell":
        grid.find(id="d4").string = "  "
    elif change == "nested_cell":
        nested = BeautifulSoup('<span class="cell">Nested</span>', "html.parser").span
        grid.find(id="a1").append(nested)
    elif change == "extra_direct_text":
        grid.append("Unassigned statement")
    elif change == "non_cell_child":
        grid.append(BeautifulSoup("<p>Unassigned statement</p>", "html.parser").p)
    elif change == "column_override":
        grid.find(id="a1")["style"] = "grid-column: 3;"
    elif change == "grid_override":
        grid["style"] = "grid-template-columns: repeat(3, 1fr);"
    elif change == "wrong_header_count":
        grid.find(id="h4")["class"] = ["cell"]
    elif change == "second_category_header":
        grid.find(id="h2")["class"] = ["cell", "header", "category"]
    elif change == "duplicate_header":
        grid.find(id="h2").string = "Method"
    elif change == "empty_data":
        for child in list(grid.find_all("div", recursive=False))[5:]:
            child.decompose()
    with pytest.raises(UnsupportedGridLayout):
        parse_css_grid(grid, _source)


def test_category_span_whitespace_and_case_are_literal_css_syntax():
    grid = _grid()
    grid.find(id="c0")["style"] = "  GRID-ROW : SPAN 2 "
    rows = parse_css_grid(grid, _source)
    assert rows[0].table_cells[0] == rows[1].table_cells[0]
