"""Synthetic contract/safety checks; no clinic corpus, real tokenizer or network."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from telescope_rag.ingestion.models import (
    ExtractedDocument,
    PreparedChunk,
    PreparedDocument,
    RawPage,
    SourceSpan,
)
from telescope_rag.ingestion.review import prepared_digest
from telescope_rag.retrieval.assembly import (
    AssemblyRequest,
    EvidenceCatalog,
    RequestPart,
    SourceScope,
    evidence_group_key,
)


class SyntheticCounter:
    verified = True
    version = "synthetic-character-units-not-production-tokens"

    def count(self, text):
        return len(text)


def chunk(
    i,
    text="Synthetic complete source claim.",
    *,
    document=None,
    owner=None,
    flags=(),
    language="en",
):
    document = document or f"doc-{i}"
    span = SourceSpan(block_id=f"span-{i}", locator="main > p", original_text=text, end=len(text))
    return PreparedChunk(
        chunk_id=f"chunk-{i}",
        point_id=str(UUID(int=i)),
        document_id=document,
        canonical_url=f"https://telescopecenter.com/synthetic-{document}/",
        page_title="Synthetic source",
        snapshot_id="synthetic-snapshot",
        fetched_at=datetime(2026, 10, 16, tzinfo=UTC),
        parent_block_id=f"parent-{i}",
        block_type="doctor" if owner else "section",
        language=language,
        section_path=(),
        doctor_id=owner,
        doctor_name=owner,
        source_issue_codes=flags,
        admission_policy_hash="synthetic-policy",
        source_spans=(span,),
        original_text=text,
        retrieval_text=text,
        content_hash=f"content-{i}",
        token_count=8,
        tokenizer_version="synthetic",
        embedding_format_version="synthetic",
        embedding_format_hash="synthetic",
        embedding_ready=True,
    )


def catalog(*chunks):
    by_doc = {}
    for c in chunks:
        by_doc.setdefault(c.document_id, []).append(c)
    docs = tuple(
        PreparedDocument(
            document=ExtractedDocument(
                page=RawPage(
                    snapshot_id=values[0].snapshot_id,
                    document_id=doc,
                    canonical_url=values[0].canonical_url,
                    fetched_at=values[0].fetched_at,
                    content_hash="synthetic",
                    html="<main>Synthetic fixture only</main>",
                ),
                title="Synthetic",
                units=(),
            ),
            chunks=tuple(values),
            embedding_ready=True,
        )
        for doc, values in by_doc.items()
    )
    return EvidenceCatalog(docs, expected_digest=prepared_digest(docs))


def request(text="Question", **part_fields):
    return AssemblyRequest(
        original_query=text,
        parts=(
            RequestPart(
                part_id="p1",
                start=0,
                end=len(text),
                **part_fields,
            ),
        ),
    )


def assemble(c, req, ids, **options):
    return c.assemble(
        req,
        ids,
        counter=SyntheticCounter(),
        token_basis="synthetic_test",
        max_tokens=options.pop("max_tokens", 100000),
        **options,
    )


def test_exact_repeats_share_text_but_retain_all_occurrences_and_source_spans():
    first, second = chunk(1), chunk(2)
    result = assemble(catalog(first, second), request(), {"p1": [first.chunk_id, second.chunk_id]})
    assert len(result.groups) == 1
    assert result.groups[0].occurrences == (first, second)
    assert result.parts[0].occurrence_ids == (first.chunk_id, second.chunk_id)
    assert result.rendered_text.count(first.retrieval_text) == 1
    assert result.groups[0].occurrences[1].source_spans == second.source_spans
    assert not result.semantic_support_assessed and not result.luna_input_admitted
    assert result.token_basis == "synthetic_test"


def test_control_arm_can_retain_occurrence_slots_with_identical_budget_and_counter():
    a, b = chunk(1), chunk(2)
    result = assemble(
        catalog(a, b), request(), {"p1": [a.chunk_id, b.chunk_id]}, coalesce_exact=False
    )
    assert len(result.groups) == 2
    assert result.rendered_text.count(a.retrieval_text) == 2
    assert result.token_count == len(result.rendered_text)


@pytest.mark.parametrize(
    "text",
    [
        "Not all cases qualify; only after the published assessment.",
        "لا تنطبق على كل الحالات؛ فقط حسب التقييم المنشور.",
        "مش لكل الحالات؛ حسب التقييم، والمواعيد المنشورة مش توفر حجوزات.",
    ],
)
def test_negation_qualifiers_and_every_literal_character_survive_rendering(text):
    c = chunk(1, text)
    result = assemble(catalog(c), request(), {"p1": [c.chunk_id]})
    assert c.retrieval_text in result.rendered_text
    assert result.groups[0].occurrences[0].original_text == text


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Fast", "Very fast"),
        ("2 weeks", "4-6 weeks"),
        ("Acne treatment", "Acne-scar treatment"),
        ("سريع", "أبطأ"),
    ],
)
def test_similar_but_different_facts_numbers_or_service_claims_never_coalesce(a, b):
    first, second = chunk(1, a), chunk(2, b)
    result = assemble(catalog(first, second), request(), {"p1": [first.chunk_id, second.chunk_id]})
    assert len(result.groups) == 2
    assert result.groups[0].occurrences == (first,)
    assert result.groups[1].occurrences == (second,)


@pytest.mark.parametrize(
    "difference",
    [
        {"doctor_id": "other", "doctor_name": "Other doctor", "block_type": "doctor"},
        {"language": "ar"},
        {"source_issue_codes": ("unreviewed_scope",)},
        {"canonical_doctor_name": "Different authorized metadata"},
        {"section_path": ("Other context",)},
    ],
)
def test_similar_specialties_languages_qualifiers_or_policy_do_not_merge(difference):
    first = chunk(1, "Ophthalmology Specialist")
    second = chunk(2, "Ophthalmology Specialist").model_copy(update=difference)
    result = assemble(catalog(first, second), request(), {"p1": [first.chunk_id, second.chunk_id]})
    assert len(result.groups) == 2


def test_shared_group_never_transfers_out_of_scope_citations_between_parts():
    a, b = chunk(1), chunk(2)
    req = AssemblyRequest(
        original_query="PageA PageB",
        parts=(
            RequestPart(
                part_id="a", start=0, end=5, scope=SourceScope(document_ids=(a.document_id,))
            ),
            RequestPart(
                part_id="b", start=6, end=11, scope=SourceScope(document_ids=(b.document_id,))
            ),
        ),
    )
    result = assemble(
        catalog(a, b), req, {"a": [b.chunk_id, a.chunk_id], "b": [a.chunk_id, b.chunk_id]}
    )
    assert len(result.groups) == 1
    assert result.groups[0].part_occurrences == (("a", (a.chunk_id,)), ("b", (b.chunk_id,)))
    assert result.parts[0].occurrence_ids == (a.chunk_id,)
    assert result.parts[0].filtered_occurrence_ids == (b.chunk_id,)
    assert result.parts[1].occurrence_ids == (b.chunk_id,)


def test_round_robin_does_not_let_one_part_consume_every_group_slot():
    a, b, c = chunk(1, "One"), chunk(2, "Two"), chunk(3, "Three")
    req = AssemblyRequest(
        original_query="A B",
        parts=(RequestPart(part_id="a", start=0, end=1), RequestPart(part_id="b", start=2, end=3)),
    )
    result = assemble(
        catalog(a, b, c), req, {"a": [a.chunk_id, b.chunk_id], "b": [c.chunk_id]}, max_groups=2
    )
    assert [g.occurrences[0] for g in result.groups] == [a, c]
    assert result.parts[0].omission_reasons == ((evidence_group_key(b), "group_limit"),)
    assert result.parts[1].candidate_status == "evidence_supplied"


def test_oversized_complete_evidence_is_omitted_without_truncation_or_starvation():
    large, small = chunk(1, "Unbroken original qualifier " * 200), chunk(2, "Complete small claim.")
    result = assemble(
        catalog(large, small), request(), {"p1": [large.chunk_id, small.chunk_id]}, max_tokens=1200
    )
    assert [g.occurrences[0] for g in result.groups] == [small]
    assert result.parts[0].omission_reasons == (
        (evidence_group_key(large), "indivisible_over_token_budget"),
    )
    assert small.retrieval_text in result.rendered_text
    assert "Unbroken" not in result.rendered_text
    assert result.token_count == len(result.rendered_text) <= 1200


@pytest.mark.parametrize(
    ("flag", "use"),
    [
        ("generic_faq_specific_procedure_scope_unverified", "procedure_specific"),
        ("consultation_offer_applicability_unverified", "consultation_eligibility"),
        ("consultation_advertisement_scope_unresolved", "consultation_eligibility"),
        ("consultation_fee_offer_reconciliation_unverified", "consultation_eligibility"),
        ("name_only_profile_no_specialty_or_biography_claim", "doctor_role"),
        ("name_only_profile_no_specialty_or_biography_claim", "profile_detail"),
        ("department_titles_non_authoritative_use_explicit_roles", "doctor_role"),
        ("damaged_description_excluded_heading_only", "service_description"),
        ("parallel_category_membership_unresolved_no_category_assertion", "technique_category"),
        ("comparison_category_names_without_additional_row_assignment", "technique_category"),
        ("new_unknown_flag", "general_excerpt"),
    ],
)
def test_restricted_uses_keep_source_text_but_only_as_context(flag, use):
    c = chunk(1, flags=(flag,))
    result = assemble(catalog(c), request(intended_use=use), {"p1": [c.chunk_id]})
    assert result.groups[0].context_only_parts == ("p1",)
    assert result.parts[0].candidate_status == "context_only"
    assert c.retrieval_text in result.rendered_text
    assert flag in result.rendered_text
    assert not result.semantic_support_assessed


def test_heading_only_name_is_retained_for_its_explicit_supported_scope():
    c = chunk(1, "Synthetic service heading", flags=("damaged_description_excluded_heading_only",))
    result = assemble(catalog(c), request(intended_use="service_name"), {"p1": [c.chunk_id]})
    assert not result.parts[0].context_only
    assert result.groups[0].occurrences[0] == c
    assert not result.semantic_support_assessed


def test_complete_directory_membership_is_read_from_catalog_not_topk_or_caller_expected_ids():
    cards = [
        chunk(i, f"Shared specialty: owner {i}", document="directory", owner=f"owner-{i}")
        for i in range(1, 12)
    ]
    c = catalog(*cards)
    req = request(
        scope=SourceScope(document_ids=("directory",), block_types=("doctor",), complete=True)
    )
    result = assemble(c, req, {"p1": [cards[0].chunk_id]})
    assert len(result.groups) == 11
    assert result.parts[0].admitted_scope_complete
    assert set(result.parts[0].occurrence_ids) == {x.chunk_id for x in cards}
    partial = assemble(c, req, {"p1": []}, max_groups=5)
    assert partial.parts[0].candidate_status == "scope_incomplete"
    assert partial.parts[0].admitted_scope_complete is False
    assert len(partial.parts[0].missing_scope_occurrence_ids) == 6


def test_excluded_clarification_and_no_hit_parts_remain_explicit():
    req = AssemblyRequest(
        original_query="Public Private Ambiguous",
        parts=(
            RequestPart(part_id="a", start=0, end=6),
            RequestPart(
                part_id="b", start=7, end=14, state="excluded", reason="Outside public scope"
            ),
            RequestPart(
                part_id="c",
                start=15,
                end=24,
                state="clarification_required",
                reason="Identity ambiguous",
            ),
        ),
    )
    result = assemble(catalog(chunk(1)), req, {"a": [], "b": [], "c": []})
    assert [p.candidate_status for p in result.parts] == [
        "no_candidates",
        "excluded",
        "clarification_required",
    ]
    assert all(p.part_id in result.rendered_text for p in req.parts)
    assert not result.groups


def test_actual_owner_filters_do_not_use_canonical_aliases_implicitly():
    c = chunk(1, owner="literal").model_copy(update={"canonical_doctor_id": "approved-canonical"})
    cat = catalog(c)
    assert cat.scope_members(SourceScope(owner_id="approved-canonical")) == ()
    assert cat.scope_members(
        SourceScope(owner_id="approved-canonical", owner_kind="canonical")
    ) == (c.chunk_id,)


@pytest.mark.parametrize(
    "changes",
    [
        {"parts": (RequestPart(part_id="a", start=0, end=1),)},
        {"parts": (RequestPart(part_id="a", start=0, end=10),)},
        {"parts": (RequestPart(part_id="a", start=0, end=3, state="excluded"),)},
    ],
)
def test_unaccounted_original_query_invalid_coordinates_or_missing_scope_reason_fail(changes):
    with pytest.raises(ValidationError):
        AssemblyRequest(original_query="A B", **changes)


def test_forged_source_binding_and_mismatched_bundle_digest_fail():
    c = chunk(1)
    with pytest.raises(ValueError, match="binding"):
        catalog(c.model_copy(update={"canonical_url": "https://other.invalid/"}))
    with pytest.raises(ValueError, match="digest"):
        EvidenceCatalog((), expected_digest="invented")


def test_unknown_documents_unknown_candidates_and_unaccounted_parts_fail_closed():
    c = catalog(chunk(1))
    with pytest.raises(ValueError, match="scope_document"):
        assemble(c, request(scope=SourceScope(document_ids=("unknown",))), {"p1": []})
    with pytest.raises(ValueError, match="inventory"):
        assemble(c, request(), {"p1": ["unknown"]})
    with pytest.raises(ValueError, match="contract"):
        assemble(c, request(), {})
    with pytest.raises(ValidationError):
        SourceScope(complete=True)


def test_synthetic_counter_cannot_masquerade_as_actual_qwen_or_luna_counting():
    c = catalog(chunk(1))
    with pytest.raises(ValueError, match="contract"):
        c.assemble(request(), {"p1": []}, counter=SyntheticCounter())
    with pytest.raises(ValueError, match="metadata_exceeds"):
        assemble(c, request(), {"p1": []}, max_tokens=1)


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, None])
def test_unknown_or_invalid_actual_render_count_never_falls_back(value):
    class BrokenCounter(SyntheticCounter):
        def count(self, text):
            return value

    with pytest.raises(ValueError, match="token_count_unavailable"):
        catalog(chunk(1)).assemble(
            request(), {"p1": []}, counter=BrokenCounter(), token_basis="synthetic_test"
        )
