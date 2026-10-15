"""Clean, format and bound structural units without fixed token windows."""

import re
import uuid
from collections.abc import Sequence
from typing import Protocol

from telescope_rag.ingestion.extraction import normalize_text
from telescope_rag.ingestion.models import (
    AuditItem,
    ContentUnit,
    ExtractedDocument,
    PreparedChunk,
    PreparedDocument,
    Segment,
    SourceSpan,
    stable_id,
)
from telescope_rag.providers.contracts import EmbeddingFormat

PREPARATION_VERSION = "structure-nfc-v5"
EMBEDDING_MODEL = "qwen/qwen3-embedding-8b"


class PreparationTokenCounter(Protocol):
    """A caller-verified complete-input Qwen count, never an implicit character estimate."""

    model: str
    version: str
    verified: bool

    def count(self, text: str) -> int: ...


def _unique_context(unit: ContentUnit) -> tuple[Segment, ...]:
    seen = set()
    result = []
    for segment in unit.context:
        key = (segment.source.block_id, segment.source.start, segment.source.end)
        if key not in seen and normalize_text(segment.text):
            seen.add(key)
            result.append(segment)
    return tuple(result)


def _formatted(unit: ContentUnit, segments: Sequence[Segment]) -> str:
    context = _unique_context(unit)
    content_refs = {(s.source.block_id, s.source.start, s.source.end) for s in segments}
    body_texts = {normalize_text(s.text) for s in segments}
    parts = []
    seen = set()

    def append(part: str, *, preserve_repetition: bool = False):
        if part and (preserve_repetition or part not in seen):
            parts.append(part)
            seen.add(part)

    for segment in context:
        if (segment.source.block_id, segment.source.start, segment.source.end) not in content_refs:
            text = normalize_text(segment.text)
            if unit.kind in {"list", "table"} or text not in body_texts:
                append(text)
    for segment in segments:
        if segment.table_headers and segment.table_cells:
            append(
                "; ".join(
                    normalize_text(header.original_text[header.start : header.end])
                    + ": "
                    + normalize_text(cell.original_text[cell.start : cell.end])
                    for header, cell in zip(segment.table_headers, segment.table_cells, strict=True)
                ),
                preserve_repetition=True,
            )
        elif unit.kind == "list" or "li:nth-of-type(" in segment.source.locator:
            marker = "- "
            if "ol:nth-of-type(" in segment.source.locator:
                index = re.search(r"li:nth-of-type\((\d+)\)$", segment.source.locator)
                if index:
                    marker = index[1] + ". "
            append(marker + normalize_text(segment.text), preserve_repetition=True)
        else:
            append(normalize_text(segment.text))
    # Layout separation is deterministic. It never fabricates clinical labels or facts.
    # Repeated context/heading/alt labels do not need repeated embedding text.
    # Every source occurrence remains in the chunk's span records. Ordered list
    # items and complete table rows preserve intentional repetition and ordering.
    return "\n\n".join(part for part in parts if part)


def _valid_segment(segment: Segment) -> bool:
    original = segment.source.original_text[segment.source.start : segment.source.end]
    return bool(normalize_text(original)) and normalize_text(original) == normalize_text(
        segment.text
    )


def _valid_table_mapping(unit: ContentUnit, segment: Segment) -> bool:
    if not segment.table_cells and not segment.table_headers:
        return unit.kind != "table"
    if unit.kind != "table" or len(segment.table_cells) != len(segment.table_headers):
        return False
    context_sources = {source.model_dump_json() for source in (s.source for s in unit.context)}
    if any(header.model_dump_json() not in context_sources for header in segment.table_headers):
        return False
    if segment.table_layout == "grid_cells":
        return segment.source in segment.table_cells
    row = segment.source.original_text[segment.source.start : segment.source.end]
    return normalize_text(
        " ".join(cell.original_text[cell.start : cell.end] for cell in segment.table_cells)
    ) == normalize_text(row)


def _sentences(segment: Segment) -> tuple[Segment, ...]:
    """Split original node text at explicit punctuation, retaining exact slice coordinates."""
    source = segment.source
    original = source.original_text
    part = original[source.start : source.end]
    # Do not fragment formatted rows/items or rewritten source text. In particular a
    # table qualifier must never be detached from its row by generic sentence logic.
    if normalize_text(part) != normalize_text(segment.text):
        return (segment,)
    boundaries = []
    for match in re.finditer(r"(?:[.!?؟。！]+[\"'”’»)]*(?=\s|$)|\n\s*\n)", part):
        before = part[: match.start()]
        after = part[match.end() :].lstrip()
        if match.group().startswith(".") and re.search(
            r"\b(?:Dr|Mr|Mrs|Ms|Prof|Sr|Jr|St)$", before, re.I
        ):
            continue
        if re.match(
            r"(?:however|except|but|only|not|this|it)\b|(?:لكن|ولكن|إلا|باستثناء|فقط|لا|هذا|هذه)\s",
            after,
            re.I,
        ):
            continue
        boundaries.append(match.end())
    if not boundaries or boundaries[-1] != len(part):
        boundaries.append(len(part))
    result = []
    start = 0
    for end in boundaries:
        value = part[start:end]
        if normalize_text(value):
            result.append(
                Segment(
                    text=normalize_text(value),
                    source=SourceSpan(
                        block_id=source.block_id,
                        locator=source.locator,
                        original_text=original,
                        start=source.start + start,
                        end=source.start + end,
                        source_line=source.source_line,
                    ),
                )
            )
        start = end
    return tuple(result)


def prepare_document(
    document: ExtractedDocument,
    *,
    max_tokens: int = 1200,
    counter: PreparationTokenCounter | None = None,
    document_prefix: str = "",
    embedding_format: EmbeddingFormat | None = None,
) -> PreparedDocument:
    """Produce provenance-preserving chunks, or explicit draft/gap records.

    A verified compatible counter is required to enforce a token ceiling. A verified
    format profile is independently required before a chunk may enter embedding.
    No fallback estimates, fixed windows, or implicit overlapping text are used.
    """
    if type(max_tokens) is not int or max_tokens < 1:
        raise ValueError("max_tokens must be a positive integer")
    gaps = list(document.gaps)
    removed = list(document.removed)
    chunks = []
    count_available = bool(
        counter is not None
        and counter.verified is True
        and counter.model == EMBEDDING_MODEL
        and isinstance(counter.version, str)
        and counter.version
    )
    format_verified = bool(embedding_format is not None and embedding_format.verified)
    if embedding_format is not None:
        if document_prefix and document_prefix != embedding_format.document_prefix:
            raise ValueError("Document prefix conflicts with embedding format")
        document_prefix = embedding_format.document_prefix
    if not count_available:
        gaps.append(AuditItem(code="token_count_unavailable"))
    if not format_verified:
        gaps.append(AuditItem(code="embedding_format_unverified"))

    def count(text: str) -> int | None:
        if not count_available:
            return None
        try:
            value = counter.count(document_prefix + text)
        except Exception:
            return None
        return value if type(value) is int and value >= 1 else None

    def add_chunk(unit: ContentUnit, segments: Sequence[Segment], tokens: int | None):
        if count_available and (tokens is None or tokens > max_tokens):
            gaps.append(
                AuditItem(
                    code="token_counter_failed" if tokens is None else "indivisible_unit_overflow",
                    unit_id=unit.unit_id,
                )
            )
            return
        text = _formatted(unit, segments)
        context = _unique_context(unit)
        original = "\n\n".join(
            " ".join(cell.original_text[cell.start : cell.end] for cell in segment.table_cells)
            if segment.table_layout == "grid_cells"
            else segment.source.original_text[segment.source.start : segment.source.end]
            for segment in segments
        )
        version = counter.version if count_available and tokens is not None else None
        config = ":".join(
            (
                PREPARATION_VERSION,
                str(max_tokens),
                str(version),
                embedding_format.version if embedding_format else "unverified",
                document_prefix,
            )
        )
        content_hash = stable_id(text, config, unit.doctor_id or "", unit.language)
        chunk_id = stable_id(
            document.page.document_id,
            unit.unit_id,
            content_hash,
            *(f"{s.source.block_id}:{s.source.start}:{s.source.end}" for s in segments),
        )
        chunks.append(
            PreparedChunk(
                chunk_id=chunk_id,
                point_id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id)),
                document_id=document.page.document_id,
                canonical_url=document.page.canonical_url,
                page_title=document.title,
                snapshot_id=document.page.snapshot_id,
                fetched_at=document.page.fetched_at,
                parent_block_id=unit.unit_id,
                block_type=unit.kind,
                language=unit.language,
                section_path=unit.section_path,
                doctor_id=unit.doctor_id,
                doctor_name=unit.doctor_name,
                canonical_doctor_id=unit.canonical_doctor_id,
                canonical_doctor_name=unit.canonical_doctor_name,
                source_issue_codes=unit.source_issue_codes,
                admission_policy_hash=document.admission_policy_hash,
                source_spans=tuple(span for s in segments for span in (s.source, *s.table_cells)),
                context_spans=tuple(s.source for s in context),
                original_text=original,
                retrieval_text=text,
                content_hash=content_hash,
                token_count=tokens,
                tokenizer_version=version,
                preparation_version=PREPARATION_VERSION,
                embedding_ready=tokens is not None and format_verified,
                embedding_format_version=embedding_format.version if format_verified else None,
                embedding_format_hash=stable_id(
                    "embedding-format-v1", embedding_format.model_dump_json()
                )
                if format_verified
                else None,
            )
        )

    for unit in document.units:
        if any(not _valid_segment(segment) for segment in (*unit.context, *unit.segments)):
            gaps.append(AuditItem(code="source_mapping_invalid", unit_id=unit.unit_id))
            continue
        if any(not _valid_table_mapping(unit, segment) for segment in unit.segments):
            gaps.append(AuditItem(code="table_source_mapping_invalid", unit_id=unit.unit_id))
            continue
        segments = [segment for segment in unit.segments if normalize_text(segment.text)]
        if not segments:
            gaps.append(AuditItem(code="empty_unit", unit_id=unit.unit_id))
            continue
        full_text = _formatted(unit, segments)
        tokens = count(full_text)
        if not count_available:
            add_chunk(unit, segments, None)
            continue
        if tokens is None:
            gaps.append(AuditItem(code="token_counter_failed", unit_id=unit.unit_id))
            continue
        if tokens <= max_tokens:
            add_chunk(unit, segments, tokens)
            continue
        # Keep each complete paragraph, item or table row. Only an oversized
        # narrative paragraph may fall back to language-aware sentence boundaries.
        leaves = []
        for segment in segments:
            child_tokens = count(_formatted(unit, [segment]))
            if child_tokens is None:
                gaps.append(AuditItem(code="token_counter_failed", unit_id=unit.unit_id))
                continue
            if child_tokens <= max_tokens:
                leaves.append(segment)
            elif unit.kind in {"section", "doctor", "faq", "contact", "hours"}:
                candidates = _sentences(segment)
                if len(candidates) <= 1:
                    gaps.append(
                        AuditItem(
                            code="indivisible_unit_overflow",
                            unit_id=unit.unit_id,
                            locator=segment.source.locator,
                        )
                    )
                    continue
                for candidate in candidates:
                    candidate_tokens = count(_formatted(unit, [candidate]))
                    if candidate_tokens is not None and candidate_tokens <= max_tokens:
                        leaves.append(candidate)
                    else:
                        gaps.append(
                            AuditItem(
                                code="indivisible_unit_overflow",
                                unit_id=unit.unit_id,
                                locator=candidate.source.locator,
                            )
                        )
            else:
                gaps.append(
                    AuditItem(
                        code="indivisible_unit_overflow",
                        unit_id=unit.unit_id,
                        locator=segment.source.locator,
                    )
                )
        group: list[Segment] = []
        for leaf in leaves:
            candidate_tokens = count(_formatted(unit, [*group, leaf]))
            if candidate_tokens is None:
                gaps.append(AuditItem(code="token_counter_failed", unit_id=unit.unit_id))
                continue
            if group and candidate_tokens > max_tokens:
                add_chunk(unit, group, count(_formatted(unit, group)))
                group = []
            group.append(leaf)
        if group:
            add_chunk(unit, group, count(_formatted(unit, group)))
    # Source gaps cannot silently turn a partial preparation into an approved input.
    ready = bool(chunks) and not gaps and all(chunk.embedding_ready for chunk in chunks)
    return PreparedDocument(
        document=document,
        chunks=tuple(chunks),
        gaps=tuple(gaps),
        removed=tuple(removed),
        embedding_ready=ready,
    )
