"""Deterministic representative selection for byte-identical evidence occurrences.

Several admitted pages repeat the same published block verbatim: the site
footer contact block, the booking call to action, and directory cards that are
also copied onto a profile page. Those occurrences share one embedding input, so
they share one vector and therefore one retrieval score. Left alone they occupy
every retrieval slot with a single fact and the citation lands on whichever page
the database happened to return first.

This module keeps every occurrence in the admitted corpus and in the evidence
group inventory. It only chooses which occurrence represents a group when a
part's candidates are assembled. Selection is deterministic and uses no model,
no similarity score and no medical judgement:

1. an occurrence whose page presents the block as its own section with a heading
   outranks a repeated footer fragment;
2. a page with its own substantive content outranks a template page that only
   repeats shared blocks;
3. a shorter public path outranks a deeper derivative path;
4. the lexicographically smaller canonical URL outranks the larger one;
5. the smaller chunk id breaks the final tie.

A representative is only used when it is inside the requesting part's own
scope. Otherwise the retrieved occurrence is kept unchanged.
"""

from collections.abc import Mapping
from types import MappingProxyType

from telescope_rag.ingestion.deduplication import embedding_input_key
from telescope_rag.ingestion.models import PreparedChunk


class DuplicateIndex:
    """Map every admitted occurrence to the representative of its content group."""

    def __init__(self, chunks: Mapping[str, PreparedChunk]) -> None:
        if not chunks:
            raise ValueError("duplicate_index_requires_chunks")
        self._chunks = MappingProxyType(dict(chunks))
        groups: dict[str, list[PreparedChunk]] = {}
        documents_per_key: dict[str, set[str]] = {}
        for chunk in self._chunks.values():
            key = embedding_input_key(chunk)
            groups.setdefault(key, []).append(chunk)
            documents_per_key.setdefault(key, set()).add(chunk.document_id)
        unique_sections: dict[str, int] = {}
        for chunk in self._chunks.values():
            key = embedding_input_key(chunk)
            if len(documents_per_key[key]) == 1:
                unique_sections[chunk.document_id] = unique_sections.get(chunk.document_id, 0) + 1
        self._representative: dict[str, str] = {}
        self._group_sizes: dict[str, int] = {}
        for key, members in groups.items():
            representative = min(
                members,
                key=lambda chunk: (
                    0 if chunk.section_path else 1,
                    -unique_sections.get(chunk.document_id, 0),
                    len(chunk.canonical_url.strip("/").split("/")),
                    chunk.canonical_url,
                    chunk.chunk_id,
                ),
            )
            for member in members:
                self._representative[member.chunk_id] = representative.chunk_id
            self._group_sizes[key] = len(members)
        self._keys = MappingProxyType(
            {chunk_id: embedding_input_key(chunk) for chunk_id, chunk in self._chunks.items()}
        )
        self._representative_map = MappingProxyType(self._representative)
        self._sizes = MappingProxyType(self._group_sizes)
        self.group_count = len(groups)
        self.occurrence_count = len(self._chunks)
        self.collapsed_occurrence_count = len(self._chunks) - len(groups)

    def content_key(self, chunk_id: str) -> str:
        """The shared embedding input identity of an occurrence."""
        key = self._keys.get(chunk_id)
        if key is None:
            raise ValueError("duplicate_index_unknown_chunk")
        return key

    def representative(self, chunk_id: str, *, allowed: frozenset[str] | None = None) -> str:
        """Return the representative occurrence, honouring the caller's own scope."""
        representative = self._representative_map.get(chunk_id)
        if representative is None:
            raise ValueError("duplicate_index_unknown_chunk")
        if allowed is not None and representative not in allowed:
            return chunk_id
        return representative

    def is_shared(self, chunk_id: str) -> bool:
        """True when more than one admitted occurrence carries this exact content."""
        return self._sizes[self.content_key(chunk_id)] > 1
