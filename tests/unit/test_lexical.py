"""Pure synthetic lexical comparison checks; no provider, corpus or network."""

from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError
from math import log

import pytest

from telescope_rag.retrieval import lexical
from telescope_rag.retrieval.lexical import BM25Index, LexicalHit, reciprocal_rank_fusion


def test_bm25_matches_hand_calculated_term_frequency_and_length_normalization():
    index = BM25Index({"a": "laser laser eye", "b": "laser clinic", "c": "skin"})
    hits = index.search("laser")
    idf = log(1 + 1.5 / 2.5)
    assert [hit.chunk_id for hit in hits] == ["a", "b"]
    assert hits[0].score == pytest.approx(idf * 2 * 2.2 / (2 + 1.2 * (0.25 + 0.75 * 3 / 2)))
    assert hits[1].score == pytest.approx(idf)
    assert index.search("laser laser")[0].score == pytest.approx(2 * hits[0].score)


def test_all_document_matches_have_positive_idf_and_stable_occurrence_order():
    source_occurrences = {"owner-b": "eye clinic", "owner-a": "eye clinic"}
    hits = BM25Index(source_occurrences).search("eye")
    assert hits == (
        LexicalHit("owner-a", pytest.approx(log(1.2))),
        LexicalHit("owner-b", pytest.approx(log(1.2))),
    )
    assert len(BM25Index(source_occurrences).search("eye", limit=1)) == 1


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("Published HOURS", "hours"),
        ("café", "cafe\u0301"),
        ("Straße", "STRASSE"),
        ("عيون،جلدية", "جلدية"),
        ("بدي أعرف الدوام", "بدي"),
        ("بدّيك تفحص", "بدّيك"),
        ("عمره ١٢ سنة", "١٢"),
        ("Motasim Masalmeh", "MOTASIM"),
        ("متاح 12 يوما", "12"),
    ],
)
def test_unicode_literal_analysis(text, query):
    assert [hit.chunk_id for hit in BM25Index({"one": text}).search(query)] == ["one"]


@pytest.mark.parametrize(("text", "query"), [("إجراء", "اجراء"), ("١٢", "12"), ("مَرحبا", "مرحبا")])
def test_no_arabic_letter_folding_diacritic_stripping_or_number_translation(text, query):
    assert BM25Index({"one": text}).search(query) == ()


def test_negation_and_common_terms_are_not_removed_as_stopwords():
    index = BM25Index({"en": "not", "ar": "لا", "ar-jo": "مش", "other": "yes"})
    for query, identity in [("not", "en"), ("لا", "ar"), ("مش", "ar-jo")]:
        assert [hit.chunk_id for hit in index.search(query)] == [identity]


def test_tokenless_docs_queries_and_nonmatching_queries_do_not_invent_hits():
    index = BM25Index({"blank": "", "punctuation": "---", "fact": "doctor hours"})
    for query in ["", "   ", "?!", "price"]:
        assert index.search(query) == ()
    assert BM25Index({"blank": ""}).search("doctor") == ()


def test_scope_is_applied_before_cutoff_and_keeps_distinct_owners():
    index = BM25Index({"foreign": "laser", "owner-a": "laser clinic", "owner-b": "laser clinic"})
    assert index.search("laser", limit=1)[0].chunk_id == "foreign"
    assert (
        index.search("laser", limit=1, allowed_chunk_ids=frozenset({"owner-b"}))[0].chunk_id
        == "owner-b"
    )
    assert index.search("laser", allowed_chunk_ids=frozenset()) == ()
    assert len(index.search("laser", allowed_chunk_ids=frozenset({"owner-a", "owner-b"}))) == 2


@pytest.mark.parametrize("scope", [[], {"owner"}, frozenset({"unissued"})])
def test_invalid_lexical_scope_is_rejected(scope):
    with pytest.raises(ValueError, match="lexical_scope_invalid"):
        BM25Index({"owner": "laser"}).search("laser", allowed_chunk_ids=scope)


def test_mapping_mutation_cannot_change_the_built_index():
    documents = {"a": "hours"}
    index = BM25Index(documents)
    documents["a"] = "surgery"
    documents["b"] = "hours"
    assert [hit.chunk_id for hit in index.search("hours")] == ["a"]
    assert index.search("surgery") == ()
    with pytest.raises(FrozenInstanceError):
        index.search("hours")[0].score = 0


def test_analysis_does_not_normalize_or_merge_source_occurrence_identities():
    identities = {"café": "doctor", "cafe\u0301": "doctor"}
    hits = BM25Index(identities).search("doctor")
    assert len(hits) == 2
    assert {hit.chunk_id for hit in hits} == set(identities)


@pytest.mark.parametrize("value", [None, [], {}, {"one": None}, {1: "doctor"}])
def test_invalid_document_mappings_or_types_are_rejected(value):
    with pytest.raises(ValueError):
        BM25Index(value)


@pytest.mark.parametrize("identity", ["", " ", " owner", "owner ", "owner\nnext", "x" * 257])
def test_malformed_identity_is_rejected_in_both_apis(identity):
    with pytest.raises(ValueError):
        BM25Index({identity: "fact"})
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[identity]])


def test_duplicate_mapping_occurrences_and_misreported_size_are_rejected():
    class BrokenMapping(Mapping):
        def __getitem__(self, key):
            return "fact"

        def __iter__(self):
            return iter(["same", "same"])

        def __len__(self):
            return 2

    with pytest.raises(ValueError, match="duplicate"):
        BM25Index(BrokenMapping())

    class WrongSize(BrokenMapping):
        def __iter__(self):
            return iter(["one"])

    with pytest.raises(ValueError, match="inconsistent"):
        BM25Index(WrongSize())


def test_document_and_total_corpus_byte_bounds(monkeypatch):
    monkeypatch.setattr(lexical, "MAX_DOCUMENT_BYTES", 8)
    monkeypatch.setattr(lexical, "MAX_CORPUS_BYTES", 12)
    assert BM25Index({"one": "عيون"}).search("عيون")
    with pytest.raises(ValueError, match="document text exceeds"):
        BM25Index({"one": "عيون عيون"})
    with pytest.raises(ValueError, match="corpus text exceeds"):
        BM25Index({"one": "عيون", "two": "عيون"})
    monkeypatch.setattr(lexical, "MAX_DOCUMENTS", 1)
    with pytest.raises(ValueError):
        BM25Index({"one": "a", "two": "b"})


@pytest.mark.parametrize("query", [None, 12, [], "a" * 16_001, "\ud800"])
def test_invalid_or_oversized_query(query):
    with pytest.raises(ValueError):
        BM25Index({"one": "fact"}).search(query)


def test_invalid_document_unicode():
    with pytest.raises(ValueError, match="valid Unicode"):
        BM25Index({"one": "\ud800"})


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "20", None])
def test_result_limits_are_validated(limit):
    with pytest.raises(ValueError):
        BM25Index({"one": "fact"}).search("fact", limit=limit)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["one"]], limit=limit)


def test_rrf_matches_hand_calculated_one_based_equal_weight_formula():
    hits = reciprocal_rank_fusion([["b", "a"], ["c", "a"]], rank_constant=60)
    assert [hit.chunk_id for hit in hits] == ["a", "b", "c"]
    assert hits[0].score == pytest.approx(2 / 62)
    assert hits[1].score == hits[2].score == pytest.approx(1 / 61)
    assert reciprocal_rank_fusion([["b", "a"], ["c", "a"]], limit=1) == hits[:1]


def test_rrf_preserves_separate_identical_text_occurrences_and_stable_ties():
    assert [hit.chunk_id for hit in reciprocal_rank_fusion([["owner-b"], ["owner-a"]])] == [
        "owner-a",
        "owner-b",
    ]
    assert reciprocal_rank_fusion([]) == reciprocal_rank_fusion([[], []]) == ()


@pytest.mark.parametrize(
    "rankings",
    [
        None,
        "abc",
        ["abc"],
        [["same", "same"]],
        [[None]],
        [[1]],
        [["x"]] * 9,
        [[str(i) for i in range(101)]],
    ],
)
def test_rrf_rejects_malformed_or_unbounded_input(rankings):
    with pytest.raises(ValueError):
        reciprocal_rank_fusion(rankings)


def test_rrf_actual_iteration_remains_bounded_when_sequence_misreports_its_size():
    class WrongSize(Sequence):
        def __init__(self, items):
            self.items = items

        def __getitem__(self, index):
            return self.items[index]

        def __len__(self):
            return 0

    with pytest.raises(ValueError, match="too many rankings"):
        reciprocal_rank_fusion(WrongSize([[]] * 9))
    with pytest.raises(ValueError, match="too many identities"):
        reciprocal_rank_fusion([WrongSize([str(index) for index in range(101)])])


@pytest.mark.parametrize("constant", [0, -1, 10_001, True, 1.5, "60", None])
def test_rrf_rejects_invalid_rank_constant(constant):
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["one"]], rank_constant=constant)
