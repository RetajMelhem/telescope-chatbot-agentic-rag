"""Source selection must be complete, sealed, literal and independent of embedding approval."""

import json
from datetime import UTC, datetime

import pytest

from telescope_rag.ingestion.admission import (
    AdmissionPlan,
    DoctorAlias,
    UnitSelection,
    admission_hash,
    apply_admission,
    segment_key,
    unit_digest,
)
from telescope_rag.ingestion.cli import admit_bundle
from telescope_rag.ingestion.extraction import extract_page
from telescope_rag.ingestion.models import RawPage, stable_id
from telescope_rag.ingestion.preparation import prepare_document
from telescope_rag.ingestion.review import (
    ReviewApproval,
    build_audit,
    prepared_digest,
    prepared_document_json,
    validate_approval,
    write_bundle,
)


def sources():
    docs = []
    for n, name in enumerate(("Dr. Example Alias", "Dr. Example Preferred")):
        html = (
            "<main><h1>Department label</h1><section class='doctor-profile'>"
            f"<h2>{name}</h2><p>Literal specialty.</p></section><h2>Service</h2>"
            "<p>Damaged source copy.</p></main>"
        )
        page = RawPage(
            snapshot_id="synthetic-admission",
            document_id=f"doc-{n}",
            canonical_url=f"https://telescopecenter.com/synthetic-admission-{n}/",
            fetched_at=datetime(2026, 10, 15, tzinfo=UTC),
            html=html,
            content_hash=stable_id(html),
        )
        docs.append(prepare_document(extract_page(page)))
    return tuple(docs)


def selection(doc, unit, **updates):
    return UnitSelection(
        document_id=doc.document.page.document_id,
        unit_id=unit.unit_id,
        unit_digest=unit_digest(unit),
        disposition="retain",
        segment_keys=tuple(segment_key(s) for s in unit.segments),
        context_keys=tuple(segment_key(s) for s in unit.context),
        section_path=unit.section_path,
        reason="synthetic_user_decision",
    ).model_copy(update=updates)


def plan_for(docs):
    return AdmissionPlan(
        snapshot_id="synthetic-admission",
        collection_digest="synthetic-collection-hash",
        input_prepared_digest=prepared_digest(docs),
        decision_authority="Synthetic human decision",
        decision_notes=("Synthetic selection and alias confirmation.",),
        aliases=(
            DoctorAlias(
                preferred_name="Example Preferred",
                literal_source_names=("Dr. Example Alias", "Dr. Example Preferred"),
            ),
        ),
        units=tuple(selection(d, u) for d in docs for u in d.document.units),
    )


def apply(docs, plan):
    return apply_admission(docs, plan, collection_digest="synthetic-collection-hash")


def test_aliases_add_canonical_metadata_without_rewriting_owner_or_text():
    docs = sources()
    plan = plan_for(docs)
    admitted = apply(docs, plan)
    canonical = set()
    for old, new in zip(docs, admitted, strict=True):
        assert new.page == old.document.page and new.admission_policy_hash == admission_hash(plan)
        for original, unit in zip(old.document.units, new.units, strict=True):
            assert unit.doctor_name == original.doctor_name
            assert unit.doctor_id == original.doctor_id
            assert unit.context == original.context and unit.segments == original.segments
            if unit.doctor_name:
                assert unit.canonical_doctor_name == "Example Preferred"
                canonical.add(unit.canonical_doctor_id)
        for chunk in prepare_document(new).chunks:
            assert chunk.admission_policy_hash == admission_hash(plan)
            assert chunk.token_count is None and not chunk.embedding_ready
    assert len(canonical) == 1


def test_legacy_document_digest_and_roundtrip_keep_absent_admission_fields_absent():
    document = sources()[0]
    fields = {"canonical_doctor_id", "canonical_doctor_name", "source_issue_codes"}
    legacy_json = document.model_dump_json(
        exclude={
            "document": {"admission_policy_hash": True, "units": {"__all__": fields}},
            "chunks": {"__all__": fields | {"admission_policy_hash"}},
        }
    )
    legacy = type(document).model_validate_json(legacy_json)
    assert prepared_document_json(legacy) == legacy_json
    assert prepared_digest((legacy,)) == stable_id("prepared-bundle-v1", legacy_json)
    assert prepared_digest(
        (type(document).model_validate_json(prepared_document_json(legacy)),)
    ) == prepared_digest((legacy,))


def test_repeated_original_context_is_allowed_but_extra_occurrence_is_rejected():
    docs = list(sources())
    u = docs[0].document.units[0]
    changed = u.model_copy(update={"context": (*u.context, u.context[-1])})
    docs[0] = docs[0].model_copy(
        update={
            "document": docs[0].document.model_copy(
                update={"units": (changed, *docs[0].document.units[1:])}
            )
        }
    )
    docs = tuple(docs)
    plan = plan_for(docs)
    assert apply(docs, plan)[0].units[0].context == changed.context
    entries = list(plan.units)
    entries[0] = entries[0].model_copy(
        update={"context_keys": (*entries[0].context_keys, entries[0].context_keys[-1])}
    )
    with pytest.raises(ValueError, match="admission_projection_invalid"):
        apply(docs, plan.model_copy(update={"units": tuple(entries)}))


@pytest.mark.parametrize("scope", [("unknown",), ("doc-0", "doc-0")])
def test_primary_directory_scope_must_reference_distinct_admitted_documents(scope):
    docs = sources()
    plan = plan_for(docs)
    with pytest.raises(ValueError, match="admission_directory_scope_invalid"):
        apply(docs, plan.model_copy(update={"primary_directory_document_ids": scope}))


@pytest.mark.parametrize(
    "change",
    [
        "digest",
        "collection",
        "missing",
        "duplicate",
        "unit_digest",
        "invented_segment",
        "invented_heading",
        "alias_unknown",
        "alias_collision",
    ],
)
def test_invalid_or_incomplete_selection_fails_closed(change):
    docs = sources()
    plan = plan_for(docs).model_copy(update={"primary_directory_document_ids": ("doc-0",)})
    entries = list(plan.units)
    if change == "digest":
        plan = plan.model_copy(update={"input_prepared_digest": "wrong"})
    elif change == "collection":
        plan = plan.model_copy(update={"collection_digest": "wrong"})
    elif change == "missing":
        plan = plan.model_copy(update={"units": tuple(entries[:-1])})
    elif change == "duplicate":
        plan = plan.model_copy(update={"units": (*entries, entries[0])})
    elif change == "alias_unknown":
        plan = plan.model_copy(
            update={
                "aliases": (
                    DoctorAlias(
                        preferred_name="Unknown",
                        literal_source_names=("Unknown One", "Unknown Two"),
                    ),
                )
            }
        )
    elif change == "alias_collision":
        plan = plan.model_copy(update={"aliases": (*plan.aliases, plan.aliases[0])})
    else:
        field, value = {
            "unit_digest": ("unit_digest", "wrong"),
            "invented_segment": ("segment_keys", ("invented",)),
            "invented_heading": ("section_path", ("Invented department",)),
        }[change]
        entries[0] = entries[0].model_copy(update={field: value})
        plan = plan.model_copy(update={"units": tuple(entries)})
    with pytest.raises(ValueError):
        apply(docs, plan)


def test_department_context_removal_and_heading_only_service_preserve_actual_source():
    docs = sources()
    plan = plan_for(docs)
    entries = []
    for doc in docs:
        for u in doc.document.units:
            entry = selection(doc, u)
            if u.doctor_name:
                entry = selection(
                    doc,
                    u,
                    context_keys=tuple(
                        segment_key(s) for s in u.context if s.text != "Department label"
                    ),
                    section_path=tuple(s for s in u.section_path if s != "Department label"),
                    source_issue_codes=("department_title_non_authoritative",),
                )
            elif any(s.text == "Damaged source copy." for s in u.segments):
                heading = next(s for s in u.context if s.text == "Service")
                entry = selection(doc, u, segment_keys=(segment_key(heading),))
            entries.append(entry)
    admitted = apply(docs, plan.model_copy(update={"units": tuple(entries)}))
    for d in admitted:
        for c in prepare_document(d).chunks:
            assert "Damaged source copy." not in c.retrieval_text
            if c.doctor_name:
                assert "Department label" not in c.retrieval_text
        assert any("Service" in c.retrieval_text for c in prepare_document(d).chunks)


def test_owner_context_cannot_be_removed():
    docs = sources()
    plan = plan_for(docs)
    entries = list(plan.units)
    i = next(
        i
        for i, s in enumerate(entries)
        if next(u for u in docs[0].document.units if u.unit_id == s.unit_id).doctor_name
    )
    unit = next(u for u in docs[0].document.units if u.unit_id == entries[i].unit_id)
    entries[i] = selection(
        docs[0],
        unit,
        context_keys=tuple(segment_key(s) for s in unit.context if s.text != unit.doctor_name),
        section_path=tuple(s for s in unit.section_path if s != unit.doctor_name),
    )
    with pytest.raises(ValueError, match="admission_owner_context_removed"):
        apply(docs, plan.model_copy(update={"units": tuple(entries)}))


def test_admit_cli_receipt_is_bound_and_does_not_bypass_embedding_gates(tmp_path):
    docs = sources()
    plan = plan_for(docs).model_copy(update={"primary_directory_document_ids": ("doc-0",)})
    audit = build_audit(
        docs,
        snapshot_id=plan.snapshot_id,
        collection_digest=plan.collection_digest,
        crawl_coverage_confirmed=True,
    )
    original = tmp_path / "original"
    output = tmp_path / "admitted"
    policy = tmp_path / "plan.json"
    write_bundle(original, docs, audit)
    policy.write_text(plan.model_dump_json(), encoding="utf-8")
    summary = admit_bundle(original, policy, output)
    receipt = json.loads((output / "metadata/source-admission-receipt.json").read_bytes())
    approval = ReviewApproval.model_validate_json((output / "review-template.json").read_bytes())
    assert receipt["policy_hash"] == admission_hash(plan)
    assert receipt["input_prepared_digest"] == prepared_digest(docs)
    assert receipt["source_decisions_applied"] and not receipt["embedding_approval"]
    assert approval.source_reviewed and not approval.approved
    assert not summary["embedding_ready"] and not summary["approved"]
    assert summary["directory_coverage_status"] == "reviewed_primary_directory_sources"
    directory = json.loads((output / "metadata/primary-directory.json").read_bytes())
    assert directory["prepared_digest"] == receipt["output_prepared_digest"]
    assert directory["pages"][0]["named_entry_count"] == 1
    new_docs = tuple(prepare_document(d) for d in apply(docs, plan))
    new_audit = build_audit(
        new_docs,
        snapshot_id=plan.snapshot_id,
        collection_digest=plan.collection_digest,
        crawl_coverage_confirmed=True,
    )
    with pytest.raises(ValueError, match="preparation_not_embedding_ready"):
        validate_approval(
            new_docs,
            new_audit,
            approval.model_copy(
                update={"approved": True, "accepted_gap_codes": new_audit.gap_codes}
            ),
        )
    before = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError):
        admit_bundle(original, policy, output)
    assert before == {
        str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()
    }
