"""Verify the chunk-to-point mapping of a token-validated corpus bundle.

The admitted bundle is a draft: it carries no verified token count, so the
structure-aware preparation could not enforce the safety ceiling and an
oversized unit stayed as a single over-limit chunk. The counting step
re-prepares with the pinned verified counter and splits such a unit at its
existing boundaries, so the counted bundle can hold more chunks than the
admitted one.

This script proves, on the data rather than by assertion:

  * which unit changed, and that the change is a necessary split, not a
    duplicate;
  * that the split's text and source spans are continuous and complete;
  * that every admitted unit still has a chunk and every chunk still resolves
    to an admitted unit;
  * that every chunk's ownership, provenance and token bound hold;
  * that the points the candidate writer will upload are exactly one per
    chunk, with no identifier collision.

Usage:
    python scripts/verify_chunk_point_mapping.py \
        --admitted data/processed/m7-admitted-v1 \
        --validated data/processed/m7-token-validated-v1
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
from typing import Any

from telescope_rag.ingestion.deduplication import embedding_input_key
from telescope_rag.ingestion.models import PreparedChunk, PreparedDocument
from telescope_rag.providers.qwen_tokenizer import QwenPreparationCounter

TOKENIZER = ".tools/qwen-tokenizer/1d8ad4ca9b3dd8059ad90a75d4983776a23d44af/tokenizer.json"
CEILING = 1200


def load(directory: pathlib.Path) -> dict[str, PreparedDocument]:
    out: dict[str, PreparedDocument] = {}
    for path in sorted(directory.glob("*.json")):
        if len(path.stem) == 64:
            document = PreparedDocument.model_validate_json(path.read_bytes())
            out[document.document.page.canonical_url] = document
    return out


def spans(chunk: PreparedChunk) -> set[tuple[str, int, int]]:
    return {(s.locator, s.start, s.end) for s in chunk.source_spans}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admitted", type=pathlib.Path, required=True)
    parser.add_argument("--validated", type=pathlib.Path, required=True)
    parser.add_argument("--tokenizer", type=pathlib.Path, default=pathlib.Path(TOKENIZER))
    args = parser.parse_args()

    admitted = load(args.admitted)
    validated = load(args.validated)
    admitted_chunks = [c for d in admitted.values() for c in d.chunks]
    validated_chunks = [c for d in validated.values() for c in d.chunks]

    admitted_by_unit: dict[str, list[PreparedChunk]] = collections.defaultdict(list)
    validated_by_unit: dict[str, list[PreparedChunk]] = collections.defaultdict(list)
    for chunk in admitted_chunks:
        admitted_by_unit[chunk.parent_block_id].append(chunk)
    for chunk in validated_chunks:
        validated_by_unit[chunk.parent_block_id].append(chunk)

    report: dict[str, Any] = {
        "admitted_chunks": len(admitted_chunks),
        "validated_chunks": len(validated_chunks),
        "difference": len(validated_chunks) - len(admitted_chunks),
        "splits": [],
    }

    counter = QwenPreparationCounter(args.tokenizer)
    for unit_id, after in validated_by_unit.items():
        before = admitted_by_unit.get(unit_id, [])
        if len(before) == len(after):
            continue
        original = before[0]
        joined = "\n\n".join(chunk.original_text for chunk in after)
        report["splits"].append(
            {
                "unit_id": unit_id,
                "canonical_url": after[0].canonical_url,
                "admitted_chunks": len(before),
                "validated_chunks": len(after),
                "unsplit_verified_tokens": counter.count(original.retrieval_text),
                "ceiling": CEILING,
                "split_tokens": [chunk.token_count for chunk in after],
                "text_continuity_exact": joined == original.original_text,
                "segment_lists_equal": original.original_text.split("\n\n")
                == [t for chunk in after for t in chunk.original_text.split("\n\n")],
                "span_overlap": len(spans(after[0]) & spans(after[1])),
                "span_union": len(spans(after[0]) | spans(after[1])),
                "admitted_spans": len(spans(original)),
                "union_covers_admitted": (spans(after[0]) | spans(after[1])) == spans(original),
                "within_ceiling": all(
                    chunk.token_count is not None and chunk.token_count <= CEILING
                    for chunk in after
                ),
            }
        )

    admitted_units = {u.unit_id for d in admitted.values() for u in d.document.units}
    validated_units = {u.unit_id for d in validated.values() for u in d.document.units}
    unit_index = {
        (d.document.page.document_id, u.unit_id): (d, u)
        for d in validated.values()
        for u in d.document.units
    }
    problems = []
    for chunk in validated_chunks:
        entry = unit_index.get((chunk.document_id, chunk.parent_block_id))
        if entry is None:
            problems.append(("unknown_parent_unit", chunk.canonical_url, chunk.chunk_id))
            continue
        document, unit = entry
        page = document.document.page
        if (
            chunk.canonical_url != page.canonical_url
            or chunk.snapshot_id != page.snapshot_id
            or chunk.fetched_at != page.fetched_at
            or chunk.page_title != document.document.title
            or chunk.doctor_id != unit.doctor_id
            or chunk.doctor_name != unit.doctor_name
            or not chunk.source_spans
            or chunk.token_count is None
            or chunk.token_count > CEILING
            or not chunk.embedding_ready
        ):
            problems.append(("ownership_or_bound_mismatch", chunk.canonical_url, chunk.chunk_id))

    groups: dict[str, list[PreparedChunk]] = collections.defaultdict(list)
    for chunk in validated_chunks:
        groups[embedding_input_key(chunk)].append(chunk)

    report.update(
        {
            "admitted_units": len(admitted_units),
            "validated_units": len(validated_units),
            "admitted_units_without_a_chunk": len(admitted_units - set(validated_by_unit)),
            "validated_units_not_admitted": len(validated_units - admitted_units),
            "provenance_or_bound_problems": len(problems),
            "chunks_over_ceiling": sum(
                1 for c in validated_chunks if c.token_count and c.token_count > CEILING
            ),
            "distinct_chunk_ids": len({c.chunk_id for c in validated_chunks}),
            "distinct_point_ids": len({c.point_id for c in validated_chunks}),
            "points_to_be_written": len(validated_chunks),
            "distinct_embedding_inputs": len(groups),
            "reuse_occurrences": len(validated_chunks) - len(groups),
            "point_id_collisions": len(validated_chunks)
            - len({c.point_id for c in validated_chunks}),
            "shared_vector_groups_with_repeated_url": [
                {
                    "canonical_url": members[0].canonical_url,
                    "members": len(members),
                    "distinct_chunk_ids": len({c.chunk_id for c in members}),
                    "distinct_point_ids": len({c.point_id for c in members}),
                    "distinct_locators": len({s.locator for c in members for s in c.source_spans}),
                }
                for members in groups.values()
                if len(members) > 1 and len({c.canonical_url for c in members}) < len(members)
            ],
        }
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
