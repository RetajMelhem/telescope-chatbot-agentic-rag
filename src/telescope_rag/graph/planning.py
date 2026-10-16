"""One planner input builder shared by the graph and bounded compatibility screens."""

import json
from typing import Literal

from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.prompts.offline_v1 import PLANNER_SYSTEM, PROMPT_VERSION
from telescope_rag.prompts.planner_anchors_v4 import PLANNER_SYSTEM as ANCHORED_SYSTEM
from telescope_rag.prompts.planner_anchors_v4 import PROMPT_VERSION as ANCHORED_VERSION
from telescope_rag.prompts.planner_candidate_v2 import (
    PLANNER_SYSTEM as CANDIDATE_SYSTEM,
)
from telescope_rag.prompts.planner_candidate_v2 import (
    PROMPT_VERSION as CANDIDATE_VERSION,
)
from telescope_rag.prompts.planner_policy_v6 import PLANNER_SYSTEM as POLICY_SYSTEM
from telescope_rag.prompts.planner_policy_v6 import PROMPT_VERSION as POLICY_VERSION
from telescope_rag.prompts.planner_targets_v5 import PLANNER_SYSTEM as TARGET_SYSTEM
from telescope_rag.prompts.planner_targets_v5 import PROMPT_VERSION as TARGET_VERSION
from telescope_rag.providers.contracts import ChatMessage


def planner_messages(
    request: WorkflowRequest,
    bindings: SourceBindings,
    *,
    max_parts: int,
    profile: Literal[
        "baseline",
        "source_types_no_reasoning",
        "literal_anchors",
        "answer_targets",
        "policy_targets",
    ] = "baseline",
) -> tuple[ChatMessage, ...]:
    if profile not in {
        "baseline",
        "source_types_no_reasoning",
        "literal_anchors",
        "answer_targets",
        "policy_targets",
    }:
        raise ValueError("unknown_planner_profile")
    candidate = profile == "source_types_no_reasoning"
    body = {
        "prompt_version": POLICY_VERSION
        if profile == "policy_targets"
        else TARGET_VERSION
        if profile == "answer_targets"
        else ANCHORED_VERSION
        if profile == "literal_anchors"
        else CANDIDATE_VERSION
        if candidate
        else PROMPT_VERSION,
        "original_query": request.query,
        "requested_language": request.language,
        "history": [h.model_dump() for h in request.history],
        "max_parts": max_parts,
        "source_manifest": json.loads(bindings.manifest_json),
    }
    return (
        ChatMessage(
            role="system",
            content=POLICY_SYSTEM
            if profile == "policy_targets"
            else TARGET_SYSTEM
            if profile == "answer_targets"
            else ANCHORED_SYSTEM
            if profile == "literal_anchors"
            else CANDIDATE_SYSTEM
            if candidate
            else PLANNER_SYSTEM,
        ),
        ChatMessage(role="user", content=json.dumps(body, ensure_ascii=False)),
    )
