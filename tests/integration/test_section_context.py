"""Synthetic source structure tests, not semantic certification of clinical claims."""

import pytest
from test_offline_workflow import catalog, source

from telescope_rag.retrieval.section_context import section_context


def chunk(index, path, **kwargs):
    return source(index, "Synthetic contextual passage.", document="main", **kwargs).model_copy(
        update={"section_path": path}
    )


def test_ancestor_context_is_separate_and_deduplicated_for_sibling_targets():
    parent = chunk(1, ("Services",))
    children = (chunk(2, ("Services", "A")), chunk(3, ("Services", "B")))
    evidence = catalog(parent, *children)
    assert section_context(
        evidence, tuple(c.chunk_id for c in children), allowed=frozenset(evidence.chunks), limit=2
    ) == (parent.chunk_id,)
    assert evidence.chunks[parent.chunk_id].retrieval_text == parent.retrieval_text


@pytest.mark.parametrize("difference", ["document", "owner", "language", "canonical_owner"])
def test_same_heading_does_not_transfer_another_sources_context(difference):
    child = chunk(1, ("Services", "A"))
    parent = chunk(2, ("Services",))
    changes = {
        "document": {"document_id": "other", "canonical_url": "https://telescopecenter.com/other/"},
        "owner": {"doctor_id": "other", "doctor_name": "Other owner"},
        "language": {"language": "ar"},
        "canonical_owner": {"canonical_doctor_id": "other", "canonical_doctor_name": "Other"},
    }
    parent = parent.model_copy(update=changes[difference])
    evidence = catalog(parent, child)
    assert (
        section_context(evidence, (child.chunk_id,), allowed=frozenset(evidence.chunks), limit=2)
        == ()
    )


@pytest.mark.parametrize("missing", [False, True])
def test_oversized_or_scoped_out_nearest_context_is_not_partially_offered(missing):
    roots = (chunk(1, ("Root",)),)
    parents = tuple(chunk(i, ("Root", "Services")) for i in (2, 3, 4))
    child = chunk(5, ("Root", "Services", "A"))
    evidence = catalog(*roots, *parents, child)
    allowed = frozenset(evidence.chunks) - ({parents[0].chunk_id} if missing else set())
    assert section_context(evidence, (child.chunk_id,), allowed=allowed, limit=2) == ()


@pytest.mark.parametrize("limit", [-1, True, 3, "2"])
def test_context_limit_is_strict(limit):
    item = chunk(1, ("Root",))
    evidence = catalog(item)
    with pytest.raises(ValueError, match="section_context_limit_invalid"):
        section_context(evidence, (item.chunk_id,), allowed=frozenset(evidence.chunks), limit=limit)


def test_unissued_targets_or_scope_are_rejected():
    item = chunk(1, ("Root",))
    evidence = catalog(item)
    with pytest.raises(ValueError, match="section_context_scope_invalid"):
        section_context(evidence, (item.chunk_id,), allowed=frozenset({"unknown"}), limit=1)
