"""Development candidate only; the default graph retains its v1 prompt."""

from telescope_rag.prompts.offline_v1 import PLANNER_SYSTEM as BASELINE_PLANNER_SYSTEM

PROMPT_VERSION = "offline-rag-planner-source-types-v2"
PLANNER_SYSTEM = (
    BASELINE_PLANNER_SYSTEM
    + """
Each document's available_block_types lists literal admitted chunk types, not medical categories.
If you restrict block_types, use only types actually listed for the selected source documents.
Do not guess a structural type from a page title or the subject of the question. In particular,
contact facts can be stored in section chunks. Leave block_types empty when no type restriction
is needed to preserve the user's source/owner constraints. Metadata does not establish facts.
"""
)
