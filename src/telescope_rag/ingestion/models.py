"""Versioned ingestion records with DOM and extracted-text provenance."""

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BlockKind = Literal["section", "doctor", "faq", "list", "table", "contact", "hours"]


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RawPage(Record):
    snapshot_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    fetched_at: datetime
    content_hash: str = Field(min_length=1)
    html: str = Field(repr=False)

    @model_validator(mode="after")
    def aware_timestamp(self):
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("A timezone-aware fetch timestamp is required")
        return self


class SourceSpan(Record):
    """Offsets refer to original extracted node text, never raw HTML bytes."""

    block_id: str
    locator: str
    original_text: str = Field(repr=False)
    start: int = Field(default=0, ge=0)
    end: int = Field(ge=0)
    source_line: int | None = None
    attribute: Literal["alt"] | None = None

    @model_validator(mode="after")
    def valid_offsets(self):
        if (
            not self.locator
            or not self.block_id
            or not 0 <= self.start <= self.end <= len(self.original_text)
        ):
            raise ValueError("Invalid extracted-text source mapping")
        return self


class Segment(Record):
    text: str = Field(repr=False)
    source: SourceSpan
    table_cells: tuple[SourceSpan, ...] = ()
    table_headers: tuple[SourceSpan, ...] = ()
    table_layout: Literal["row", "grid_cells"] = "row"


class ContentUnit(Record):
    unit_id: str
    kind: BlockKind
    section_path: tuple[str, ...] = ()
    context: tuple[Segment, ...] = ()
    segments: tuple[Segment, ...]
    doctor_id: str | None = None
    doctor_name: str | None = None
    language: Literal["ar", "en", "und"] = "und"


class AuditItem(Record):
    code: str
    locator: str | None = None
    unit_id: str | None = None
    detail: str | None = None


class ExtractedDocument(Record):
    page: RawPage
    title: str
    units: tuple[ContentUnit, ...]
    removed: tuple[AuditItem, ...] = ()
    gaps: tuple[AuditItem, ...] = ()
    extractor_version: str = "html-structure-v2"


class PreparedChunk(Record):
    chunk_id: str
    point_id: str
    document_id: str
    canonical_url: str
    page_title: str
    snapshot_id: str
    fetched_at: datetime
    parent_block_id: str
    block_type: BlockKind
    language: Literal["ar", "en", "und"]
    section_path: tuple[str, ...]
    doctor_id: str | None = None
    doctor_name: str | None = None
    source_spans: tuple[SourceSpan, ...]
    context_spans: tuple[SourceSpan, ...] = ()
    original_text: str = Field(repr=False)
    retrieval_text: str = Field(repr=False)
    content_hash: str
    token_count: int | None = Field(default=None, ge=1)
    tokenizer_version: str | None = None
    embedding_format_version: str | None = None
    embedding_format_hash: str | None = None
    preparation_version: str = "structure-nfc-v2"
    embedding_ready: bool = False


class PreparedDocument(Record):
    document: ExtractedDocument
    chunks: tuple[PreparedChunk, ...]
    gaps: tuple[AuditItem, ...] = ()
    removed: tuple[AuditItem, ...] = ()
    embedding_ready: bool = False
