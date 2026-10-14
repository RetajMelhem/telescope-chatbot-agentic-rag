"""Exact embedding reuse with a complete, separate source-occurrence inventory."""

from collections.abc import Sequence

from telescope_rag.ingestion.models import PreparedChunk, stable_id


def embedding_input_key(chunk: PreparedChunk, configuration_hash: str = "") -> str:
    """Reuse vectors only for identical text within literal owner/language/configuration."""
    return stable_id(
        configuration_hash, chunk.language, chunk.doctor_id or "", chunk.retrieval_text
    )


def group_embedding_inputs(chunks: Sequence[PreparedChunk]) -> dict[str, list[PreparedChunk]]:
    groups: dict[str, list[PreparedChunk]] = {}
    ids = set()
    for chunk in chunks:
        if chunk.chunk_id in ids:
            raise ValueError("duplicate_chunk_occurrence")
        ids.add(chunk.chunk_id)
        groups.setdefault(embedding_input_key(chunk), []).append(chunk)
    return groups


def draft_input_plan(chunks: Sequence[PreparedChunk], prepared_digest: str) -> dict:
    """An audit projection, not source approval or a provider-ready batch."""
    groups = group_embedding_inputs(chunks)
    return {
        "version": "exact-input-occurrences-v1",
        "prepared_digest": prepared_digest,
        "status": "draft_requires_source_and_provider_validation",
        "occurrence_count": len(chunks),
        "unique_input_count": len(groups),
        "reused_occurrence_count": len(chunks) - len(groups),
        "inputs": [
            {
                "input_key": key,
                "language": occurrences[0].language,
                "doctor_id": occurrences[0].doctor_id,
                "retrieval_text": occurrences[0].retrieval_text,
                "representative_chunk_id": occurrences[0].chunk_id,
                "occurrence_chunk_ids": [c.chunk_id for c in occurrences],
            }
            for key, occurrences in groups.items()
        ],
    }
