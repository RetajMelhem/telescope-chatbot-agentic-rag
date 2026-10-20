"""Create the execution-approved copy of a token-validated corpus bundle.

The counted bundle is a draft: it carries a token-count receipt but no
reviewer approval and no embedding configuration, so the indexing command
cannot consume it. This script produces the exact execution copy that the
indexing command reads, without dispatching anything.

The copy differs from the counted bundle in exactly two metadata files:

  metadata/review-approved.json          the source review and its digests
  metadata/embedding-configuration.json  the pinned model, dimensions and format

Both are bound to the counted bundle's exact prepared digest and collection
digest. If the counted bundle changes, this script refuses to reuse an
approval that no longer matches it.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from telescope_rag.ingestion.indexing import EmbeddingConfiguration
from telescope_rag.ingestion.models import stable_id
from telescope_rag.ingestion.review import ReviewApproval
from telescope_rag.providers.qwen_tokenizer import hosted_qwen_format

MODEL = "qwen/qwen3-embedding-8b"
DIMENSIONS = 4096
PREPARATION_VERSION = "structure-nfc-v5"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Record the source review as approved. Required for the indexing command.",
    )
    args = parser.parse_args()

    receipt = json.loads((args.bundle / "metadata/token-count-receipt.json").read_bytes())
    audit = json.loads((args.bundle / "audit.json").read_bytes())
    prepared_digest = receipt["output_prepared_digest"]
    collection_digest = receipt["collection_digest"]
    if audit["prepared_digest"] != prepared_digest:
        raise SystemExit("counted bundle audit does not match the token-count receipt")
    if audit["collection_digest"] != collection_digest:
        raise SystemExit("counted bundle audit does not match the token-count receipt")
    if not audit["embedding_ready"]:
        raise SystemExit("counted bundle is not embedding ready")

    profile = hosted_qwen_format()
    configuration = EmbeddingConfiguration(
        model=MODEL,
        dimensions=DIMENSIONS,
        format_version=profile.version,
        format_hash=stable_id("embedding-format-v1", profile.model_dump_json()),
        preparation_version=PREPARATION_VERSION,
        tokenizer_version=receipt["counter"]["count_profile"],
    )
    approval = ReviewApproval(
        snapshot_id=receipt["input_prepared_digest"] and audit["snapshot_id"],
        prepared_digest=prepared_digest,
        collection_digest=collection_digest,
        reviewer=args.reviewer,
        approved=bool(args.approve),
        source_reviewed=True,
        accepted_gap_codes=tuple(audit.get("gap_codes", ())),
    )

    if args.output.exists():
        raise SystemExit("output directory already exists; refusing to overwrite it")
    shutil.copytree(args.bundle, args.output)
    metadata = args.output / "metadata"
    (metadata / "review-approved.json").write_text(
        approval.model_dump_json(indent=2), encoding="utf-8"
    )
    (metadata / "embedding-configuration.json").write_text(
        configuration.model_dump_json(indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "snapshot_id": approval.snapshot_id,
                "prepared_digest": prepared_digest,
                "collection_digest": collection_digest,
                "approved": approval.approved,
                "source_reviewed": approval.source_reviewed,
                "reviewer": approval.reviewer,
                "embedding_configuration": configuration.model_dump(mode="json"),
            },
            indent=2,
        )
    )
    if not approval.approved:
        print("approved=false: the indexing command will refuse this bundle")


if __name__ == "__main__":
    main()
