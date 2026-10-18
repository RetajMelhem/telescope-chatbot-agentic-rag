"""Bounded structural context candidates; headings never establish factual entailment."""

from telescope_rag.retrieval.assembly import EvidenceCatalog


def section_context(
    catalog: EvidenceCatalog,
    targets: tuple[str, ...],
    *,
    allowed: frozenset[str],
    limit: int,
) -> tuple[str, ...]:
    """Offer a complete nearest ancestor set within exact source/owner/language scope.

    Candidate context remains separate original chunks. Never choose a partial
    ancestor set or infer clinical relationships from a matching heading alone.
    """
    if type(limit) is not int or not 0 <= limit <= 2:
        raise ValueError("section_context_limit_invalid")
    if not allowed <= catalog.chunks.keys() or any(i not in allowed for i in targets):
        raise ValueError("section_context_scope_invalid")
    if not limit:
        return ()
    selected: list[str] = []
    for identity in targets:
        child = catalog.chunks[identity]
        for depth in range(len(child.section_path) - 1, 0, -1):
            parent_path = child.section_path[:depth]
            parents = tuple(
                i
                for i, c in catalog.chunks.items()
                if c.document_id == child.document_id
                and c.language == child.language
                and c.doctor_id == child.doctor_id
                and c.canonical_doctor_id == child.canonical_doctor_id
                and c.section_path == parent_path
            )
            if not parents:
                continue
            new = tuple(i for i in parents if i not in selected and i not in targets)
            if set(parents) <= allowed and len(selected) + len(new) <= limit:
                selected.extend(new)
            # Missing/oversized nearest context does not authorize a broader one.
            break
    return tuple(selected)
