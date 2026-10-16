"""One planner input builder shared by the graph and bounded compatibility screens."""

import json
from typing import Literal

from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.prompts.offline_v1 import PLANNER_SYSTEM, PROMPT_VERSION
from telescope_rag.prompts.planner_anchors_v3 import PLANNER_SYSTEM as ANCHORED_SYSTEM
from telescope_rag.prompts.planner_anchors_v3 import PROMPT_VERSION as ANCHORED_VERSION
from telescope_rag.prompts.planner_candidate_v2 import (
    PLANNER_SYSTEM as CANDIDATE_SYSTEM,
)
from telescope_rag.prompts.planner_candidate_v2 import (
    PROMPT_VERSION as CANDIDATE_VERSION,
)
from telescope_rag.providers.contracts import ChatMessage


def planner_messages(
    request: WorkflowRequest,
    bindings: SourceBindings,
    *,
    max_parts: int,
    profile: Literal["baseline", "source_types_no_reasoning", "literal_anchors"] = "baseline",
) -> tuple[ChatMessage, ...]:
    if profile not in {"baseline", "source_types_no_reasoning", "literal_anchors"}:
        raise ValueError("unknown_planner_profile")
    candidate = profile == "source_types_no_reasoning"
    body = {
        "prompt_version": ANCHORED_VERSION
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
            content=ANCHORED_SYSTEM
            if profile == "literal_anchors"
            else CANDIDATE_SYSTEM
            if candidate
            else PLANNER_SYSTEM,
        ),
        ChatMessage(role="user", content=json.dumps(body, ensure_ascii=False)),
    )
