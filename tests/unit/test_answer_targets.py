"""Literal reference contracts, not a semantic target classifier."""

import json

import pytest
from test_request_anchors import anchored_part, bindings

from telescope_rag.graph.anchoring import AnchoredPlannerReply, AnchorError, resolve_anchored_plan
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.graph.target_context import bind_answer_targets


def resolve(query, parts, **fields):
    request = WorkflowRequest(query=query, **fields)
    reply = AnchoredPlannerReply(language="en", parts=tuple(parts))
    derived, anchors = resolve_anchored_plan(reply, request, "issued")
    targets = bind_answer_targets(reply, anchors)
    plan = bindings().validate(derived, request, "issued", max_parts=4)
    return targets, plan


@pytest.mark.parametrize(
    "reference,target",
    [
        ("The named page:", " report its fee notice."),
        ("الصفحة المذكورة:", " انقل تنبيه الرسوم."),
        ("الصفحة اللي حكينا عنها:", " احكيلي تنبيه الكشفية."),
        ("😀 e\u0301 source:", " retain ١٠:٣٠ literally."),
    ],
)
def test_reference_is_separate_and_literal_in_search_and_receipt(reference, target):
    whole = reference + target
    parts = (anchored_part(whole, reference_text=reference, retrieval_query=whole),)
    targets, plan = resolve(whole, parts)
    assert targets[0].target.quote == whole and targets[0].reference_text == reference
    assert targets[0].part_id == plan.assembly_request.parts[0].part_id
    assert not plan.semantic_interpretation_verified


def test_same_literal_source_context_can_be_shared_without_copying_another_question():
    first = "The named page: am I eligible?"
    second = " What fee notice does it publish?"
    targets, plan = resolve(
        first + second,
        (
            anchored_part(first, intended_use="consultation_eligibility"),
            anchored_part(
                second,
                intended_use="service_description",
                reference_text="The named page",
                retrieval_query="The named page" + second,
            ),
        ),
    )
    assert targets[1].target.quote == second
    assert "am I eligible" not in targets[1].target.quote
    assert targets[1].reference_text == "The named page"
    assert len(plan.retrieval_queries) == 2


def test_history_reference_keeps_exact_selected_context_without_becoming_target():
    query = "What is the posted role?"
    targets, _ = resolve(
        query,
        (
            anchored_part(
                query,
                reference_text="Synthetic Doctor A",
                history_indices=(0,),
                retrieval_query="Synthetic Doctor A " + query,
            ),
        ),
        history=({"role": "user", "content": "Synthetic Doctor A"},),
    )
    assert targets[0].target.quote == query and targets[0].history_indices == (0,)
    assert targets[0].reference_text == "Synthetic Doctor A"


def test_selected_reference_cannot_silently_disappear_from_search():
    query = "What is its role?"
    with pytest.raises(AnchorError, match="retrieval_query_lost_reference_context"):
        resolve(
            query,
            (anchored_part(query, reference_text="Synthetic Doctor A", history_indices=(0,)),),
            history=({"role": "user", "content": "Synthetic Doctor A"},),
        )


@pytest.mark.parametrize("selected", [(), (1,)])
def test_unselected_or_invented_history_context_is_still_rejected(selected):
    query = "What is its role?"
    with pytest.raises(ValueError):
        resolve(
            query,
            (
                anchored_part(
                    query,
                    reference_text="Synthetic Doctor A",
                    history_indices=selected,
                    retrieval_query="Synthetic Doctor A " + query,
                ),
            ),
            history=({"role": "user", "content": "Synthetic Doctor A"},),
        )


def test_metadata_does_not_claim_or_syntactically_guess_correct_semantic_purpose():
    query = "Synthetic combined purpose, deliberately labelled by a fake planner."
    targets, plan = resolve(query, (anchored_part(query, intended_use="service_description"),))
    assert targets[0].target.quote == query
    assert plan.assembly_request.parts[0].intended_use == "service_description"
    assert not plan.semantic_interpretation_verified
    assert query not in repr(targets[0])


def test_inventory_or_target_mismatch_does_not_issue_ambiguous_receipts():
    query = "Synthetic target."
    reply = AnchoredPlannerReply(language="en", parts=(anchored_part(query),))
    _, anchors = resolve_anchored_plan(reply, WorkflowRequest(query=query), "issued")
    with pytest.raises(AnchorError, match="inventory_mismatch"):
        bind_answer_targets(reply, ())
    changed = AnchoredPlannerReply.model_validate_json(
        json.dumps(reply.model_dump(mode="json")).replace("Synthetic target.", "Other target.")
    )
    with pytest.raises(AnchorError, match="anchor_mismatch"):
        bind_answer_targets(changed, anchors)
