"""Offline counted rebuild of reviewed admissions; never approves or calls a provider."""

import json
from pathlib import Path
from typing import Literal

from telescope_rag.ingestion.admission import AdmissionPlan, admission_hash
from telescope_rag.ingestion.models import PreparedDocument
from telescope_rag.ingestion.preparation import prepare_document
from telescope_rag.ingestion.review import (
    PreparationAudit,
    ReviewApproval,
    build_audit,
    prepared_digest,
    write_bundle,
)
from telescope_rag.providers.qwen_tokenizer import (
    QwenPreparationCounter,
    candidate_qwen_format,
    hosted_qwen_format,
)


def _read(path: Path, maximum: int = 20_000_000) -> bytes:
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("counted_bundle_record_invalid")
    return path.read_bytes()


def count_admitted_bundle(
    bundle: Path,
    output: Path,
    tokenizer_path: Path,
    *,
    profile: Literal["upstream", "openrouter-deepinfra-v1"] = "upstream",
) -> dict:
    """Preserve selected source documents and bind the rebuild to their exact digests.

    The default uses the upstream-only profile. The named hosted profile was
    verified separately; neither choice grants source approval or dispatches HTTP.
    """
    if output.exists():
        raise ValueError("counted_bundle_output_exists")
    audit = PreparationAudit.model_validate_json(_read(bundle / "audit.json"))
    review = ReviewApproval.model_validate_json(_read(bundle / "review-template.json"))
    plan_raw = _read(bundle / "metadata/source-admission-plan.json")
    receipt_raw = _read(bundle / "metadata/source-admission-receipt.json")
    plan = AdmissionPlan.model_validate_json(plan_raw)
    receipt = json.loads(receipt_raw)
    paths = sorted(
        p
        for p in bundle.glob("*.json")
        if p.name not in {"audit.json", "summary.json", "review-template.json"}
    )
    if not 0 < len(paths) <= 250:
        raise ValueError("counted_bundle_size_invalid")
    original = tuple(PreparedDocument.model_validate_json(_read(p, 12_000_000)) for p in paths)
    digest = prepared_digest(original)
    policy = admission_hash(plan)
    if (
        digest != audit.prepared_digest
        or len(original) != audit.document_count
        or sum(len(d.chunks) for d in original) != audit.chunk_count
        or review.prepared_digest != digest
        or review.snapshot_id != audit.snapshot_id
        or not review.source_reviewed
        or not audit.collection_digest
        or review.collection_digest != audit.collection_digest
        or plan.collection_digest != audit.collection_digest
        or plan.snapshot_id != audit.snapshot_id
        or receipt.get("output_prepared_digest") != digest
        or receipt.get("collection_digest") != audit.collection_digest
        or receipt.get("input_prepared_digest") != plan.input_prepared_digest
        or receipt.get("policy_hash") != policy
        or receipt.get("source_decisions_applied") is not True
        or receipt.get("admitted_document_count") != len(original)
        or any(
            d.document.admission_policy_hash != policy
            or d.document.page.snapshot_id != audit.snapshot_id
            for d in original
        )
    ):
        raise ValueError("counted_bundle_source_binding_invalid")
    counter = QwenPreparationCounter(tokenizer_path)
    if profile not in {"upstream", "openrouter-deepinfra-v1"}:
        raise ValueError("counted_bundle_profile_invalid")
    format = candidate_qwen_format() if profile == "upstream" else hosted_qwen_format()
    counted = tuple(
        prepare_document(d.document, counter=counter, embedding_format=format) for d in original
    )
    preparation_gaps = {g.code for d in original for g in (*d.document.gaps, *d.gaps)}
    rebuilt = build_audit(
        counted,
        snapshot_id=audit.snapshot_id,
        collection_digest=audit.collection_digest,
        crawl_coverage_confirmed=audit.crawl_coverage_complete,
        crawl_gap_codes=tuple(g for g in audit.gap_codes if g not in preparation_gaps),
    ).model_copy(update={"directory_coverage_status": audit.directory_coverage_status})
    # Source decisions and original DOM coordinates are unchanged, even if the
    # token ceiling splits an oversized unit at a supported structural boundary.
    if any(a.document != b.document for a, b in zip(original, counted, strict=True)):
        raise ValueError("counted_bundle_source_changed")
    directories = []
    for document in counted:
        if document.document.page.document_id not in plan.primary_directory_document_ids:
            continue
        entries: dict[str, list] = {}
        for entry in rebuilt.directory:
            if entry.canonical_url == document.document.page.canonical_url:
                entries.setdefault(entry.name, []).append(entry.model_dump(mode="json"))
        directories.append(
            {
                "document_id": document.document.page.document_id,
                "canonical_url": document.document.page.canonical_url,
                "named_entry_count": len(entries),
                "entries": entries,
                "scope": (
                    "Published named entries; not inferred unique clinicians across languages."
                ),
            }
        )
    if len(directories) != len(plan.primary_directory_document_ids):
        raise ValueError("counted_bundle_directory_scope_invalid")
    write_bundle(output, counted, rebuilt)
    metadata = output / "metadata"
    (metadata / "source-admission-plan.json").write_bytes(plan_raw)
    # The prior receipt still binds the prior admission. Do not relabel it as the
    # newly counted bundle; the new rebuild receipt records this explicit chain.
    (metadata / "parent-source-admission-receipt.json").write_bytes(receipt_raw)
    (metadata / "primary-directory.json").write_text(
        json.dumps(
            {
                "policy_hash": policy,
                "prepared_digest": rebuilt.prepared_digest,
                "pages": directories,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (metadata / "token-count-receipt.json").write_text(
        json.dumps(
            {
                "input_prepared_digest": digest,
                "output_prepared_digest": rebuilt.prepared_digest,
                "collection_digest": audit.collection_digest,
                "admission_policy_hash": policy,
                "source_documents_unchanged": True,
                "counter": counter.receipt(),
                "candidate_format": format.model_dump(),
                "hosted_profile_verified": format.verified,
                "embedding_ready": rebuilt.embedding_ready,
                "approved": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "review-template.json").write_text(
        ReviewApproval(
            snapshot_id=rebuilt.snapshot_id,
            prepared_digest=rebuilt.prepared_digest,
            collection_digest=rebuilt.collection_digest,
            reviewer=review.reviewer,
            source_reviewed=True,
            approved=False,
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    return json.loads((output / "summary.json").read_bytes())
