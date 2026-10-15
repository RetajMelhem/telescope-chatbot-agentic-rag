"""Pure cached-vector ranking tests using synthetic sources and hand calculations."""

import math
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID

import pytest

from telescope_rag.ingestion.models import PreparedChunk, SourceSpan
from telescope_rag.retrieval.cached_dense import CachedDenseRanker


def chunk(chunk_id="a", *, index=1, owner="Doctor A", text="Synthetic specialty"):
    source = SourceSpan(
        block_id=f"source-{index}", locator="main > p", original_text=text, end=len(text)
    )
    return PreparedChunk(
        chunk_id=chunk_id,
        point_id=str(UUID(int=index)),
        document_id=f"document-{index}",
        canonical_url=f"https://telescopecenter.com/synthetic-{index}/",
        page_title="Synthetic doctors",
        snapshot_id="synthetic-cache-snapshot",
        fetched_at=datetime(2026, 10, 16, tzinfo=UTC),
        parent_block_id=f"owner-{index}",
        block_type="doctor",
        language="en",
        section_path=("Synthetic specialty",),
        doctor_id=owner,
        doctor_name=owner,
        source_issue_codes=("synthetic_issue",),
        admission_policy_hash="synthetic-admission",
        source_spans=(source,),
        original_text=text,
        retrieval_text=text,
        content_hash=f"synthetic-content-{index}",
        tokenizer_version="synthetic-counter",
        embedding_format_version="synthetic-format",
        embedding_format_hash="synthetic-format-hash",
        embedding_ready=True,
    )


def ranker(vectors, *, chunks=None, dimensions=2):
    if chunks is None:
        chunks = {
            chunk_id: chunk(chunk_id, index=index)
            for index, chunk_id in enumerate(vectors, start=1)
        }
    return CachedDenseRanker(chunks, vectors, expected_dimensions=dimensions)


def test_cosine_hand_calculation_normalization_negative_and_zero_scores():
    ranked = ranker({"positive": (3, 4), "negative": (-3, -4), "orthogonal": (0, 20)}).search(
        (10, 0), limit=3
    )
    assert [hit.chunk_id for hit in ranked] == ["positive", "orthogonal", "negative"]
    assert [hit.score for hit in ranked] == pytest.approx([0.6, 0.0, -0.6])
    assert all(hit.occurrence_ids == (hit.chunk_id,) for hit in ranked)


def test_query_and_document_scaling_do_not_change_cosine_direction():
    index = ranker({"a": (3, 4), "b": (30, 40), "c": (-300, -400)})
    assert index.search((1, 2)) == index.search((1000, 2000))
    hits = index.search((3, 4))
    assert [hit.chunk_id for hit in hits] == ["a", "b", "c"]
    assert [hit.score for hit in hits] == pytest.approx([1, 1, -1])


def test_finite_extreme_and_subnormal_coordinates_normalize_stably():
    large = ranker({"a": (3e307, 4e307)})
    assert large.search((1e308, 1e308))[0].score == pytest.approx(7 / (math.sqrt(2) * 5))
    assert ranker({"a": (5e-324, 0)}).search((5e-324, 0))[0].score == 1.0


def test_equal_scores_tie_by_chunk_id_independently_of_input_order():
    first = ranker({"z": (1, 0), "a": (1, 0), "m": (1, 0)})
    second = ranker({"m": (1, 0), "z": (1, 0), "a": (1, 0)})
    assert [hit.chunk_id for hit in first.search((1, 0))] == ["a", "m", "z"]
    assert first.search((1, 0)) == second.search((1, 0))


def test_complete_ranking_precedes_group_selection_and_all_occurrences_survive():
    vectors = {
        "a1": (1, 0),
        "a2": (1, 0),
        "a3": (0.99, 0.01),
        "b": (0.8, 0.6),
        "c": (0, 1),
        "a-tail": (-1, 0),
    }
    chunks = {
        chunk_id: chunk(chunk_id, index=i, owner="A" if chunk_id.startswith("a") else chunk_id)
        for i, chunk_id in enumerate(vectors, start=1)
    }
    index = ranker(vectors, chunks=chunks)
    calls = []

    def exact_key(item):
        calls.append(item.chunk_id)
        return item.doctor_id

    hits = index.search((1, 0), limit=2, group_key=exact_key)
    assert [hit.chunk_id for hit in hits] == ["a1", "b"]
    assert hits[0].occurrence_ids == ("a-tail", "a1", "a2", "a3")
    assert hits[1].occurrence_ids == ("b",)
    assert sorted(calls) == sorted(vectors)
    # Truncating an occurrence pool first would yield only the repeated A group.
    assert [hit.chunk_id for hit in index.search((1, 0), limit=2)] == ["a1", "a2"]


def test_group_representative_uses_best_score_then_id_and_preserves_all_ids():
    chunks = {
        "a": chunk("a", index=1, owner="A"),
        "z": chunk("z", index=2, owner="A"),
        "b": chunk("b", index=3, owner="B"),
    }
    hits = ranker({"a": (0, 1), "z": (1, 0), "b": (0.5, 0.5)}, chunks=chunks).search(
        (1, 0), group_key=lambda item: item.doctor_id
    )
    assert [hit.chunk_id for hit in hits] == ["z", "b"]
    assert hits[0].occurrence_ids == ("a", "z")
    assert hits[0].score == 1.0


def test_same_specialty_different_owners_remain_distinct_under_explicit_owner_key():
    chunks = {
        "a": chunk("a", index=1, owner="Doctor A", text="Ophthalmology Specialist"),
        "b": chunk("b", index=2, owner="Doctor B", text="Ophthalmology Specialist"),
    }
    index = ranker({"a": (1, 0), "b": (1, 0)}, chunks=chunks)
    hits = index.search((1, 0), group_key=lambda item: (item.retrieval_text, item.doctor_id))
    assert [hit.occurrence_ids for hit in hits] == [("a",), ("b",)]
    # No grouping is inferred; even byte-identical vectors remain separate by default.
    assert len(index.search((1, 0))) == 2


def test_caller_explicit_grouping_policy_is_used_without_semantic_substitution():
    index = ranker({"a": (1, 0), "b": (0, 1)})
    grouped = index.search((1, 0), group_key=lambda item: "explicit-whole-inventory-group")
    assert len(grouped) == 1
    assert grouped[0].occurrence_ids == ("a", "b")


def test_input_vector_mapping_and_prepared_model_are_copied():
    original = chunk()
    chunks = {"a": original}
    vector = [1.0, 0.0]
    vectors = {"a": vector}
    index = ranker(vectors, chunks=chunks)
    vector[:] = [-1, 0]
    vectors.clear()
    chunks.clear()
    object.__setattr__(original, "doctor_id", "mutated-outside-ranker")
    seen = []
    hits = index.search(
        (1, 0), group_key=lambda item: seen.append(item.doctor_id) or item.doctor_id
    )
    assert hits[0].score == 1.0
    assert seen == ["Doctor A"]


def test_query_is_not_retained_and_outputs_are_immutable():
    index = ranker({"a": (1, 0), "b": (-1, 0)})
    query = [1, 0]
    hits = index.search(query)
    query[0] = -1
    assert hits[0].chunk_id == "a"
    assert index.search(query)[0].chunk_id == "b"
    with pytest.raises(FrozenInstanceError):
        hits[0].score = 2
    with pytest.raises(TypeError):
        hits[0].occurrence_ids[0] = "forged"


@pytest.mark.parametrize("dimensions", [0, -1, 4097, True, 2.0, "2", None])
def test_invalid_expected_dimensions(dimensions):
    with pytest.raises(ValueError, match="invalid_dimensions"):
        ranker({"a": (1, 0)}, dimensions=dimensions)


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.0, "1", None])
def test_invalid_result_limits(limit):
    with pytest.raises(ValueError, match="invalid_limit"):
        ranker({"a": (1, 0)}).search((1, 0), limit=limit)


def test_production_dimension_default_and_maximum_result_limit():
    item = chunk()
    index = CachedDenseRanker({"a": item}, {"a": [1.0] * 4096})
    assert index.search([2.0] * 4096, limit=100)[0].score == pytest.approx(1)
    with pytest.raises(ValueError, match="invalid_vector"):
        CachedDenseRanker({"a": item}, {"a": [1.0] * 4097})


@pytest.mark.parametrize(
    "vector",
    [
        [],
        [1],
        [1, 0, 0],
        [0, 0],
        [True, 0],
        ["1", 0],
        [None, 0],
        [float("nan"), 0],
        [float("inf"), 0],
        [float("-inf"), 0],
        [10**1000, 0],
        "10",
        b"10",
        bytearray(b"10"),
        {0: 1, 1: 0},
        None,
    ],
)
def test_invalid_vectors_rejected_for_both_document_and_query(vector):
    with pytest.raises(ValueError, match="invalid_vector"):
        ranker({"a": vector})
    with pytest.raises(ValueError, match="invalid_vector"):
        ranker({"a": (1, 0)}).search(vector)


@pytest.mark.parametrize(
    "chunks,vectors",
    [
        ({}, {}),
        ({"a": chunk()}, {}),
        ({}, {"a": (1, 0)}),
        ({"a": chunk()}, {"b": (1, 0)}),
        ({"a": chunk()}, {"a": (1, 0), "b": (1, 0)}),
        ({"a": chunk(), "b": chunk("b", index=2)}, {"a": (1, 0)}),
        (None, {"a": (1, 0)}),
        ({"a": chunk()}, None),
    ],
)
def test_rejects_incomplete_foreign_and_empty_vector_inventory(chunks, vectors):
    with pytest.raises(ValueError, match="inventory"):
        CachedDenseRanker(chunks, vectors, expected_dimensions=2)


@pytest.mark.parametrize("identity", ["", " a", "a ", "a\n", "x" * 257, 1, True])
def test_rejects_malformed_or_nonliteral_inventory_identity(identity):
    with pytest.raises(ValueError, match="identity"):
        CachedDenseRanker({identity: chunk()}, {identity: (1, 0)}, expected_dimensions=2)


def test_rejects_forged_chunk_key_and_duplicate_point_id():
    with pytest.raises(ValueError, match="invalid_chunk"):
        ranker({"forged": (1, 0)}, chunks={"forged": chunk("actual")})
    with pytest.raises(ValueError, match="invalid_chunk"):
        ranker(
            {"a": (1, 0), "b": (0, 1)},
            chunks={"a": chunk("a"), "b": chunk("b")},
        )


@pytest.mark.parametrize(
    "field",
    [
        "snapshot_id",
        "preparation_version",
        "tokenizer_version",
        "embedding_format_version",
        "embedding_format_hash",
        "admission_policy_hash",
    ],
)
def test_mixed_snapshot_or_embedding_configuration_is_rejected(field):
    first = chunk("a", index=1)
    second = chunk("b", index=2).model_copy(update={field: "different"})
    with pytest.raises(ValueError, match="mixed_snapshot_or_configuration"):
        ranker({"a": (1, 0), "b": (0, 1)}, chunks={"a": first, "b": second})


def test_mixed_embedding_readiness_is_rejected():
    chunks = {
        "a": chunk("a", index=1),
        "b": chunk("b", index=2).model_copy(update={"embedding_ready": False}),
    }
    with pytest.raises(ValueError, match="mixed_snapshot_or_configuration"):
        ranker({"a": (1, 0), "b": (0, 1)}, chunks=chunks)


def test_oversized_mapping_rejects_without_iteration():
    class Oversized(Mapping):
        def __len__(self):
            return 10001

        def __iter__(self):
            pytest.fail("oversized mappings must not be consumed")

        def __getitem__(self, key):
            pytest.fail("oversized mappings must not be consumed")

    with pytest.raises(ValueError, match="invalid_inventory"):
        CachedDenseRanker(Oversized(), Oversized(), expected_dimensions=2)


@pytest.mark.parametrize("key", [False, 1, "text", lambda item: []])
def test_invalid_or_unhashable_group_key_rejects(key):
    with pytest.raises(ValueError, match="invalid_group_key"):
        ranker({"a": (1, 0)}).search((1, 0), group_key=key)


def test_group_key_failure_is_not_silently_changed_to_no_grouping():
    def bad_key(item):
        raise RuntimeError("synthetic sensitive caller detail")

    with pytest.raises(ValueError, match="^cached_dense_invalid_group_key$") as caught:
        ranker({"a": (1, 0)}).search((1, 0), group_key=bad_key)
    assert caught.value.__suppress_context__
