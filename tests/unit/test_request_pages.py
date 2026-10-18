"""Request-local page reuse preserves exact scope and lets normal packing enforce limits."""

import pytest
from test_evidence_assembly import SyntheticCounter, catalog, chunk

from telescope_rag.retrieval.assembly import AssemblyRequest, RequestPart, SourceScope
from telescope_rag.retrieval.request_pages import reuse_page_candidates


def fixture(*, scope=None, state="public", intended_use="profile_detail", flags=(), language="en"):
    first = chunk(1, document="shared", owner="a")
    second = chunk(2, document="shared", owner="b", flags=flags, language=language)
    other = chunk(3, document="other", owner="c")
    evidence = catalog(first, second, other)
    request = AssemblyRequest(
        original_query="A B",
        parts=(
            RequestPart(part_id="p1", start=0, end=1),
            RequestPart(
                part_id="p2",
                start=2,
                end=3,
                scope=scope or SourceScope(),
                state=state,
                reason="synthetic" if state != "public" else "",
                intended_use=intended_use,
            ),
        ),
    )
    rows = {
        "p1": (first.chunk_id, second.chunk_id),
        "p2": (first.chunk_id,) if state == "public" else (),
    }
    return evidence, request, rows, (first, second, other)


def test_same_page_reuse_keeps_rank_prefix_and_separate_owners():
    evidence, request, rows, items = fixture()
    result = reuse_page_candidates(evidence, request, rows, shareable_parts=frozenset({"p2"}))
    assert result["p1"] == rows["p1"]
    assert result["p2"] == (items[0].chunk_id, items[1].chunk_id)
    assert rows["p2"] == (items[0].chunk_id,)  # Input rankings stay unchanged.
    packed = evidence.assemble(
        request, result, counter=SyntheticCounter(), max_tokens=100000, token_basis="synthetic_test"
    )
    assert len(packed.groups) == 2
    assert {g.occurrences[0].doctor_id for g in packed.groups} == {"a", "b"}
    assert all(dict(g.part_occurrences)["p2"] for g in packed.groups)


@pytest.mark.parametrize(
    "scope,state,intended_use,flags,language",
    [
        (SourceScope(owner_id="a"), "public", "profile_detail", (), "en"),
        (SourceScope(language="en"), "public", "profile_detail", (), "ar"),
        (SourceScope(block_types=("section",)), "public", "profile_detail", (), "en"),
        (
            SourceScope(document_ids=("shared",), complete=True),
            "public",
            "profile_detail",
            (),
            "en",
        ),
        (SourceScope(), "excluded", "profile_detail", (), "en"),
        (SourceScope(), "clarification_required", "profile_detail", (), "en"),
        (
            SourceScope(),
            "public",
            "profile_detail",
            ("name_only_profile_no_specialty_or_biography_claim",),
            "en",
        ),
    ],
)
def test_reuse_cannot_cross_owner_language_type_complete_or_source_policy(
    scope,
    state,
    intended_use,
    flags,
    language,
):
    evidence, request, rows, _ = fixture(
        scope=scope, state=state, intended_use=intended_use, flags=flags, language=language
    )
    assert reuse_page_candidates(evidence, request, rows, shareable_parts=frozenset({"p2"})) == rows


def test_reuse_does_not_introduce_a_page_or_override_disabled_operations():
    evidence, request, rows, items = fixture()
    assert reuse_page_candidates(evidence, request, rows, shareable_parts=frozenset()) == rows
    rows["p2"] = (items[2].chunk_id,)
    assert reuse_page_candidates(evidence, request, rows, shareable_parts=frozenset({"p2"})) == rows
    rows["p2"] = ()
    assert reuse_page_candidates(evidence, request, rows, shareable_parts=frozenset({"p2"})) == rows


@pytest.mark.parametrize("bad", [("unknown",), ("chunk-1", "chunk-1"), "chunk-1"])
def test_invalid_retrieval_inventory_is_not_hidden_by_reuse(bad):
    evidence, request, rows, _ = fixture()
    rows["p1"] = bad
    with pytest.raises(ValueError, match="inventory_invalid"):
        reuse_page_candidates(evidence, request, rows, shareable_parts=frozenset({"p2"}))
