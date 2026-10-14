"""Read-only collection and draft preparation commands; no inference or index publication."""

import argparse
import asyncio
import hashlib
import json
import uuid
from pathlib import Path

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.collection import CollectionManifest, collect
from telescope_rag.ingestion.extraction import extract_page
from telescope_rag.ingestion.models import RawPage
from telescope_rag.ingestion.preparation import prepare_document
from telescope_rag.ingestion.review import build_audit, write_bundle


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
        else:
            summary = prepare_snapshot(args.snapshot, args.output)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception:
        # User-visible CLI diagnostics do not print external HTML, keys, or local configuration.
        parser.exit(1, "Ingestion failed; inspect the bounded snapshot/audit artifacts.\n")


if __name__ == "__main__":
    main()
