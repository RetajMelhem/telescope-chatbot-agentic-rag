"""Small, fail-closed adapters for explicitly supported source layouts.

CSS grids and Elementor containers are not HTML tables. Supported shapes are
the observed five-column direct-cell grid with explicit category spans and the
four-column Elementor matrix with complete headers/rows and explicit groups.
No computed style, text similarity, or inferred cell pairing establishes a
relationship. Callers must record a gap when a parser refuses.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from bs4 import Comment, NavigableString, Tag

from telescope_rag.ingestion.models import Segment

_SPAN = re.compile(r"\s*grid-row\s*:\s*span\s+([1-9][0-9]*)\s*;?\s*", re.I)
_INLINE_TAGS = {"a", "b", "br", "em", "i", "small", "span", "strong", "sub", "sup"}
_COLUMNS = 5
_MAX_ROWS = 256


class UnsupportedGridLayout(ValueError):
    """The source does not establish one of the supported complete grid layouts."""

    def __init__(self):
        super().__init__("unsupported_css_grid_table")


def _cells(node: Tag) -> list[Tag]:
    if node.name != "div" or set(node.get("class", [])) != {"grid"}:
        raise UnsupportedGridLayout
    if node.get("style"):
        # Inline positioning/reordering can invalidate direct source order.
        raise UnsupportedGridLayout
    result = []
    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            if child.strip():
                raise UnsupportedGridLayout
            continue
        if not isinstance(child, Tag) or child.name != "div":
            raise UnsupportedGridLayout
        classes = set(child.get("class", []))
        if "cell" not in classes or not classes <= {"cell", "header", "category"}:
            raise UnsupportedGridLayout
        if any(
            nested.name not in _INLINE_TAGS
            or set(nested.get("class", [])) & {"grid", "cell", "header", "category"}
            or nested.get("style")
            for nested in child.find_all(True)
        ):
            raise UnsupportedGridLayout
        if not child.get_text(" ", strip=True):
            raise UnsupportedGridLayout
        result.append(child)
    if len(result) > _COLUMNS + _MAX_ROWS * _COLUMNS:
        raise UnsupportedGridLayout
    return result


def parse_css_grid(node: Tag, segment_factory: Callable[[Tag], Segment]) -> tuple[Segment, ...]:
    """Return source-backed complete rows or refuse the entire grid.

    A category's source span repeats across exactly its explicit ``grid-row``
    span. Each row's primary source and text come from its first *actual* cell;
    there is no invented combined-row source. All five header and cell spans are
    retained in column order for the preparation layer to format with labels.
    """
    cells = _cells(node)
    if len(cells) <= _COLUMNS:
        raise UnsupportedGridLayout
    headers = cells[:_COLUMNS]
    if any("header" not in cell.get("class", []) or cell.get("style") for cell in headers):
        raise UnsupportedGridLayout
    if ["category" in cell.get("class", []) for cell in headers] != [
        True,
        False,
        False,
        False,
        False,
    ]:
        raise UnsupportedGridLayout
    header_segments = tuple(segment_factory(cell) for cell in headers)
    if len({segment.text for segment in header_segments}) != _COLUMNS:
        raise UnsupportedGridLayout
    data = cells[_COLUMNS:]
    position = 0
    rows: list[Segment] = []
    while position < len(data):
        category_node = data[position]
        if set(category_node.get("class", [])) != {"cell", "category"}:
            raise UnsupportedGridLayout
        match = _SPAN.fullmatch(str(category_node.get("style", "")))
        if not match:
            raise UnsupportedGridLayout
        span = int(match[1])
        if span > _MAX_ROWS or len(rows) + span > _MAX_ROWS:
            raise UnsupportedGridLayout
        category = segment_factory(category_node)
        position += 1
        for offset in range(span):
            actual_nodes = data[position : position + _COLUMNS - 1]
            if len(actual_nodes) != _COLUMNS - 1 or any(
                set(cell.get("class", [])) != {"cell"} or cell.get("style") for cell in actual_nodes
            ):
                raise UnsupportedGridLayout
            actual_segments = tuple(segment_factory(cell) for cell in actual_nodes)
            first = category if offset == 0 else actual_segments[0]
            rows.append(
                Segment(
                    text=first.text,
                    source=first.source,
                    table_cells=(category.source,) + tuple(s.source for s in actual_segments),
                    table_headers=tuple(s.source for s in header_segments),
                    table_layout="grid_cells",
                )
            )
            position += _COLUMNS - 1
    return tuple(rows)


_ELEMENTOR_HEADERS = {
    ("Technique", "How It Works", "Recovery Time", "Best For"),
    ("Technique", "How It Is Performed", "Recovery Speed", "Best Suited For"),
    ("التقنية", "كيف يعمل", "Recovery Time", "الأنسب لمن"),
    ("التقنية", "كيف تتم", "سرعة التعافي", "الأنسب لمن"),
}
_ELEMENTOR_HEADER_WORDS = {value for labels in _ELEMENTOR_HEADERS for value in labels[1:]}
_CELL_TAGS = _INLINE_TAGS | {"div", "p", "h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6"}


class UnsupportedElementorLayout(ValueError):
    """A comparison candidate lacks complete, unambiguous source row relationships."""

    def __init__(self):
        super().__init__("unsupported_elementor_comparison_table")


@dataclass(frozen=True)
class ElementorComparisonGroup:
    """One explicit source category, or the matrix when there is no category label.

    Emit each group as a table with ``headers + context`` as extra source context.
    A category label is source text, not an invented fifth column. Every row retains
    all four actual header/cell spans and the original complete-row source span.
    """

    headers: tuple[Segment, ...]
    rows: tuple[Segment, ...]
    context: tuple[Segment, ...] = ()


def _elementor_text(node: Tag) -> str:
    return " ".join(node.get_text(" ", strip=False).split())


def _elementor_children(node: Tag) -> list[Tag]:
    children = []
    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            if child.strip():
                raise UnsupportedElementorLayout
        elif isinstance(child, Tag):
            children.append(child)
        else:
            raise UnsupportedElementorLayout
    return children


def _elementor_container(node: Tag) -> bool:
    return node.name == "div" and "e-con" in node.get("class", [])


def _elementor_header_candidate(node: Tag) -> bool:
    if not _elementor_container(node):
        return False
    if "table-header" in node.get("class", []):
        return True
    try:
        children = _elementor_children(node)
    except UnsupportedElementorLayout:
        return False
    labels = [_elementor_text(child) for child in children]
    # This only identifies candidates for validation. It never supplies a missing
    # header or a clinical label; malformed candidate shapes must be quarantined.
    return (
        bool(labels)
        and labels[0] in {"Technique", "التقنية"}
        and any(value in _ELEMENTOR_HEADER_WORDS for value in labels[1:])
    )


def _local_elementor_headers(node: Tag) -> list[Tag]:
    """Observed matrices start with a header row or one wrapper containing it."""
    if not _elementor_container(node):
        return []
    # Detection deliberately ignores direct text: the strict parser must reject
    # that malformed candidate rather than allowing a generic text fallback.
    children = [child for child in node.children if isinstance(child, Tag)]
    if len(children) < 2:
        return []
    first = children[0]
    if _elementor_header_candidate(first):
        return [first]
    if not _elementor_container(first):
        return []
    inner = [child for child in first.children if isinstance(child, Tag)]
    headers = [child for child in inner if _elementor_header_candidate(child)]
    # A wrapper around separate complete matrices is not itself one matrix. Let
    # the caller visit each sibling candidate, preserving their separate scopes.
    if headers and any(_local_elementor_headers(child) for child in children[1:]):
        return []
    return headers


def is_elementor_comparison(node: Tag) -> bool:
    """Detect a local explicit four-column comparison candidate, including refusals.

    Check before a generic Elementor container walk. On a positive detection,
    parsing failure must record a gap and suppress generic cell-by-cell fallback.
    No IDs, page URL, numeric token budget, or semantic similarity participates.
    """
    return bool(_local_elementor_headers(node))


def _elementor_cell(node: Tag) -> bool:
    if not _elementor_container(node) or node.get("style"):
        return False
    if node.find(class_="e-con"):
        return False
    if any(child.name not in _CELL_TAGS or child.get("style") for child in node.find_all(True)):
        return False
    # Each actual cell contains one text-editor/heading value; multiple blocks or
    # nested layout cells would hide an unresolved row/column boundary.
    if len(node.find_all(_BLOCK_TAGS)) > 1:
        return False
    return bool(_elementor_text(node))


def _elementor_spacer(node: Tag) -> bool:
    return not _elementor_text(node) and bool(
        "elementor-widget-spacer" in node.get("class", [])
        or node.find(class_="elementor-widget-spacer")
    )


def parse_elementor_comparison(
    node: Tag, segment_factory: Callable[[Tag], Segment]
) -> tuple[ElementorComparisonGroup, ...]:
    """Parse the observed local matrix, refusing incomplete or reordered layouts.

    Supported source shapes have one complete four-cell header row followed by
    four-cell data rows, directly or in bounded Elementor groups. An explicit
    ``table-section-title`` binds only its sibling row group. ``table-inner`` may
    identify a row, but its blank ``data-label`` attributes cannot invent labels.
    Repeated matrices are parsed independently and conflicting source wording
    stays distinct. The caller must retain/audit every original source occurrence.
    """
    header_nodes = _local_elementor_headers(node)
    if len(header_nodes) != 1 or node.get("style"):
        raise UnsupportedElementorLayout
    header_node = header_nodes[0]
    header_cells = _elementor_children(header_node)
    labels = tuple(_elementor_text(cell) for cell in header_cells)
    if labels not in _ELEMENTOR_HEADERS or not all(_elementor_cell(c) for c in header_cells):
        raise UnsupportedElementorLayout
    headers = tuple(segment_factory(cell) for cell in header_cells)
    collected: list[tuple[tuple[Segment, ...], Segment]] = []
    header_seen = False

    def visit(current: Tag, context: tuple[Segment, ...] = (), depth: int = 0):
        nonlocal header_seen
        if depth > 16 or len(collected) > _MAX_ROWS or current.get("style"):
            raise UnsupportedElementorLayout
        if current is header_node:
            if header_seen:
                raise UnsupportedElementorLayout
            header_seen = True
            return
        if _elementor_spacer(current):
            return
        if not _elementor_container(current) or _elementor_header_candidate(current):
            raise UnsupportedElementorLayout
        children = _elementor_children(current)
        cells = [child for child in children if _elementor_cell(child)]
        if len(cells) == len(children) and cells:
            if not header_seen or len(cells) != 4:
                raise UnsupportedElementorLayout
            values = tuple(segment_factory(cell) for cell in cells)
            row = segment_factory(current)
            if " ".join(row.text.split()) != " ".join(" ".join(v.text.split()) for v in values):
                raise UnsupportedElementorLayout
            collected.append(
                (
                    context,
                    row.model_copy(
                        update={
                            "table_headers": tuple(header.source for header in headers),
                            "table_cells": tuple(value.source for value in values),
                            "table_layout": "row",
                        }
                    ),
                )
            )
            return
        if "table-inner" in current.get("class", []):
            raise UnsupportedElementorLayout
        titles = [child for child in children if "table-section-title" in child.get("class", [])]
        if titles:
            if len(titles) != 1 or children[0] is not titles[0] or not header_seen:
                raise UnsupportedElementorLayout
            title = titles[0]
            if not _elementor_text(title) or len(title.find_all(_BLOCK_TAGS)) != 1:
                raise UnsupportedElementorLayout
            if any(n.name not in _CELL_TAGS or n.get("style") for n in title.find_all(True)):
                raise UnsupportedElementorLayout
            context = context + (segment_factory(title),)
            children = children[1:]
        if not children:
            raise UnsupportedElementorLayout
        for child in children:
            visit(child, context, depth + 1)

    visit(node)
    if not header_seen or not collected or len(collected) > _MAX_ROWS:
        raise UnsupportedElementorLayout
    groups: list[ElementorComparisonGroup] = []
    for context, row in collected:
        if groups and groups[-1].context == context:
            previous = groups[-1]
            groups[-1] = ElementorComparisonGroup(headers, previous.rows + (row,), context)
        else:
            groups.append(ElementorComparisonGroup(headers, (row,), context))
    return tuple(groups)
