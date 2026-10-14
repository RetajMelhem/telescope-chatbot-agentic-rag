"""Apply reviewed, digest-bound source selections without rewriting source facts."""

import re
from typing import Literal

from pydantic import Field

from telescope_rag.ingestion.models import (
    AuditItem,
    ContentUnit,
    ExtractedDocument,
    PreparedDocument,
    Record,
    Segment,
    stable_id,
)
from telescope_rag.ingestion.review import prepared_digest


class DoctorAlias(Record):
    """A human-confirmed identity relation, separate from literal source names."""

    preferred_name: str = Field(min_length=1)
    literal_source_names: tuple[str, ...] = Field(min_length=2)
    authority: Literal["user_confirmed"] = "user_confirmed"


class UnitSelection(Record):
    document_id: str
    unit_id: str
    unit_digest: str
    disposition: Literal["retain", "exclude"]
    segment_keys: tuple[str, ...] = ()
    context_keys: tuple[str, ...] = ()
    section_path: tuple[str, ...] = ()
    reason: str = Field(min_length=1)
    source_issue_codes: tuple[str, ...] = ()


class AdmissionPlan(Record):
    version: Literal["reviewed-source-selection-v1"] = "reviewed-source-selection-v1"
    snapshot_id: str
    collection_digest: str
    input_prepared_digest: str
    decision_authority: str = Field(min_length=1)
    decision_notes: tuple[str, ...]
    aliases: tuple[DoctorAlias, ...] = ()
    excluded_document_ids: tuple[str, ...] = ()
    primary_directory_document_ids: tuple[str, ...] = ()
    accepted_exclusion_gaps: tuple[
        Literal["placeholder_document", "placeholder_content_quarantined"], ...
    ] = ()
    units: tuple[UnitSelection, ...]


def segment_key(segment: Segment) -> str:
    return stable_id("source-segment-v1", segment.model_dump_json())


def unit_digest(unit: ContentUnit) -> str:
    return stable_id("source-unit-v1", unit.model_dump_json())


def admission_hash(plan: AdmissionPlan) -> str:
    return stable_id("admission-policy-v1", plan.model_dump_json())


def _subsequence(values: tuple[str, ...], originals: tuple[str, ...]) -> bool:
    remaining = iter(originals)
    return all(any(original == value for original in remaining) for value in values)


def _project(unit: ContentUnit, selection: UnitSelection) -> ContentUnit:
    if selection.unit_digest != unit_digest(unit):
        raise ValueError("admission_unit_digest_mismatch")
    if selection.disposition == "exclude":
        if selection.segment_keys or selection.context_keys or selection.section_path:
            raise ValueError("excluded_unit_has_projection")
        return unit
    originals = {segment_key(s): s for s in (*unit.context, *unit.segments)}
    if (
        not selection.segment_keys
        or len(set(selection.segment_keys)) != len(selection.segment_keys)
        or set((*selection.segment_keys, *selection.context_keys)) - originals.keys()
        or not _subsequence(selection.context_keys, tuple(segment_key(s) for s in unit.context))
        or not _subsequence(selection.section_path, unit.section_path)
    ):
        raise ValueError("admission_projection_invalid")
    own_keys = tuple(segment_key(s) for s in unit.segments)
    removed_context = [s for s in unit.context if segment_key(s) not in selection.context_keys]
    if any(
        not re.search(r"(?:title|h[1-6]):nth-of-type\(\d+\)$", s.source.locator)
        for s in removed_context
    ):
        raise ValueError("admission_required_context_removed")
    # Keep original body order, or retain one actual heading after excluding a damaged body.
    own_body = _subsequence(selection.segment_keys, own_keys)
    heading_only = (
        len(selection.segment_keys) == 1
        and selection.segment_keys[0] in {segment_key(s) for s in unit.context}
        and originals[selection.segment_keys[0]].text in unit.section_path
        and re.search(
            r"h[1-6]:nth-of-type\(\d+\)$", originals[selection.segment_keys[0]].source.locator
        )
        and unit.kind == "section"
    )
    if not (own_body or heading_only):
        raise ValueError("admission_projection_invalid")
    if unit.kind in {"faq", "table"} and selection.segment_keys != own_keys:
        raise ValueError("admission_atomic_unit_changed")
    # Required FAQ/table labels and owner identity may not be trimmed by admission.
    retained_context = {originals[k].source.block_id for k in selection.context_keys}
    if unit.kind == "table" and any(
        h.block_id not in retained_context for s in unit.segments for h in s.table_headers
    ):
        raise ValueError("admission_atomic_context_changed")
    if unit.kind == "faq" and selection.context_keys != tuple(segment_key(s) for s in unit.context):
        raise ValueError("admission_atomic_context_changed")
    segments = tuple(originals[k] for k in selection.segment_keys)
    context = tuple(originals[k] for k in selection.context_keys)
    if any(
        label not in {s.text for s in (*segments, *context)} for label in selection.section_path
    ):
        raise ValueError("admission_projection_invalid")
    if unit.doctor_name and not any(s.text == unit.doctor_name for s in (*segments, *context)):
        raise ValueError("admission_owner_context_removed")
    return unit.model_copy(
        update={
            "segments": segments,
            "context": context,
            "section_path": selection.section_path,
            "source_issue_codes": selection.source_issue_codes,
        }
    )


def apply_admission(
    documents: tuple[PreparedDocument, ...], plan: AdmissionPlan, *, collection_digest: str
) -> tuple[ExtractedDocument, ...]:
    """Validate complete source accounting before producing a selected source projection.

    Source selection is independent of token validation/provider approval. Raw pages,
    original segments, literal owner IDs/names and source coordinates remain unchanged.
    """
    if (
        not collection_digest
        or plan.collection_digest != collection_digest
        or plan.input_prepared_digest != prepared_digest(documents)
        or any(d.document.page.snapshot_id != plan.snapshot_id for d in documents)
    ):
        raise ValueError("admission_input_binding_mismatch")
    doc_ids = {d.document.page.document_id for d in documents}
    if len(doc_ids) != len(documents) or set(plan.excluded_document_ids) - doc_ids:
        raise ValueError("admission_document_scope_invalid")
    if len(set(plan.excluded_document_ids)) != len(plan.excluded_document_ids):
        raise ValueError("admission_document_scope_invalid")
    primary = set(plan.primary_directory_document_ids)
    if (
        len(primary) != len(plan.primary_directory_document_ids)
        or primary - doc_ids
        or primary & set(plan.excluded_document_ids)
    ):
        raise ValueError("admission_directory_scope_invalid")
    expected = {
        (d.document.page.document_id, u.unit_id): u for d in documents for u in d.document.units
    }
    if len(expected) != sum(len(d.document.units) for d in documents):
        raise ValueError("duplicate_source_unit")
    selections = {(s.document_id, s.unit_id): s for s in plan.units}
    if len(selections) != len(plan.units) or selections.keys() != expected.keys():
        raise ValueError("admission_source_accounting_incomplete")
    source_names = {u.doctor_name for u in expected.values() if u.doctor_name}
    aliases = {}
    preferred = set()
    for alias in plan.aliases:
        if alias.preferred_name in preferred:
            raise ValueError("admission_alias_collision")
        preferred.add(alias.preferred_name)
        for name in alias.literal_source_names:
            if name in aliases or name not in source_names:
                raise ValueError("admission_alias_invalid")
            aliases[name] = alias
    policy_hash = admission_hash(plan)
    projected = {key: _project(unit, selections[key]) for key, unit in expected.items()}
    result = []
    for prepared in documents:
        doc = prepared.document
        doc_id = doc.page.document_id
        if doc_id in plan.excluded_document_ids:
            if any(selections[(doc_id, u.unit_id)].disposition != "exclude" for u in doc.units):
                raise ValueError("admission_excluded_document_retains_units")
            continue
        retained = []
        removed = list(doc.removed)
        for unit in doc.units:
            selection = selections[(doc_id, unit.unit_id)]
            if selection.disposition == "exclude":
                removed.append(AuditItem(code=selection.reason, unit_id=unit.unit_id))
                continue
            admitted = projected[(doc_id, unit.unit_id)]
            if alias := aliases.get(unit.doctor_name):
                admitted = admitted.model_copy(
                    update={
                        "canonical_doctor_id": stable_id(
                            "user-confirmed-doctor", alias.preferred_name
                        ),
                        "canonical_doctor_name": alias.preferred_name,
                    }
                )
            if admitted != unit:
                removed.append(AuditItem(code=selection.reason, unit_id=unit.unit_id))
            retained.append(admitted)
        for gap in doc.gaps:
            if gap.code in plan.accepted_exclusion_gaps:
                removed.append(gap.model_copy(update={"code": "reviewed_" + gap.code}))
        result.append(
            doc.model_copy(
                update={
                    "units": tuple(retained),
                    "removed": tuple(removed),
                    "gaps": tuple(
                        g for g in doc.gaps if g.code not in plan.accepted_exclusion_gaps
                    ),
                    "admission_policy_hash": policy_hash,
                }
            )
        )
    if not result or any(not d.units for d in result):
        raise ValueError("admission_empty_document")
    if any(
        not any(u.doctor_name for u in d.units) for d in result if d.page.document_id in primary
    ):
        raise ValueError("admission_directory_scope_invalid")
    return tuple(result)
