"""Offline integrity gates for LLM-authored planner cases; never a semantic judge.

Expected plans and source-use decisions are authored and independently reviewed
through language reasoning. This module only binds that evidence to exact inputs.
It cannot call a model, embed, query an index, or enable the public API.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from bs4 import BeautifulSoup
from pydantic import Field, model_validator

from scripts.retrieval_benchmark import canonical_bytes, load_corpus
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import ClosedRecord, DraftStatus, PlannerReply, WorkflowRequest
from telescope_rag.retrieval.assembly import EvidenceCatalog, limited_to_context


class PartReview(ClosedRecord):
    part_index: int = Field(ge=0, le=3)
    witness_chunk_ids: tuple[str, ...] = Field(max_length=100)
    expected_resolution: DraftStatus
    semantic_rationale: str = Field(min_length=1)
    protected_text: tuple[str, ...] = Field(min_length=1)


class PlannerFixture(ClosedRecord):
    case_id: str = Field(min_length=1, max_length=64)
    family_id: str = Field(min_length=1, max_length=32)
    language: Literal["en", "ar", "ar-JO"]
    split: Literal["development", "reserved_evaluation"]
    request: WorkflowRequest
    expected_plan: PlannerReply
    part_reviews: tuple[PartReview, ...] = Field(min_length=1, max_length=4)
    author_agent: str = Field(min_length=1)
    author_model: Literal["gpt-6.1-sol"]

    @model_validator(mode="after")
    def complete_records(self):
        if self.case_id != f"{self.family_id}-{self.language}":
            raise ValueError("case_identity_mismatch")
        if self.expected_plan.language != self.language:
            raise ValueError("case_plan_language_mismatch")
        if [r.part_index for r in self.part_reviews] != list(range(len(self.expected_plan.parts))):
            raise ValueError("part_review_coverage_mismatch")
        return self


def value_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def fixture_hash(case: PlannerFixture) -> str:
    return value_hash(case.model_dump(mode="json"))


def load_fixtures(paths: tuple[Path, ...]) -> tuple[PlannerFixture, ...]:
    return tuple(
        PlannerFixture.model_validate_json(line, strict=True)
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def validate_case(case: PlannerFixture, catalog: EvidenceCatalog) -> None:
    """Literal coverage, binding and policy checks only; no language classification."""
    plan = SourceBindings(catalog).validate(
        case.expected_plan, case.request, case.case_id, max_parts=4
    )
    for proposal, part, review in zip(
        case.expected_plan.parts, plan.assembly_request.parts, case.part_reviews, strict=True
    ):
        witnesses = review.witness_chunk_ids
        if len(set(witnesses)) != len(witnesses) or any(i not in catalog.chunks for i in witnesses):
            raise ValueError("witness_unknown_or_duplicate")
        originals = [
            case.request.query[part.start : part.end],
            *[case.request.history[i].content for i in proposal.history_indices],
        ]
        if any(not t.strip() or not any(t in s for s in originals) for t in review.protected_text):
            raise ValueError("protected_text_not_literal_part_or_bound_history")
        if part.state != "public":
            if witnesses or review.expected_resolution != part.state:
                raise ValueError("nonpublic_witness_or_resolution")
            continue
        if review.expected_resolution not in {"candidate", "unknown"}:
            raise ValueError("public_resolution_mismatch")
        members = set(catalog.scope_members(part.scope))
        if not set(witnesses) <= members:
            raise ValueError("witness_outside_exact_source_scope")
        if proposal.operation == "time_comparison" and review.expected_resolution != "unknown":
            raise ValueError("unimplemented_time_operation_cannot_claim_candidate")
        if review.expected_resolution == "candidate" and (
            not witnesses
            or any(limited_to_context(catalog.chunks[i], part.intended_use) for i in witnesses)
        ):
            raise ValueError("candidate_requires_eligible_selected_witnesses")
        # Selected witnesses are not an exhaustive relevance inventory. Complete
        # reads enumerate catalog membership, which can include context entries.


def validate_cohort(
    cases: tuple[PlannerFixture, ...],
    catalog: EvidenceCatalog,
    *,
    expected_families: tuple[str, ...],
    development_families: tuple[str, ...],
    previous_queries: frozenset[str] = frozenset(),
) -> dict:
    if not cases or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("empty_or_duplicate_case_inventory")
    expected = {
        f"{family}-{language}" for family in expected_families for language in ("en", "ar", "ar-JO")
    }
    if {c.case_id for c in cases} != expected:
        raise ValueError("case_language_family_coverage_mismatch")
    if not set(development_families) <= set(expected_families):
        raise ValueError("unknown_development_family")
    for case in cases:
        validate_case(case, catalog)
        expected_split = (
            "development" if case.family_id in development_families else "reserved_evaluation"
        )
        if case.split != expected_split:
            raise ValueError("family_split_mismatch")
        if case.request.query in previous_queries:
            raise ValueError("query_exactly_reuses_previous_cohort")
    witnesses = {i for c in cases for r in c.part_reviews for i in r.witness_chunk_ids}
    return {
        "cases": len(cases),
        "families": len(expected_families),
        "parts": sum(len(c.part_reviews) for c in cases),
        "languages": dict(Counter(c.language for c in cases)),
        "splits": dict(Counter(c.split for c in cases)),
        "expected_part_resolutions": dict(
            Counter(r.expected_resolution for c in cases for r in c.part_reviews)
        ),
        "distinct_selected_witnesses": len(witnesses),
        "selected_witness_urls": len({catalog.chunks[i].canonical_url for i in witnesses}),
        "semantic_judgments_made_by_script": 0,
        "model_execution": "not_executed",
        "limits": "New authored cases, not an unseen statistical holdout. Selected witnesses are "
        "not exhaustive relevance labels. Literal checks do not judge semantic correctness.",
    }


def validate_reviews(cases: tuple[PlannerFixture, ...], reviews: list[dict]) -> None:
    """Bind final individually written judgments; preserve earlier findings separately."""
    if len(reviews) != len(cases) or len({r["case_id"] for r in reviews}) != len(reviews):
        raise ValueError("independent_review_coverage_mismatch")
    by_id = {r["case_id"]: r for r in reviews}
    if set(by_id) != {c.case_id for c in cases}:
        raise ValueError("independent_review_case_inventory_mismatch")
    for case in cases:
        review = by_id[case.case_id]
        if (
            review["case_sha256"] != fixture_hash(case)
            or review["plan_sha256"] != value_hash(case.expected_plan.model_dump(mode="json"))
            or review["reviewer_agent"] == case.author_agent
            or not review["reviewer_agent"].strip()
            or review["reviewer_model"] != "gpt-6.1-sol"
            or review["verdict"] != "pass"
            or not review["rationale"].strip()
        ):
            raise ValueError("independent_review_binding_or_verdict_invalid")
        parts = review["part_reviews"]
        if [p["part_index"] for p in parts] != list(range(len(case.part_reviews))):
            raise ValueError("independent_part_review_coverage_mismatch")
        if any(not p["rationale"].strip() for p in parts):
            raise ValueError("independent_part_review_rationale_missing")
        if any(p.get("verdict", "pass") != "pass" for p in parts):
            raise ValueError("independent_part_review_not_passed")
        for actual, proposed, authored in zip(
            parts, case.expected_plan.parts, case.part_reviews, strict=True
        ):
            expected = {
                "original_request_span": case.request.query[proposed.start : proposed.end],
                "state": proposed.state,
                "operation": proposed.operation,
                "intended_use": proposed.intended_use,
                "expected_resolution": authored.expected_resolution,
                "witness_chunk_ids": list(authored.witness_chunk_ids),
            }
            if any(key in actual and actual[key] != value for key, value in expected.items()):
                raise ValueError("independent_part_review_literal_metadata_mismatch")
        witnessed = {i for r in case.part_reviews for i in r.witness_chunk_ids}
        if not witnessed <= {entry["chunk_id"] for entry in review["source_evidence"]}:
            raise ValueError("independent_review_source_coverage_mismatch")


def validate_source_evidence(
    reviews: list[dict], catalog: EvidenceCatalog, *, bundle: Path, packet_root: Path
) -> dict:
    """Verify quoted payloads/ownership and actual saved DOM; not semantic judgment."""
    from telescope_rag.ingestion.models import PreparedDocument

    sources = {}
    for path in sorted(bundle.glob("*.json")):
        if len(path.stem) == 64:
            document = PreparedDocument.model_validate_json(path.read_bytes())
            sources[document.document.page.document_id] = (path, document.document.page)
    packets, checked = {}, {}
    for review in reviews:
        for evidence in review["source_evidence"]:
            identity = evidence["chunk_id"]
            if identity not in catalog.chunks:
                raise ValueError("review_source_unknown_chunk")
            chunk = catalog.chunks[identity]
            path, page = sources[chunk.document_id]
            expected = {
                "source_url": chunk.canonical_url,
                "original_prepared_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "original_html_sha256": hashlib.sha256(page.html.encode()).hexdigest(),
            }
            if any(evidence.get(key) != value for key, value in expected.items()):
                raise ValueError("review_source_identity_or_hash_mismatch")
            packet_path = (packet_root / evidence["source_packet"]).resolve()
            if not packet_path.is_relative_to(packet_root.resolve()):
                raise ValueError("review_packet_path_escape")
            if (
                hashlib.sha256(packet_path.read_bytes()).hexdigest()
                != evidence["source_packet_sha256"]
            ):
                raise ValueError("review_packet_hash_mismatch")
            if packet_path not in packets:
                entries = json.loads(packet_path.read_bytes())["entries"]
                if len({e["chunk_id"] for e in entries}) != len(entries):
                    raise ValueError("review_packet_duplicate_chunk")
                packets[packet_path] = {e["chunk_id"]: e for e in entries}
            entry = packets[packet_path][identity]
            if (
                entry["source_url"] != chunk.canonical_url
                or entry["full_retrieval_text"] != chunk.retrieval_text
                or entry["source_issue_codes"] != list(chunk.source_issue_codes)
                or entry["original_prepared_sha256"] != expected["original_prepared_file_sha256"]
                or entry["embedded_original_html_sha256"] != expected["original_html_sha256"]
            ):
                raise ValueError("review_packet_source_payload_mismatch")
            for field, actual in (
                ("literal_owner_id", chunk.doctor_id),
                ("literal_owner", chunk.doctor_id),
                ("literal_owner_name", chunk.doctor_name),
                ("canonical_owner_id", chunk.canonical_doctor_id),
                ("canonical_owner_name", chunk.canonical_doctor_name),
            ):
                if field in entry and entry[field] != actual:
                    raise ValueError("review_packet_owner_mismatch")
            # Reject invented supplemental fields too, rather than merely ignoring
            # an unsupported quote or doctor claim beside a correct chunk ID.
            for field, actual in (
                ("quote", chunk.retrieval_text),
                ("literal_owner_id", chunk.doctor_id),
                ("canonical_owner_id", chunk.canonical_doctor_id),
            ):
                if field in evidence and evidence[field] != actual:
                    raise ValueError("review_evidence_supplemental_payload_mismatch")
            elements = entry["original_source_elements"]
            spans = (*chunk.context_spans, *chunk.source_spans)
            locators = [n["locator"] for n in elements]
            if evidence["original_DOM_locators"] != locators or set(locators) != {
                s.locator for s in spans
            }:
                raise ValueError("review_dom_inventory_mismatch")
            if (packet_path, identity) in checked:
                continue
            soup = BeautifulSoup(page.html, "html.parser")
            for span in spans:
                matches = [
                    n
                    for n in elements
                    if n["locator"] == span.locator and n.get("attribute") == span.attribute
                ]
                selector = (
                    span.locator.removesuffix("::attr(alt)")
                    if span.attribute == "alt"
                    else span.locator
                )
                nodes = soup.select(selector)
                if len(nodes) != 1 or not matches:
                    raise ValueError("review_dom_locator_mismatch")
                raw = (
                    nodes[0].get(span.attribute, "")
                    if span.attribute
                    else nodes[0].get_text(" ", strip=False)
                )
                if raw != span.original_text:
                    raise ValueError("review_dom_original_text_mismatch")
                for match in matches:
                    for field in (
                        "html_node_text",
                        "original_dom_text_or_attribute",
                        "independent_original_dom_text_or_attribute",
                    ):
                        if field in match and " ".join(match[field].split()) != " ".join(
                            raw.split()
                        ):
                            raise ValueError("review_dom_display_text_mismatch")
                if not any(
                    (
                        n.get("span", {}).get("original_text", n.get("original_span_text"))
                        == span.original_text
                    )
                    and n.get("span", n)["start"] == span.start
                    and n.get("span", n)["end"] == span.end
                    for n in matches
                ):
                    raise ValueError("review_dom_span_mismatch")
            checked[packet_path, identity] = len(spans)
    return {
        "review_source_packet_entries_verified": len(checked),
        "review_dom_span_references_verified": sum(checked.values()),
        "distinct_source_chunks_verified": len({identity for _, identity in checked}),
        "semantic_judgments_made_by_script": 0,
    }


def request_export(case: PlannerFixture) -> dict:
    return {
        "case_id": case.case_id,
        "language": case.language,
        "query": case.request.query,
        "history": [h.model_dump(mode="json") for h in case.request.history],
        "requested_language": case.request.language,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    )


def freeze(
    cases: tuple[PlannerFixture, ...],
    reviews: list[dict],
    catalog: EvidenceCatalog,
    *,
    output: Path,
    source_bundle: str,
    bindings: dict[str, str],
    evidence_files: tuple[Path, ...],
    previous_queries: frozenset[str],
    bundle: Path,
    packet_root: Path,
) -> dict:
    summary = validate_cohort(
        cases,
        catalog,
        expected_families=tuple(f"PL{i:02}" for i in range(1, 9)),
        development_families=("PL01", "PL05"),
        previous_queries=previous_queries,
    )
    validate_reviews(cases, reviews)
    validate_source_evidence(reviews, catalog, bundle=bundle, packet_root=packet_root)
    output.mkdir(parents=True, exist_ok=False)
    ordered = sorted(cases, key=lambda c: c.case_id)
    (output / "cases.jsonl").write_text(
        "".join(c.model_dump_json() + "\n" for c in ordered), encoding="utf-8"
    )
    (output / "requests.jsonl").write_text(
        "".join(json.dumps(request_export(c), ensure_ascii=False) + "\n" for c in ordered),
        encoding="utf-8",
    )
    write_json(output / "independent-reviews.json", reviews)
    ids = {i for c in cases for r in c.part_reviews for i in r.witness_chunk_ids}
    write_json(
        output / "source-witnesses.json",
        [catalog.chunks[i].model_dump(mode="json") for i in sorted(ids)],
    )
    evidence = output / "review"
    evidence.mkdir()
    if len({p.name for p in evidence_files}) != len(evidence_files):
        raise ValueError("duplicate_evidence_filename")
    for path in evidence_files:
        (evidence / path.name).write_bytes(path.read_bytes())
    write_json(output / "coverage.json", summary)
    write_json(
        output / "execution-status.json",
        {
            "luna_planning": "not_executed",
            "answer_generation": "not_executed",
            "retrieval": "not_executed",
            "provider_calls": 0,
            "qdrant_calls": 0,
            "planner_accuracy": None,
            "semantic_answer_scores": None,
        },
    )
    manifest = {
        "version": "m5-planner-cases-v1",
        "source_bundle": source_bundle,
        "prepared_digest": catalog.prepared_digest,
        "bindings": bindings,
        "cohort_sha256": value_hash([c.model_dump(mode="json") for c in ordered]),
        "files": {
            p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.rglob("*"))
            if p.is_file()
        },
    }
    write_json(output / "manifest.json", manifest)
    return {
        **summary,
        "manifest_sha256": hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest(),
    }


def verify_frozen(root: Path, directory: Path, manifest_sha256: str) -> dict:
    manifest_path = directory / "manifest.json"
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != manifest_sha256:
        raise ValueError("planner_manifest_hash_mismatch")
    manifest = json.loads(manifest_path.read_bytes())
    inventory = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if inventory != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("planner_frozen_inventory_mismatch")
    for name, digest in manifest["files"].items():
        path = (directory / name).resolve()
        if (
            not path.is_relative_to(directory.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("planner_frozen_file_mismatch")
    for name, digest in manifest["bindings"].items():
        path = (root / name).resolve()
        if (
            not path.is_relative_to(root.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("planner_source_or_code_binding_mismatch")
    bundle = (root / manifest["source_bundle"]).resolve()
    if not bundle.is_relative_to(root.resolve()):
        raise ValueError("planner_source_bundle_escape")
    documents, _ = load_corpus(bundle)
    catalog = EvidenceCatalog(documents, expected_digest=manifest["prepared_digest"])
    cases = load_fixtures((directory / "cases.jsonl",))
    summary = validate_cohort(
        cases,
        catalog,
        expected_families=tuple(f"PL{i:02}" for i in range(1, 9)),
        development_families=("PL01", "PL05"),
    )
    if (
        value_hash([c.model_dump(mode="json") for c in sorted(cases, key=lambda c: c.case_id)])
        != manifest["cohort_sha256"]
    ):
        raise ValueError("planner_cohort_hash_mismatch")
    validate_reviews(cases, json.loads((directory / "independent-reviews.json").read_bytes()))
    source_validation = validate_source_evidence(
        json.loads((directory / "independent-reviews.json").read_bytes()),
        catalog,
        bundle=bundle,
        packet_root=directory,
    )
    actual_requests = [
        json.loads(line)
        for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if actual_requests != [request_export(c) for c in cases]:
        raise ValueError("planner_request_export_changed_or_gold_leaked")
    ids = {i for c in cases for r in c.part_reviews for i in r.witness_chunk_ids}
    if json.loads((directory / "source-witnesses.json").read_bytes()) != [
        catalog.chunks[i].model_dump(mode="json") for i in sorted(ids)
    ]:
        raise ValueError("planner_source_witnesses_changed")
    if json.loads((directory / "coverage.json").read_bytes()) != summary:
        raise ValueError("planner_frozen_coverage_changed")
    status = json.loads((directory / "execution-status.json").read_bytes())
    if status != {
        "luna_planning": "not_executed",
        "answer_generation": "not_executed",
        "retrieval": "not_executed",
        "provider_calls": 0,
        "qdrant_calls": 0,
        "planner_accuracy": None,
        "semantic_answer_scores": None,
    }:
        raise ValueError("planner_preparation_cannot_claim_execution")
    return {
        **summary,
        **source_validation,
        "manifest_sha256": manifest_sha256,
        "frozen_integrity_verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(verify_frozen(root, args.frozen.resolve(), args.manifest_sha256), indent=2))


if __name__ == "__main__":
    main()
