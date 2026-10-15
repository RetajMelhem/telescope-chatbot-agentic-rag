"""Synthetic replay metric/dispatch guards; no real corpus/cache or services."""

from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def score_groups(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))
    from scripts.replay_evidence_assembly import score_groups as score

    return score


def witness(identity, ids, role="answer_support"):
    return SimpleNamespace(group_id=identity, chunk_ids=tuple(ids), role=role)


def case(*groups):
    return SimpleNamespace(evidence_groups=groups)


def test_presentation_k_counts_a_group_once_but_keeps_all_exact_occurrence_witnesses(score_groups):
    c = case(witness("a", ["source-b"]), witness("b", ["other"]))
    groups = [["source-a", "source-b"], ["other"]]
    assert score_groups(c, groups, k=1)["support"] == {
        "expected_groups": 2,
        "hit_groups": ["a"],
        "recall": 0.5,
    }
    assert score_groups(c, groups, k=2)["support"]["recall"] == 1


def test_alternatives_are_or_requirements_are_and_and_context_is_not_support(score_groups):
    c = case(
        witness("one", ["a", "b"]),
        witness("two", ["c"]),
        witness("scope", ["warning"], "uncertainty_context"),
    )
    scored = score_groups(c, [["a", "b"], ["warning"]], k=2)
    assert scored["support"]["recall"] == 0.5
    assert scored["context"]["recall"] == 1
    assert scored["support"]["hit_groups"] == ["one"]


def test_unlabeled_alternative_is_not_automatically_a_relevance_negative_or_gold_change(
    score_groups,
):
    c = case(witness("selected", ["preferred"]))
    result = score_groups(c, [["unlisted-validity-unknown"]], k=5)
    assert result["support"]["recall"] == 0
    assert result["context"]["recall"] is None
    assert not hasattr(result, "precision")
    assert c.evidence_groups[0].chunk_ids == ("preferred",)


def test_empty_roles_are_null_and_k_never_pads_missing_rendered_units(score_groups):
    assert score_groups(case(), [], k=20)["support"]["recall"] is None
    result = score_groups(case(witness("one", ["a"]), witness("two", ["b"])), [["a"]], k=20)
    assert result["support"]["recall"] == 0.5


@pytest.mark.parametrize("groups", [[["a", "a"]], [["a"], ["a"]], [[]]])
def test_repeated_or_empty_occurrence_membership_cannot_inflate_metrics(groups, score_groups):
    with pytest.raises(ValueError):
        score_groups(case(witness("a", ["a"])), groups, k=5)


@pytest.mark.parametrize("k", [0, -1, True, 1.5])
def test_invalid_cutoff_rejected(k, score_groups):
    with pytest.raises(ValueError):
        score_groups(case(), [], k=k)


@pytest.fixture
def replay(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))
    from scripts import replay_evidence_assembly

    return replay_evidence_assembly


def test_cache_matches_original_hosted_hash_before_returning_a_vector(tmp_path, replay):
    from telescope_rag.ingestion.indexing import EmbeddingCache

    cache = EmbeddingCache(tmp_path)
    key = "a" * 64
    cache.put(key, "synthetic", (1.0,) * 4096)
    original = replay.file_hash(tmp_path / f"{key}.json")
    assert replay.attested_vector(cache, key, "synthetic", original) == (1.0,) * 4096


def test_recomputed_self_hash_cannot_replace_original_hosted_vector(tmp_path, replay):
    import json

    from telescope_rag.ingestion.indexing import EmbeddingCache
    from telescope_rag.ingestion.models import stable_id

    cache = EmbeddingCache(tmp_path)
    key = "b" * 64
    cache.put(key, "synthetic", (1.0,) * 4096)
    path = tmp_path / f"{key}.json"
    original = replay.file_hash(path)
    changed = json.loads(path.read_bytes())
    changed["vector"][0] = 2.0
    changed["vector_hash"] = stable_id(json.dumps(changed["vector"]))
    path.write_text(json.dumps(changed), encoding="utf-8")
    assert cache.get(key, "synthetic", 4096)[0] == 2.0
    with pytest.raises(ValueError, match="differs_from_original_hosted_run"):
        replay.attested_vector(cache, key, "synthetic", original)


def test_missing_cached_vector_refuses_instead_of_dispatching(tmp_path, replay):
    from telescope_rag.ingestion.indexing import EmbeddingCache

    with pytest.raises(ValueError, match="differs_from_original_hosted_run"):
        replay.attested_vector(EmbeddingCache(tmp_path), "c" * 64, "synthetic", "d" * 64)


def test_cache_mutation_during_read_is_rejected(tmp_path, replay):
    key = "a" * 64
    path = tmp_path / f"{key}.json"
    path.write_text("synthetic-original", encoding="utf-8")
    original = replay.file_hash(path)

    def change_during_read(*_):
        path.write_text("synthetic-replacement", encoding="utf-8")
        return (1.0,) * 4096

    cache = SimpleNamespace(directory=tmp_path, get=change_during_read)
    with pytest.raises(ValueError, match="changed_during_read"):
        replay.attested_vector(cache, key, "synthetic", original)


def test_original_cache_still_checks_configuration_and_dimensions(tmp_path, replay):
    from telescope_rag.ingestion.indexing import EmbeddingCache

    cache = EmbeddingCache(tmp_path)
    key = "a" * 64
    cache.put(key, "synthetic-original", (1.0,) * 4096)
    original = replay.file_hash(tmp_path / f"{key}.json")
    with pytest.raises(ValueError, match="invalid_embedding_cache"):
        replay.attested_vector(cache, key, "synthetic-other", original)


@pytest.mark.parametrize("change", ["reference_bytes", "prepared_digest"])
def test_historical_receipt_and_source_binding_fail_closed(tmp_path, monkeypatch, replay, change):
    import json

    path = tmp_path / replay.CORPUS_PLAN
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"prepared_digest": "synthetic-original"}), encoding="utf-8")
    monkeypatch.setattr(replay, "REFERENCE_SHA256", {replay.CORPUS_PLAN: replay.file_hash(path)})
    if change == "reference_bytes":
        path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="reference_changed|configuration_source_mismatch"):
        replay.historical_bindings(tmp_path, "synthetic-other")
