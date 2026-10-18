"""Bounded reuse of already retrieved page evidence, never new source acquisition."""

from collections.abc import Mapping, Sequence

from telescope_rag.retrieval.assembly import AssemblyRequest, EvidenceCatalog, limited_to_context


def reuse_page_candidates(
    catalog: EvidenceCatalog,
    request: AssemblyRequest,
    candidates: Mapping[str, Sequence[str]],
    *,
    shareable_parts: frozenset[str],
) -> dict[str, tuple[str, ...]]:
    if set(candidates) != {p.part_id for p in request.parts}:
        raise ValueError("request_page_inventory_invalid")
    copied = {}
    for part in request.parts:
        ids = candidates[part.part_id]
        if (
            isinstance(ids, (str, bytes))
            or not isinstance(ids, Sequence)
            or len(ids) > 10000
            or len(set(ids)) != len(ids)
            or any(i not in catalog.chunks for i in ids)
            or (part.state != "public" and ids)
        ):
            raise ValueError("request_page_inventory_invalid")
        copied[part.part_id] = tuple(ids)
    # Complete source reads are resolved from the catalog by the assembler,
    # rather than returned by dense retrieval. They are already requested reads.
    pooled = tuple(
        dict.fromkeys(
            i
            for part in request.parts
            for i in (
                catalog.scope_members(part.scope)
                if part.state == "public" and part.scope.complete
                else copied[part.part_id]
            )
        )
    )
    output = dict(copied)
    for part in request.parts:
        if part.part_id not in shareable_parts or part.state != "public" or part.scope.complete:
            continue
        allowed = set(catalog.scope_members(part.scope))
        original = copied[part.part_id]
        pages = {catalog.chunks[i].document_id for i in original if i in allowed}
        output[part.part_id] = original + tuple(
            i
            for i in pooled
            if i not in original
            and i in allowed
            and catalog.chunks[i].document_id in pages
            and not limited_to_context(catalog.chunks[i], part.intended_use)
        )
    return output
