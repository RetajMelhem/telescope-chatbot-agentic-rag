"""Explicit target/context projection; literal checks never certify purpose selection."""

from telescope_rag.graph.anchoring import AnchoredPlannerReply, AnchorError
from telescope_rag.graph.contracts import PartAnchorBinding, PartAnswerTarget


def bind_answer_targets(
    proposal: AnchoredPlannerReply, anchors: tuple[PartAnchorBinding, ...]
) -> tuple[PartAnswerTarget, ...]:
    """Call only with resolved anchors, then retain SourceBindings validation.

    No context is appended, normalized, classified or moved into an answer target.
    The model still decides the purpose and references; this checks literal retention.
    """
    if len(proposal.parts) != len(anchors):
        raise AnchorError("answer_target_inventory_mismatch")
    result = []
    for part, anchor in zip(proposal.parts, anchors, strict=True):
        if part.original_text != anchor.original.quote:
            raise AnchorError("answer_target_anchor_mismatch")
        if (
            part.state == "public"
            and part.operation == "search"
            and part.reference_text is not None
            and (part.retrieval_query is None or part.reference_text not in part.retrieval_query)
        ):
            raise AnchorError("retrieval_query_lost_reference_context")
        result.append(
            PartAnswerTarget(
                anchor.part_id, anchor.original, part.reference_text, part.history_indices
            )
        )
    return tuple(result)
