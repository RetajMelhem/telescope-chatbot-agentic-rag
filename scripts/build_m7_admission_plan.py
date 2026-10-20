"""Build the reviewed source-admission plan for the m7 public snapshot.

The plan accounts for every admitted source unit. It excludes the pages the
repository owner approved as template or placeholder material, and it applies
the source decisions that were already resolved for this clinic. It never
rewrites published content and never merges two sources into a new claim.

Every exclusion is recorded with a reason. The output is bound to the exact
prepared digest and collection digest of the bundle it was built from, so it
cannot be applied to different source bytes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from telescope_rag.ingestion.admission import (
    AdmissionPlan,
    DoctorAlias,
    UnitSelection,
    segment_key,
    unit_digest,
)
from telescope_rag.ingestion.models import ContentUnit, PreparedDocument
from telescope_rag.ingestion.review import prepared_digest

# Pages that publish no clinic content. The repository owner approved excluding
# these from the indexed knowledge.
EXCLUDED_PATH_FRAGMENTS = (
    "/lorem-ipsum-is-simply-dummy-text-of-the-printing-and-typesetting-industry",
    "/blogs/",
    "/blogs/2/",
    "/tag/general/",
    "/category/general/",
    "/category/medical/",
    "/category/test/",
    "/category/uncategorized/",
    "/testt/",
)

# The Extra pages publish the vision-correction comparison matrix, including the
# ICL row that the lasik page does not carry. They are retained for that reason
# and are not treated as template pages.
RETAINED_DERIVATIVE_PATHS = ("/extra/", "/ar/extra/")

# Source decisions already resolved for this clinic and carried forward.
DISPUTED_STRABISMUS_TIMING = "2 Weeks Final Alignment"

ALIASES = (
    DoctorAlias(
        preferred_name="Lina Hamadneh",
        literal_source_names=(
            "Dr. Lina Hamadneh",
            "Dr. Lina Hamarneh",
            "د. لينا حمادنة",
            "د. لينا حمارنة",
        ),
    ),
    DoctorAlias(
        preferred_name="Motasim Masalmeh",
        literal_source_names=("Dr. Motasim Masalmeh", "Dr. Moatasem Masalmeh"),
    ),
    DoctorAlias(
        preferred_name="Mutaz Gharaibeh",
        literal_source_names=("Prof. Dr. Mutaz Gharaibeh", "Dr. Moataz Gharaibeh"),
    ),
)

DECISION_NOTES = (
    "A fresh public snapshot of the same clinic site was collected on 2026-10-20: "
    "127 pages, complete bounded coverage, no crawl gaps.",
    "Template and placeholder pages are excluded from the indexed knowledge: the "
    "twenty lorem-ipsum posts in both languages, the empty blog, tag and category "
    "listings, and the empty test pages.",
    "The Extra pages are retained. They publish the published vision-correction "
    "comparison matrix, including the ICL row that the lasik page does not carry.",
    "The disputed strabismus recovery cards are excluded, retaining the unaffected "
    "strabismus information on the same page.",
    "The published LASIK recovery-speed claims and the PRK slower claim are retained unchanged.",
    "Explicit main-directory and profile roles stay authoritative; a derivative "
    "directory title is not a specialty.",
    "The user-confirmed doctor name pairs and their preferred English names are "
    "carried forward as separate canonical metadata over unchanged literal owners.",
    "Two doctors sharing a specialty remain independent records.",
    "No correction, translation or new relationship is supplied by this plan.",
    "This plan authorises source selection only. It approves no embedding, index "
    "write, alias publication or provider request.",
)


def document_is_excluded(url: str) -> bool:
    path = url.replace("https://telescopecenter.com", "") or "/"
    if any(path.endswith(fragment) for fragment in RETAINED_DERIVATIVE_PATHS):
        return False
    return any(fragment in path for fragment in EXCLUDED_PATH_FRAGMENTS)


def unit_signatures(unit: ContentUnit) -> tuple[str, ...]:
    """Exact source identities a unit can be recognised by in another snapshot.

    A doctor unit is identified by its literal owner name, because the same
    published card is carried by several pages with different titles. Every
    other unit is identified by its own normalized body text.
    """
    body = " ".join(segment.text for segment in unit.segments).strip()
    if unit.doctor_name:
        return (f"doctor:{unit.doctor_name}",)
    return (f"body:{body}",)


def carried_issue_codes(
    baseline: tuple[PreparedDocument, ...],
) -> tuple[dict[str, tuple[str, ...]], list[str]]:
    """Source issue codes carried forward by exact source identity.

    A previously reviewed decision attaches to the published occurrence it was
    reviewed on. The occurrence is recognised by its exact body text or its
    literal doctor name, not by a keyword rule.
    """
    codes: dict[str, tuple[str, ...]] = {}
    for document in baseline:
        for unit in document.document.units:
            if not unit.source_issue_codes:
                continue
            for signature in unit_signatures(unit):
                codes.setdefault(signature, tuple(unit.source_issue_codes))
    return codes, sorted(codes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    documents = tuple(
        PreparedDocument.model_validate_json(path.read_bytes())
        for path in sorted(args.bundle.glob("*.json"))
        if len(path.stem) == 64
    )
    if not documents:
        raise SystemExit("bundle has no prepared documents")
    baseline = tuple(
        PreparedDocument.model_validate_json(path.read_bytes())
        for path in sorted(args.baseline.glob("*.json"))
        if len(path.stem) == 64
    )
    if not baseline:
        raise SystemExit("baseline has no prepared documents")
    carried, carried_signatures = carried_issue_codes(baseline)
    # A published block can be regrouped by a later extraction while its text
    # is unchanged. A reviewed decision still attaches to that block, so the
    # exact body text is also matched by containment in either direction.
    baseline_bodies = {
        signature[len("body:") :]: carried[signature]
        for signature in carried_signatures
        if signature.startswith("body:")
    }
    audit = json.loads((args.bundle / "audit.json").read_bytes())
    collection_digest = audit["collection_digest"]
    if not collection_digest:
        raise SystemExit("bundle audit has no collection digest")

    excluded_documents = []
    primary_directory = []
    selections: list[UnitSelection] = []
    applied_signatures: set[str] = set()
    for document in documents:
        page = document.document.page
        url = page.canonical_url
        excluded = document_is_excluded(url)
        if excluded:
            excluded_documents.append(page.document_id)
        if url in {
            "https://telescopecenter.com/doctors/",
            "https://telescopecenter.com/ar/doctors/",
        }:
            primary_directory.append(page.document_id)
        for unit in document.document.units:
            text = " ".join(segment.text for segment in unit.segments)
            disputed = DISPUTED_STRABISMUS_TIMING in text
            issue_codes: tuple[str, ...] = ()
            for signature in unit_signatures(unit):
                if signature in carried:
                    issue_codes = carried[signature]
                    applied_signatures.add(signature)
                    break
            if not issue_codes and text:
                for body, codes in baseline_bodies.items():
                    if body in text or text in body:
                        issue_codes = codes
                        applied_signatures.add(f"body:{body}")
                        break
            if excluded:
                disposition = "exclude"
                reason = "template_or_placeholder_page_excluded"
            elif disputed:
                disposition = "exclude"
                reason = "disputed_recovery_timing_card_excluded"
            else:
                disposition = "retain"
                reason = "published_source_retained"
            selections.append(
                UnitSelection(
                    document_id=page.document_id,
                    unit_id=unit.unit_id,
                    unit_digest=unit_digest(unit),
                    disposition=disposition,
                    segment_keys=()
                    if disposition == "exclude"
                    else tuple(segment_key(segment) for segment in unit.segments),
                    context_keys=()
                    if disposition == "exclude"
                    else tuple(segment_key(segment) for segment in unit.context),
                    section_path=() if disposition == "exclude" else unit.section_path,
                    reason=reason,
                    source_issue_codes=() if disposition == "exclude" else issue_codes,
                )
            )

    plan = AdmissionPlan(
        snapshot_id=documents[0].document.page.snapshot_id,
        collection_digest=collection_digest,
        input_prepared_digest=prepared_digest(documents),
        decision_authority="Repository owner approved template-page exclusion; "
        "previously resolved clinic source decisions carried forward",
        decision_notes=DECISION_NOTES,
        aliases=ALIASES,
        excluded_document_ids=tuple(excluded_documents),
        primary_directory_document_ids=tuple(primary_directory),
        accepted_exclusion_gaps=(
            "placeholder_document",
            "placeholder_content_quarantined",
            "unsupported_parallel_category_layout",
        ),
        units=tuple(selections),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    retained = sum(1 for s in selections if s.disposition == "retain")
    coded = sum(1 for s in selections if s.source_issue_codes)
    unmatched = [s for s in carried_signatures if s not in applied_signatures]
    print(
        json.dumps(
            {
                "documents": len(documents),
                "excluded_documents": len(excluded_documents),
                "primary_directory_documents": len(primary_directory),
                "units": len(selections),
                "retained_units": retained,
                "excluded_units": len(selections) - retained,
                "units_with_carried_issue_codes": coded,
                "carried_issue_code_signatures": len(carried_signatures),
                "carried_issue_codes_not_matched": len(unmatched),
                "input_prepared_digest": plan.input_prepared_digest,
                "collection_digest": plan.collection_digest,
            },
            indent=2,
        )
    )
    for signature in unmatched:
        print(f"  unmatched carried code: {signature[:160]!r}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
