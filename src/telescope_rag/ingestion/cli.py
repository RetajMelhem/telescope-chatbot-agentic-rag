"""Read-only collection and draft preparation commands; no inference or index publication."""

import argparse
import asyncio
import hashlib
import json
import uuid
from pathlib import Path

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.admission import AdmissionPlan, admission_hash, apply_admission
from telescope_rag.ingestion.collection import CollectionManifest, collect
from telescope_rag.ingestion.extraction import extract_page
from telescope_rag.ingestion.models import PreparedDocument, RawPage
from telescope_rag.ingestion.preparation import prepare_document
from telescope_rag.ingestion.review import (
    PreparationAudit,
    ReviewApproval,
    build_audit,
    prepared_digest,
    write_bundle,
)
from telescope_rag.ingestion.runner import read_secret, run_candidate
from telescope_rag.ingestion.token_validation import count_admitted_bundle


def prepare_snapshot(snapshot: Path, output: Path, *, max_tokens: int = 1200) -> dict:
    """Prepare all collected pages, binding the audit to the exact raw manifest."""
    manifest_path = snapshot / "manifest.json"
    if manifest_path.stat().st_size > 600_000_000:
        raise ValueError("collection_manifest_too_large")
    raw_manifest = manifest_path.read_bytes()
    manifest = CollectionManifest.model_validate_json(raw_manifest)
    if len(manifest.pages) > 250:
        raise ValueError("collection_page_count_invalid")
    paths = sorted((snapshot / "raw").glob("*.json"))
    if len(paths) != len(manifest.pages):
        raise ValueError("raw_page_manifest_mismatch")
    expected = {page.document_id: page for page in manifest.pages}
    if len(expected) != len(paths):
        raise ValueError("duplicate_raw_page")
    pages = []
    for path in paths:
        if path.stat().st_size > 12_000_000:
            raise ValueError("raw_page_too_large")
        page = RawPage.model_validate_json(path.read_bytes())
        if expected.pop(page.document_id, None) != page or page.snapshot_id != manifest.snapshot_id:
            raise ValueError("raw_page_manifest_mismatch")
        # Validate the immutable original bytes as well as the decoded representation.
        html = path.with_suffix(".html")
        if not html.is_file() or html.stat().st_size > 2_000_000:
            raise ValueError("raw_html_missing_or_oversized")
        original_bytes = html.read_bytes()
        if hashlib.sha256(original_bytes).hexdigest() != page.content_hash:
            raise ValueError("raw_content_hash_mismatch")
        if original_bytes.decode("utf-8-sig", errors="strict") != page.html:
            raise ValueError("raw_decoded_html_mismatch")
        pages.append(page)
    if not pages or expected:
        raise ValueError("raw_snapshot_empty_or_incomplete")
    documents = tuple(prepare_document(extract_page(page), max_tokens=max_tokens) for page in pages)
    audit = build_audit(
        documents,
        snapshot_id=manifest.snapshot_id,
        crawl_gap_codes=manifest.coverage_gaps,
        collection_digest=hashlib.sha256(raw_manifest).hexdigest(),
        crawl_coverage_confirmed=manifest.coverage_complete,
    )
    write_bundle(output, documents, audit)
    return json.loads((output / "summary.json").read_text(encoding="utf-8"))


def admit_bundle(bundle: Path, plan_path: Path, output: Path, *, max_tokens: int = 1200) -> dict:
    """Apply a reviewed sealed selection, then prepare a new immutable draft bundle."""
    if plan_path.stat().st_size > 20_000_000 or (bundle / "audit.json").stat().st_size > 20_000_000:
        raise ValueError("admission_record_too_large")
    plan = AdmissionPlan.model_validate_json(plan_path.read_bytes())
    audit = PreparationAudit.model_validate_json((bundle / "audit.json").read_bytes())
    paths = sorted(
        p
        for p in bundle.glob("*.json")
        if p.name not in {"audit.json", "summary.json", "review-template.json"}
    )
    if not 0 < len(paths) <= 250 or any(p.stat().st_size > 12_000_000 for p in paths):
        raise ValueError("admission_bundle_invalid")
    original = tuple(PreparedDocument.model_validate_json(p.read_bytes()) for p in paths)
    if audit.document_count != len(original) or audit.prepared_digest != prepared_digest(original):
        raise ValueError("admission_bundle_invalid")
    extracted = apply_admission(original, plan, collection_digest=audit.collection_digest)
    documents = tuple(prepare_document(doc, max_tokens=max_tokens) for doc in extracted)
    preparation_gaps = {g.code for d in original for g in (*d.document.gaps, *d.gaps)}
    selected_audit = build_audit(
        documents,
        snapshot_id=plan.snapshot_id,
        collection_digest=plan.collection_digest,
        crawl_coverage_confirmed=audit.crawl_coverage_complete,
        crawl_gap_codes=tuple(g for g in audit.gap_codes if g not in preparation_gaps),
    )
    primary_directory = []
    for doc in documents:
        if doc.document.page.document_id not in plan.primary_directory_document_ids:
            continue
        names: dict[str, list] = {}
        for entry in selected_audit.directory:
            if entry.canonical_url == doc.document.page.canonical_url:
                names.setdefault(entry.name, []).append(entry.model_dump(mode="json"))
        primary_directory.append(
            {
                "document_id": doc.document.page.document_id,
                "canonical_url": doc.document.page.canonical_url,
                "named_entry_count": len(names),
                "entries": names,
                "scope": (
                    "Published named entries on this selected page; "
                    "not inferred unique clinicians across languages."
                ),
            }
        )
    if primary_directory:
        selected_audit = selected_audit.model_copy(
            update={"directory_coverage_status": "reviewed_primary_directory_sources"}
        )
    write_bundle(output, documents, selected_audit)
    receipt = {
        "source_decisions_applied": True,
        "decision_authority": plan.decision_authority,
        "policy_hash": admission_hash(plan),
        "collection_digest": plan.collection_digest,
        "input_prepared_digest": plan.input_prepared_digest,
        "output_prepared_digest": selected_audit.prepared_digest,
        "original_document_count": len(original),
        "admitted_document_count": len(documents),
        "excluded_document_ids": plan.excluded_document_ids,
        "excluded_unit_count": sum(u.disposition == "exclude" for u in plan.units),
        "embedding_approval": False,
        "clinical_truth_certified": False,
    }
    (output / "metadata" / "source-admission-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "metadata" / "source-admission-plan.json").write_text(
        plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output / "metadata" / "primary-directory.json").write_text(
        json.dumps(
            {
                "policy_hash": admission_hash(plan),
                "prepared_digest": selected_audit.prepared_digest,
                "pages": primary_directory,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "review-template.json").write_text(
        ReviewApproval(
            snapshot_id=selected_audit.snapshot_id,
            prepared_digest=selected_audit.prepared_digest,
            collection_digest=selected_audit.collection_digest,
            reviewer=plan.decision_authority,
            source_reviewed=True,
            approved=False,
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    return json.loads((output / "summary.json").read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect and prepare public clinic evidence for review."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    collection = commands.add_parser(
        "collect", help="GET public pages into a new immutable snapshot"
    )
    collection.add_argument("--snapshot-id", default=None)
    collection.add_argument("--output", type=Path, required=True)
    collection.add_argument("--max-pages", type=int, default=250)
    preparation = commands.add_parser(
        "prepare", help="Create draft structural chunks; no embedding"
    )
    preparation.add_argument("--snapshot", type=Path, required=True)
    preparation.add_argument("--output", type=Path, required=True)
    admission = commands.add_parser(
        "admit", help="Apply digest-bound source decisions; no embedding"
    )
    admission.add_argument("--bundle", type=Path, required=True)
    admission.add_argument("--plan", type=Path, required=True)
    admission.add_argument("--output", type=Path, required=True)
    counting = commands.add_parser(
        "count", help="Count admitted source with the pinned offline Qwen tokenizer; no embedding"
    )
    counting.add_argument("--bundle", type=Path, required=True)
    counting.add_argument("--tokenizer", type=Path, required=True)
    counting.add_argument("--output", type=Path, required=True)
    counting.add_argument(
        "--profile",
        choices=("upstream", "openrouter-deepinfra-v1"),
        default="upstream",
        help="Select a pinned format; upstream alone cannot enable embedding",
    )
    indexing = commands.add_parser(
        "index", help="Explicit paid embedding and unpublished local candidate run"
    )
    indexing.add_argument("--bundle", type=Path, required=True)
    indexing.add_argument("--tokenizer", type=Path, required=True)
    indexing.add_argument("--cache", type=Path, required=True)
    indexing.add_argument("--output", type=Path, required=True)
    indexing.add_argument("--qdrant-write-key-file", type=Path, required=True)
    indexing.add_argument("--qdrant-read-key-file", type=Path, required=True)
    indexing.add_argument("--batch-size", type=int, choices=range(1, 17), default=16)
    indexing.add_argument("--max-requests", type=int, default=128)
    indexing.add_argument("--max-input-tokens", type=int, default=100000)
    indexing.add_argument("--deadline-seconds", type=float, default=600)
    indexing.add_argument(
        "--execute", action="store_true", help="Required explicit dispatch selection"
    )
    args = parser.parse_args()
    try:
        if args.command == "collect":
            if not 1 <= args.max_pages <= 250:
                raise ValueError("max_pages_out_of_bounds")
            # Collection is independent of the user's provider/Qdrant secrets and dotenv file.
            settings = Settings(
                _env_file=None,
                app_env="development",
                openrouter_api_key="",
                qdrant_api_key="",
                crawl_max_pages=args.max_pages,
            )
            manifest = asyncio.run(
                collect(settings, args.output, args.snapshot_id or uuid.uuid4().hex)
            )
            summary = {
                "snapshot_id": manifest.snapshot_id,
                "collected_pages": len(manifest.pages),
                "coverage_complete": manifest.coverage_complete,
                "coverage_gaps": manifest.coverage_gaps,
                "approved": False,
            }
        elif args.command == "admit":
            summary = admit_bundle(args.bundle, args.plan, args.output)
        elif args.command == "count":
            summary = count_admitted_bundle(
                args.bundle, args.output, args.tokenizer, profile=args.profile
            )
        elif args.command == "index":
            if not args.execute:
                raise ValueError("index_execution_not_selected")
            settings = Settings(
                provider_max_retries=0,
                max_embedding_batch_size=args.batch_size,
                qdrant_api_key=read_secret(args.qdrant_write_key_file),
            )
            summary = asyncio.run(
                run_candidate(
                    args.bundle,
                    args.tokenizer,
                    args.cache,
                    args.output,
                    settings,
                    read_secret(args.qdrant_read_key_file),
                    max_requests=args.max_requests,
                    max_input_tokens=args.max_input_tokens,
                    deadline_seconds=args.deadline_seconds,
                    progress=lambda receipt: print(json.dumps(receipt), flush=True),
                )
            )
        else:
            summary = prepare_snapshot(args.snapshot, args.output)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception:
        # User-visible CLI diagnostics do not print external HTML, keys, or local configuration.
        parser.exit(1, "Ingestion failed; inspect the bounded snapshot/audit artifacts.\n")


if __name__ == "__main__":
    main()
