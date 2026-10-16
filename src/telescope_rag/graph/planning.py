"""One planner input builder shared by the graph and bounded compatibility screens."""

import json

from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.prompts.offline_v1 import PLANNER_SYSTEM, PROMPT_VERSION
from telescope_rag.providers.contracts import ChatMessage


def planner_messages(
    request: WorkflowRequest, bindings: SourceBindings, *, max_parts: int
) -> tuple[ChatMessage, ...]:
    body = {
        "prompt_version": PROMPT_VERSION,
        "original_query": request.query,
        "requested_language": request.language,
        "history": [h.model_dump() for h in request.history],
        "max_parts": max_parts,
        "source_manifest": json.loads(bindings.manifest_json),
    }
    return (
        ChatMessage(role="system", content=PLANNER_SYSTEM),
        ChatMessage(role="user", content=json.dumps(body, ensure_ascii=False)),
    )
