"""Small, fail-closed adapters for explicitly supported source layouts.

CSS grids are not HTML tables. Only the observed direct-cell layout with five
explicit headers and a first-column category spanning complete consecutive rows
is supported here. No computed style, text similarity, or inferred cell pairing
establishes a relationship. Callers must record a gap when this parser refuses.
"""

import re
from collections.abc import Callable

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
