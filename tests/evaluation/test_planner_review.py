"""Synthetic integrity tests. No script decides relevance or clinical meaning."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2]))
    from scripts import planner_review

    return planner_review


@pytest.fixture
def catalog():
    def chunk(identity, document="synthetic-document", codes=()):
        return SimpleNamespace(
            chunk_id=identity,
            document_id=document,
            canonical_url=f"https://telescopecenter.com/{document}/",
            page_title="Synthetic test only",
            doctor_id=None,
            canonical_doctor_id=None,
            source_issue_codes=codes,
        )

    chunks = {
        "a": chunk("a"),
        "b": chunk("b", "different-document"),
        "context": chunk("context", codes=("name_only_profile_no_specialty_or_biography_claim",)),
    }
    return SimpleNamespace(
        chunks=chunks,
        prepared_digest="synthetic-digest",
        scope_members=lambda scope: tuple(
            key
            for key, c in chunks.items()
            if not scope.document_ids or c.document_id in scope.document_ids
        ),
    )


def data(language="en", family="PL01"):
    query = f"Synthetic question {family} {language}?"
    return {
        "case_id": f"{family}-{language}",
        "family_id": family,
        "language": language,
        "split": "development",
        "request": {"query": query, "history": [], "language": "auto"},
        "expected_plan": {
            "language": language,
            "parts": [
                {
                    "start": 0,
                    "end": len(query),
                    "state": "public",
                    "operation": "search",
                    "intended_use": "general_excerpt",
                    "retrieval_query": query,
                    "document_handles": [],
                    "owner_handle": None,
                    "block_types": [],
                    "source_language": None,
                    "reference_text": None,
                    "history_indices": [],
                    "reason": None,
                }
            ],
        },
        "part_reviews": [
            {
                "part_index": 0,
                "witness_chunk_ids": ["a"],
                "expected_resolution": "candidate",
                "semantic_rationale": "Synthetic review.",
                "protected_text": ["Synthetic question"],
            }
        ],
        "author_agent": "/synthetic/author",
        "author_model": "gpt-6.1-sol",
    }


def fixture(module, value=None):
    return module.PlannerFixture.model_validate_json(json.dumps(value or data()), strict=True)


def review(module, case):
    return {
        "case_id": case.case_id,
        "case_sha256": module.fixture_hash(case),
        "plan_sha256": module.value_hash(case.expected_plan.model_dump(mode="json")),
        "reviewer_agent": "/synthetic/independent",
        "reviewer_model": "gpt-6.1-sol",
        "verdict": "pass",
        "rationale": "Synthetic authored judgment; not a real review.",
        "part_reviews": [{"part_index": 0, "rationale": "Synthetic part review."}],
        "source_evidence": [{"chunk_id": "a"}],
    }


def test_valid_case_literal_anchor_and_gold_free_export(module, catalog):
    c = fixture(module)
    module.validate_case(c, catalog)
    exported = module.request_export(c)
    assert set(exported) == {"case_id", "language", "query", "history", "requested_language"}
    # Output language and requested language are separate values; the export
    # must preserve both rather than silently overwrite the cohort language.
    assert exported["query"] == c.request.query
    assert exported["language"] == "en" and exported["requested_language"] == "auto"
    assert module.fixture_hash(c) == module.value_hash(c.model_dump(mode="json"))


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_witness",
        "duplicate_witness",
        "nonliteral",
        "unknown_handle",
        "out_of_scope",
        "lost_query_span",
        "context_as_answer",
        "time_as_candidate",
    ],
)
def test_invalid_case_cannot_pass_literal_scope_policy_gate(module, catalog, mutation):
    value = data()
    p, r = value["expected_plan"]["parts"][0], value["part_reviews"][0]
    if mutation == "unknown_witness":
        r["witness_chunk_ids"] = ["missing"]
    elif mutation == "duplicate_witness":
        r["witness_chunk_ids"] = ["a", "a"]
    elif mutation == "nonliteral":
        r["protected_text"] = ["Invented reference"]
    elif mutation == "unknown_handle":
        p["document_handles"] = ["not-issued"]
    elif mutation == "out_of_scope":
        p["document_handles"] = ["d0001"]  # sorted different-document before synthetic-document
    elif mutation == "lost_query_span":
        p["end"] -= 1
    elif mutation == "context_as_answer":
        p["intended_use"], r["witness_chunk_ids"] = "profile_detail", ["context"]
    elif mutation == "time_as_candidate":
        p["operation"], p["retrieval_query"] = "time_comparison", None
    with pytest.raises(ValueError):
        module.validate_case(fixture(module, value), catalog)


def test_context_only_unknown_and_selected_read_witnesses_remain_valid(module, catalog):
    value = data()
    p, r = value["expected_plan"]["parts"][0], value["part_reviews"][0]
    p["intended_use"] = "profile_detail"
    r.update(witness_chunk_ids=["context"], expected_resolution="unknown")
    module.validate_case(fixture(module, value), catalog)
    p.update(operation="read_source", retrieval_query=None, document_handles=["d0002"])
    r.update(witness_chunk_ids=["a"], expected_resolution="candidate")
    p["intended_use"] = "general_excerpt"
    module.validate_case(fixture(module, value), catalog)


@pytest.mark.parametrize("state", ["excluded", "clarification_required"])
def test_nonpublic_parts_never_retrieve_and_require_matching_resolution(module, catalog, state):
    value = data()
    value["expected_plan"]["parts"][0].update(
        state=state, retrieval_query=None, reason="Synthetic."
    )
    value["part_reviews"][0].update(witness_chunk_ids=[], expected_resolution=state)
    module.validate_case(fixture(module, value), catalog)
    value["part_reviews"][0]["witness_chunk_ids"] = ["a"]
    with pytest.raises(ValueError, match="nonpublic"):
        module.validate_case(fixture(module, value), catalog)


@pytest.mark.parametrize(
    "mutation",
    [
        "identity",
        "language",
        "missing_part_review",
        "extra",
        "missing_nullable_field",
        "wrong_model",
    ],
)
def test_closed_case_schemas_reject_malformed_inventory(module, mutation):
    value = data()
    if mutation == "identity":
        value["case_id"] = "Wrong"
    elif mutation == "language":
        value["expected_plan"]["language"] = "ar"
    elif mutation == "missing_part_review":
        value["part_reviews"] = []
    elif mutation == "extra":
        value["inferred_answer"] = "Unsupported"
    elif mutation == "missing_nullable_field":
        del value["expected_plan"]["parts"][0]["owner_handle"]
    elif mutation == "wrong_model":
        value["author_model"] = "other-model"
    with pytest.raises(ValidationError):
        fixture(module, value)


def test_cohort_family_language_split_and_exact_prior_query_checks(module, catalog):
    cases = tuple(fixture(module, data(language)) for language in ("en", "ar", "ar-JO"))
    kwargs = dict(expected_families=("PL01",), development_families=("PL01",))
    result = module.validate_cohort(cases, catalog, **kwargs)
    assert result["cases"] == 3 and result["semantic_judgments_made_by_script"] == 0
    assert result["model_execution"] == "not_executed"
    for broken in (cases[:-1], cases + cases[:1]):
        with pytest.raises(ValueError):
            module.validate_cohort(broken, catalog, **kwargs)
    with pytest.raises(ValueError, match="reuses_previous"):
        module.validate_cohort(
            cases, catalog, previous_queries=frozenset({cases[0].request.query}), **kwargs
        )
    with pytest.raises(ValueError, match="split"):
        module.validate_cohort(cases, catalog, expected_families=("PL01",), development_families=())


@pytest.mark.parametrize(
    "mutation",
    [
        "case_hash",
        "plan_hash",
        "same_author",
        "other_model",
        "unresolved",
        "no_rationale",
        "no_parts",
        "no_source",
        "no_case",
        "duplicate_case",
    ],
)
def test_independent_reviews_require_exact_actual_case_part_source_bindings(module, mutation):
    c = fixture(module)
    r = review(module, c)
    reviews = [r]
    if mutation == "case_hash":
        r["case_sha256"] = "tampered"
    elif mutation == "plan_hash":
        r["plan_sha256"] = "tampered"
    elif mutation == "same_author":
        r["reviewer_agent"] = c.author_agent
    elif mutation == "other_model":
        r["reviewer_model"] = "other"
    elif mutation == "unresolved":
        r["verdict"] = "unresolved"
    elif mutation == "no_rationale":
        r["rationale"] = " "
    elif mutation == "no_parts":
        r["part_reviews"] = []
    elif mutation == "no_source":
        r["source_evidence"] = []
    elif mutation == "no_case":
        reviews = []
    elif mutation == "duplicate_case":
        reviews.append(copy.deepcopy(r))
    with pytest.raises(ValueError):
        module.validate_reviews((c,), reviews)


def test_reviewed_record_change_requires_new_independent_judgment(module):
    c = fixture(module)
    r = review(module, c)
    module.validate_reviews((c,), [r])
    modified = c.model_dump(mode="json")
    modified["part_reviews"][0]["semantic_rationale"] += " Changed meaning claim."
    with pytest.raises(ValueError, match="binding"):
        module.validate_reviews((fixture(module, modified),), [r])


def test_loader_uses_exact_json_records_and_skips_only_blank_lines(module, tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(data()) + "\n\n", encoding="utf-8")
    assert len(module.load_fixtures((path,))) == 1
    path.write_text('{"case_id":"incomplete"}\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        module.load_fixtures((path,))


@pytest.fixture
def frozen(module, tmp_path, monkeypatch):
    """A real source-bound catalog, using explicitly synthetic source records."""
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "unit"))
    from test_evidence_assembly import chunk

    from telescope_rag.ingestion.models import ExtractedDocument, PreparedDocument, RawPage
    from telescope_rag.ingestion.review import prepared_digest, prepared_document_json
    from telescope_rag.retrieval.assembly import EvidenceCatalog

    c = chunk(1)
    doc = PreparedDocument(
        document=ExtractedDocument(
            page=RawPage(
                snapshot_id=c.snapshot_id,
                document_id=c.document_id,
                canonical_url=c.canonical_url,
                fetched_at=c.fetched_at,
                content_hash="synthetic-only",
                html=f"<main><p>{c.retrieval_text}</p></main>",
            ),
            title="Synthetic only",
            units=(),
        ),
        chunks=(c,),
        embedding_ready=True,
    )
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / ("a" * 64 + ".json")).write_text(prepared_document_json(doc), encoding="utf-8")
    cat = EvidenceCatalog((doc,), expected_digest=prepared_digest((doc,)))
    rows = []
    for family in range(1, 9):
        for language in ("en", "ar", "ar-JO"):
            value = data(language, f"PL{family:02}")
            value["split"] = "development" if family in {1, 5} else "reserved_evaluation"
            value["part_reviews"][0]["witness_chunk_ids"] = [c.chunk_id]
            rows.append(fixture(module, value))
    reviews = [review(module, case) for case in rows]
    for r in reviews:
        r["source_evidence"] = [{"chunk_id": c.chunk_id}]
    source_binding = tmp_path / "code-binding.txt"
    source_binding.write_text("Synthetic frozen code binding", encoding="utf-8")
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"synthetic":true}', encoding="utf-8")
    source_file = bundle / ("a" * 64 + ".json")
    packet_dir = tmp_path / "review"
    packet_dir.mkdir()
    packet = packet_dir / "source-packet.json"
    entry = {
        "chunk_id": c.chunk_id,
        "source_url": c.canonical_url,
        "full_retrieval_text": c.retrieval_text,
        "source_issue_codes": [],
        "original_prepared_sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
        "embedded_original_html_sha256": hashlib.sha256(
            doc.document.page.html.encode()
        ).hexdigest(),
        "literal_owner_id": None,
        "original_source_elements": [
            {
                "locator": "main > p",
                "attribute": None,
                "span": c.source_spans[0].model_dump(mode="json"),
            }
        ],
    }
    packet.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    for r in reviews:
        r["source_evidence"] = [
            {
                "chunk_id": c.chunk_id,
                "source_url": c.canonical_url,
                "source_packet": "review/source-packet.json",
                "source_packet_sha256": hashlib.sha256(packet.read_bytes()).hexdigest(),
                "original_prepared_file_sha256": entry["original_prepared_sha256"],
                "original_html_sha256": entry["embedded_original_html_sha256"],
                "original_DOM_locators": ["main > p"],
            }
        ]
    output = tmp_path / "frozen"
    kwargs = dict(
        output=output,
        source_bundle="bundle",
        bindings={"code-binding.txt": hashlib.sha256(source_binding.read_bytes()).hexdigest()},
        evidence_files=(evidence, packet),
        previous_queries=frozenset(),
        bundle=bundle,
        packet_root=tmp_path,
    )
    result = module.freeze(tuple(rows), reviews, cat, **kwargs)
    return output, result["manifest_sha256"], tuple(rows), reviews, cat, kwargs


def test_frozen_cohort_exact_source_review_and_request_roundtrip(module, tmp_path, frozen):
    directory, digest, cases, reviews, cat, kwargs = frozen
    result = module.verify_frozen(tmp_path, directory, digest)
    assert result["cases"] == 24 and result["parts"] == 24
    assert result["frozen_integrity_verified"] and result["model_execution"] == "not_executed"
    before = (directory / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        module.freeze(cases, reviews, cat, **kwargs)
    assert (directory / "manifest.json").read_bytes() == before


@pytest.mark.parametrize(
    "name",
    [
        "cases.jsonl",
        "requests.jsonl",
        "source-witnesses.json",
        "independent-reviews.json",
        "execution-status.json",
        "coverage.json",
        "review/evidence.json",
        "manifest.json",
    ],
)
def test_any_frozen_payload_tamper_is_rejected(module, tmp_path, frozen, name):
    directory, digest, *_ = frozen
    path = directory / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        module.verify_frozen(tmp_path, directory, digest)


def test_extra_frozen_file_or_changed_bound_code_is_rejected(module, tmp_path, frozen):
    directory, digest, *_ = frozen
    (directory / "unexpected.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="inventory"):
        module.verify_frozen(tmp_path, directory, digest)
    (directory / "unexpected.txt").unlink()
    (tmp_path / "code-binding.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="binding"):
        module.verify_frozen(tmp_path, directory, digest)


@pytest.mark.parametrize(
    "mutation",
    [
        "url",
        "quote",
        "owner",
        "prepared_hash",
        "html_hash",
        "packet_path_escape",
        "packet_hash",
        "locator",
    ],
)
def test_review_evidence_foreign_fields_cannot_hide_behind_a_correct_chunk_id(
    module, frozen, mutation
):
    _, _, _, reviews, cat, kwargs = frozen
    rows = copy.deepcopy(reviews)
    e = rows[0]["source_evidence"][0]
    if mutation == "url":
        e["source_url"] = "https://foreign.invalid/"
    elif mutation == "quote":
        e["quote"] = "Invented fact beside a real chunk ID"
    elif mutation == "owner":
        e["literal_owner_id"] = "different-doctor"
    elif mutation == "prepared_hash":
        e["original_prepared_file_sha256"] = "wrong"
    elif mutation == "html_hash":
        e["original_html_sha256"] = "wrong"
    elif mutation == "packet_path_escape":
        e["source_packet"] = "../outside.json"
    elif mutation == "packet_hash":
        e["source_packet_sha256"] = "wrong"
    elif mutation == "locator":
        e["original_DOM_locators"] = ["other > p"]
    with pytest.raises(ValueError):
        module.validate_source_evidence(
            rows, cat, bundle=kwargs["bundle"], packet_root=kwargs["packet_root"]
        )


@pytest.mark.parametrize("mutation", ["owner", "quote", "display_text", "span"])
def test_self_consistent_review_packet_rehash_cannot_change_original_source(
    module, frozen, mutation
):
    _, _, _, reviews, cat, kwargs = frozen
    path = kwargs["packet_root"] / "review/source-packet.json"
    packet = json.loads(path.read_bytes())
    e = packet["entries"][0]
    if mutation == "owner":
        e["literal_owner_id"] = "wrong-doctor"
    elif mutation == "quote":
        e["full_retrieval_text"] = "Invented medical claim"
    elif mutation == "display_text":
        e["original_source_elements"][0]["original_dom_text_or_attribute"] = "Invented display"
    elif mutation == "span":
        e["original_source_elements"][0]["span"]["original_text"] = "Invented span"
    path.write_text(json.dumps(packet), encoding="utf-8")
    rows = copy.deepcopy(reviews)
    for r in rows:
        r["source_evidence"][0]["source_packet_sha256"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    with pytest.raises(ValueError):
        module.validate_source_evidence(
            rows, cat, bundle=kwargs["bundle"], packet_root=kwargs["packet_root"]
        )
