"""Immutable preparation bundles and evidence-backed coverage review artifacts."""

import json
from pathlib import Path

from pydantic import Field

from telescope_rag.ingestion.deduplication import draft_input_plan
from telescope_rag.ingestion.models import (
    PreparedChunk,
    PreparedDocument,
    Record,
    SourceSpan,
    stable_id,
)


class DirectoryEntry(Record):
    doctor_id: str
    name: str
    canonical_doctor_id: str | None = None
    canonical_doctor_name: str | None = None
    language: str
    canonical_url: str
    parent_block_id: str
    source_spans: tuple[SourceSpan, ...]
    chunk_ids: tuple[str, ...]


class HoursEvidence(Record):
    """Raw hours evidence for review, never an inferred open/closed interval."""

    canonical_url: str
    doctor_id: str | None
    source_spans: tuple[SourceSpan, ...]
    chunk_ids: tuple[str, ...]
    interpretation_status: str = "unresolved"


class PreparationAudit(Record):
    snapshot_id: str
    prepared_digest: str
    collection_digest: str | None = None
    document_count: int
    chunk_count: int
    token_validated_chunks: int
    directory: tuple[DirectoryEntry, ...]
    hours: tuple[HoursEvidence, ...]
    gap_codes: tuple[str, ...]
    removed_count: int
    crawl_coverage_complete: bool
    directory_coverage_status: str = "requires_source_review"
    embedding_ready: bool
    approved: bool = False


class ReviewApproval(Record):
    snapshot_id: str
    prepared_digest: str
    collection_digest: str | None = None
    reviewer: str = Field(min_length=1, max_length=128)
    approved: bool = False
    source_reviewed: bool = False
    accepted_gap_codes: tuple[str, ...] = ()


def prepared_document_json(document: PreparedDocument, *, indent: int | None = None) -> str:
    """Preserve sealed legacy bytes when optional admission fields were absent.

    Use the same serialization for stored documents and their digest. Explicitly
    supplied metadata remains covered, including an explicit null/empty value.
    """
    unit_fields = {"canonical_doctor_id", "canonical_doctor_name", "source_issue_codes"}
    chunk_fields = unit_fields | {"admission_policy_hash"}
    doc_exclusions: dict = {
        "units": {
            i: unit_fields - u.model_fields_set for i, u in enumerate(document.document.units)
        }
    }
    if "admission_policy_hash" not in document.document.model_fields_set:
        doc_exclusions["admission_policy_hash"] = True
    exclusions = {
        "document": doc_exclusions,
        "chunks": {i: chunk_fields - c.model_fields_set for i, c in enumerate(document.chunks)},
    }
    return document.model_dump_json(exclude=exclusions, indent=indent)


def prepared_digest(documents: tuple[PreparedDocument, ...]) -> str:
    return stable_id(
        "prepared-bundle-v1",
        *(
            prepared_document_json(document)
            for document in sorted(documents, key=lambda item: item.document.page.document_id)
        ),
    )


def all_chunks(documents: tuple[PreparedDocument, ...]) -> tuple[PreparedChunk, ...]:
    return tuple(chunk for document in documents for chunk in document.chunks)


def build_audit(
    documents: tuple[PreparedDocument, ...],
    *,
    snapshot_id: str,
    crawl_gap_codes: tuple[str, ...] = (),
    collection_digest: str | None = None,
    crawl_coverage_confirmed: bool = False,
) -> PreparationAudit:
    if not documents or any(d.document.page.snapshot_id != snapshot_id for d in documents):
        raise ValueError("snapshot_mismatch_or_empty")
    chunks = all_chunks(documents)
    directory, hours = [], []
    for document in documents:
        for unit in document.document.units:
            children = tuple(c for c in document.chunks if c.parent_block_id == unit.unit_id)
            spans = tuple(segment.source for segment in (*unit.context, *unit.segments))
            if unit.kind == "doctor" and unit.doctor_id and unit.doctor_name:
                directory.append(
                    DirectoryEntry(
                        doctor_id=unit.doctor_id,
                        name=unit.doctor_name,
                        canonical_doctor_id=unit.canonical_doctor_id,
                        canonical_doctor_name=unit.canonical_doctor_name,
                        language=unit.language,
                        canonical_url=document.document.page.canonical_url,
                        parent_block_id=unit.unit_id,
                        source_spans=spans,
                        chunk_ids=tuple(c.chunk_id for c in children),
                    )
                )
            # These markers surface raw review candidates, never establish interpreted hours.
            text = " ".join(segment.text for segment in (*unit.context, *unit.segments)).casefold()
            hours_candidate = unit.kind == "hours" or any(
                marker in text
                for marker in (
                    "working hours",
                    "opening hours",
                    "friday",
                    "ساعات العمل",
                    "أوقات العمل",
                    "الجمعة",
                )
            )
            if hours_candidate:
                hours.append(
                    HoursEvidence(
                        canonical_url=document.document.page.canonical_url,
                        doctor_id=unit.doctor_id,
                        source_spans=spans,
                        chunk_ids=tuple(c.chunk_id for c in children),
                    )
                )
    coverage = bool(collection_digest) and crawl_coverage_confirmed and not crawl_gap_codes
    gaps = tuple(
        sorted(
            set(crawl_gap_codes)
            | (set() if collection_digest else {"collection_coverage_unverified"})
            | {
                item.code
                for document in documents
                for item in (*document.document.gaps, *document.gaps)
            }
        )
    )
    return PreparationAudit(
        snapshot_id=snapshot_id,
        prepared_digest=prepared_digest(documents),
        collection_digest=collection_digest,
        document_count=len(documents),
        chunk_count=len(chunks),
        token_validated_chunks=sum(chunk.token_count is not None for chunk in chunks),
        directory=tuple(directory),
        hours=tuple(hours),
        gap_codes=gaps,
        removed_count=sum(
            len({item.model_dump_json() for item in (*d.document.removed, *d.removed)})
            for d in documents
        ),
        crawl_coverage_complete=coverage,
        embedding_ready=bool(chunks) and all(d.embedding_ready for d in documents),
    )


def write_bundle(
    output: Path, documents: tuple[PreparedDocument, ...], audit: PreparationAudit
) -> None:
    """Exclusive directory; never overwrite a prior reviewed bundle."""
    if audit.prepared_digest != prepared_digest(documents):
        raise ValueError("audit_digest_mismatch")
    input_plan = draft_input_plan(all_chunks(documents), audit.prepared_digest)
    output.mkdir(parents=True, exist_ok=False)
    for document in documents:
        # Names come from our digest, never from external paths/HTML identifiers.
        filename = stable_id(document.document.page.document_id)
        (output / f"{filename}.json").write_text(
            prepared_document_json(document, indent=2), encoding="utf-8"
        )
    (output / "audit.json").write_text(audit.model_dump_json(indent=2), encoding="utf-8")
    (output / "review-template.json").write_text(
        ReviewApproval(
            snapshot_id=audit.snapshot_id,
            prepared_digest=audit.prepared_digest,
            collection_digest=audit.collection_digest,
            reviewer="REPLACE_WITH_REVIEWER",
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    summary = {
        "snapshot_id": audit.snapshot_id,
        "document_count": audit.document_count,
        "chunk_count": audit.chunk_count,
        "unique_embedding_inputs": input_plan["unique_input_count"],
        "reused_embedding_occurrences": input_plan["reused_occurrence_count"],
        "doctor_occurrences": len(audit.directory),
        "hours_evidence_blocks": len(audit.hours),
        "gap_codes": audit.gap_codes,
        "embedding_ready": audit.embedding_ready,
        "approved": False,
        "directory_coverage_status": audit.directory_coverage_status,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metadata = output / "metadata"
    metadata.mkdir()
    (metadata / "embedding-input-plan.json").write_text(
        json.dumps(input_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def validate_approval(
    documents: tuple[PreparedDocument, ...], audit: PreparationAudit, approval: ReviewApproval
) -> None:
    digest = prepared_digest(documents)
    if (
        not approval.approved
        or not approval.source_reviewed
        or approval.reviewer == "REPLACE_WITH_REVIEWER"
    ):
        raise ValueError("source_review_required")
    if not audit.collection_digest or approval.collection_digest != audit.collection_digest:
        raise ValueError("collection_review_binding_required")
    if (
        approval.snapshot_id != audit.snapshot_id
        or any(d.document.page.snapshot_id != audit.snapshot_id for d in documents)
        or digest != audit.prepared_digest
        or digest != approval.prepared_digest
    ):
        raise ValueError("review_digest_mismatch")
    if set(audit.gap_codes) - set(approval.accepted_gap_codes):
        raise ValueError("unreviewed_coverage_gaps")
    if not audit.embedding_ready or not all(d.embedding_ready for d in documents):
        raise ValueError("preparation_not_embedding_ready")
    for document in documents:
        page = document.document.page
        units = {unit.unit_id: unit for unit in document.document.units}
        if len(units) != len(document.document.units):
            raise ValueError("duplicate_source_unit")
        for chunk in document.chunks:
            unit = units.get(chunk.parent_block_id)
            if (
                unit is None
                or chunk.document_id != page.document_id
                or chunk.canonical_url != page.canonical_url
                or chunk.snapshot_id != page.snapshot_id
                or chunk.fetched_at != page.fetched_at
                or chunk.page_title != document.document.title
                or chunk.doctor_id != unit.doctor_id
                or chunk.doctor_name != unit.doctor_name
                or chunk.canonical_doctor_id != unit.canonical_doctor_id
                or chunk.canonical_doctor_name != unit.canonical_doctor_name
                or chunk.source_issue_codes != unit.source_issue_codes
                or chunk.admission_policy_hash != document.document.admission_policy_hash
                or chunk.block_type != unit.kind
                or chunk.language != unit.language
                or chunk.section_path != unit.section_path
            ):
                raise ValueError("chunk_source_ownership_mismatch")
            sources = tuple(
                span
                for segment in (*unit.context, *unit.segments)
                for span in (segment.source, *segment.table_cells, *segment.table_headers)
            )
            for reference in (*chunk.source_spans, *chunk.context_spans):
                if not any(
                    reference.block_id == source.block_id
                    and reference.locator == source.locator
                    and reference.attribute == source.attribute
                    and reference.original_text == source.original_text
                    and source.start <= reference.start < reference.end <= source.end
                    for source in sources
                ):
                    raise ValueError("chunk_source_mapping_mismatch")
