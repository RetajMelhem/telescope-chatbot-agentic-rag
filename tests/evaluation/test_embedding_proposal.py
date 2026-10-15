"""Synthetic boundary cases for offline arithmetic; no tokenizer/provider/service calls."""

from pathlib import Path

import pytest


@pytest.fixture
def proposal(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))
    from scripts import plan_embedding_candidate

    return plan_embedding_candidate


def rows(*tokens):
    return [{"input_key": str(i), "tokens": count} for i, count in enumerate(tokens)]


def test_fixed_windows_and_token_subbatches_preserve_order_and_every_input_once(proposal):
    # Collapsing the final singleton into a preceding window would undercount the
    # request bound for the real fixed-window embedder when caches remove inputs.
    result = proposal.batch_plan(
        rows(6, 4, 3, 3, 2), batch_size=2, max_batch_tokens=8, max_input_tokens=18
    )
    assert [b["input_count"] for b in result] == [1, 1, 2, 1]
    assert [b["input_tokens"] for b in result] == [6, 4, 6, 2]
    assert [r["input_key"] for b in result for r in b["inputs"]] == ["0", "1", "2", "3", "4"]


@pytest.mark.parametrize("count", [0, -1, True, "6", 9])
def test_invalid_or_oversized_input_cannot_be_planned(proposal, count):
    with pytest.raises(ValueError, match="token_count_invalid"):
        proposal.batch_plan(rows(count), batch_size=2, max_batch_tokens=8, max_input_tokens=100)


@pytest.mark.parametrize("batch_size", [0, 33, True, 1.5])
def test_invalid_batch_window_rejected(proposal, batch_size):
    with pytest.raises(ValueError, match="batch_limits_invalid"):
        proposal.batch_plan(
            rows(1), batch_size=batch_size, max_batch_tokens=8, max_input_tokens=100
        )


def test_exact_budget_is_allowed_but_one_token_less_rejected(proposal):
    assert (
        len(proposal.batch_plan(rows(5, 3), batch_size=2, max_batch_tokens=8, max_input_tokens=8))
        == 1
    )
    with pytest.raises(ValueError, match="input_budget_exceeded"):
        proposal.batch_plan(rows(5, 3), batch_size=2, max_batch_tokens=8, max_input_tokens=7)


def test_duplicate_input_keys_and_empty_inventory_cannot_hide_extra_inputs(proposal):
    with pytest.raises(ValueError, match="duplicate_input_key"):
        proposal.batch_plan(
            [{"input_key": "same", "tokens": 1}] * 2,
            batch_size=2,
            max_batch_tokens=8,
            max_input_tokens=100,
        )
    with pytest.raises(ValueError, match="batch_limits_invalid"):
        proposal.batch_plan([], batch_size=2, max_batch_tokens=8, max_input_tokens=100)
