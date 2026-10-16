"""Exact text/provenance contracts; these checks do not classify natural language."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from telescope_rag.graph.anchoring import (
    AnchoredPlannerPart,
    AnchoredPlannerReply,
    AnchorError,
    resolve_anchored_plan,
    unique_original_span,
)
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import WorkflowRequest
from telescope_rag.providers.validation import output_schema


def anchored_part(text, **changes):
    fields = dict(
        original_text=text,
        constraint_quotes=(),
        state="public",
        operation="search",
        intended_use="general_excerpt",
        retrieval_query=text,
        document_handles=(),
        owner_handle=None,
        block_types=(),
        source_language=None,
        reference_text=None,
        history_indices=(),
        reason=None,
    )
    return AnchoredPlannerPart(**(fields | changes))


def bindings():
    chunk = SimpleNamespace(
        document_id="synthetic-document",
        canonical_url="https://telescopecenter.com/synthetic/",
        page_title="Synthetic source",
        doctor_id=None,
        canonical_doctor_id=None,
    )
    return SourceBindings(SimpleNamespace(chunks={"synthetic": chunk}, prepared_digest="synthetic"))


def bind(query, parts, language="en", **request_fields):
    request = WorkflowRequest(query=query, **request_fields)
    proposal = AnchoredPlannerReply(language=language, parts=tuple(parts))
    derived, receipts = resolve_anchored_plan(proposal, request, "issued")
    validated = bindings().validate(derived, request, "issued", max_parts=4)
    return derived, receipts, validated


@pytest.mark.parametrize(
    "language,text,constraint",
    [
        ("en", "State the posted hours only; do not send a message.", "do not send a message"),
        ("ar", "اذكر المعلومة المنشورة فقط؛ لا ترسل أي رسالة.", "لا ترسل أي رسالة"),
        ("ar-JO", "بس احكيلي الحكي المنشور؛ ما تبعت رسالة.", "ما تبعت رسالة"),
        ("en", "😀 e\u0301 remains literal; keep 7:00–8:00 exactly.", "7:00–8:00"),
        ("ar", "اِحفظْ التشكيلَ\u200f والوقت ١٠:٣٠ كما هو.", "١٠:٣٠"),
    ],
)
def test_exact_unicode_anchors_derive_offsets_and_preserve_every_field(language, text, constraint):
    part = anchored_part(text, constraint_quotes=(constraint,), document_handles=("d0001",))
    before = part.model_dump()
    derived, receipts, validated = bind(text, (part,), language)
    assert (derived.parts[0].start, derived.parts[0].end) == (0, len(text))
    assert {
        k: v for k, v in derived.parts[0].model_dump().items() if k not in {"start", "end"}
    } == {k: v for k, v in before.items() if k not in {"original_text", "constraint_quotes"}}
    assert part.model_dump() == before
    receipt = receipts[0]
    assert receipt.part_id == validated.assembly_request.parts[0].part_id == "issued-p1"
    assert text[receipt.original.start : receipt.original.end] == receipt.original.quote == text
    assert text[receipt.constraints[0].start : receipt.constraints[0].end] == constraint
    assert not validated.semantic_interpretation_verified


@pytest.mark.parametrize(
    "original,quote",
    [
        ("banana", "ana"),
        ("same / same", "same"),
        ("نفس النص ثم نفس النص", "نفس النص"),
        ("😀x😀x", "😀x"),
    ],
)
def test_repeated_including_overlapping_matches_are_ambiguous(original, quote):
    with pytest.raises(AnchorError, match="^ambiguous_original_text_anchor$"):
        unique_original_span(original, quote)


@pytest.mark.parametrize(
    "original,quote",
    [
        ("Case matters.", "case matters."),
        ("a  b", "a b"),
        ("one\r\ntwo", "one\ntwo"),
        ("e\u0301", "é"),
        ("الاسم أمانة", "الاسم امانة"),
        ("لا تُغيّر", "لا تغير"),
        ("Text ends.", "Text ends!"),
    ],
)
def test_no_case_whitespace_unicode_spelling_or_punctuation_normalization(original, quote):
    with pytest.raises(AnchorError, match="^original_text_anchor_not_found$"):
        unique_original_span(original, quote)


@pytest.mark.parametrize("quote", ["", " ", "\n\t"])
def test_empty_or_whitespace_anchors_are_not_meaningful(quote):
    with pytest.raises(AnchorError, match="^empty_original_text_anchor$"):
        unique_original_span("query " + quote, quote)


def test_longer_literal_context_disambiguates_without_picking_an_occurrence():
    first, second = "same at home;", " same at work."
    _, receipts, _ = bind(first + second, (anchored_part(first), anchored_part(second)))
    assert receipts[0].original.start == 0 and receipts[1].original.start == len(first)


@pytest.mark.parametrize(
    "constraint,code",
    [
        ("outside", "constraint_outside_original_part"),
        ("absent", "original_text_anchor_not_found"),
        ("repeat", "ambiguous_original_text_anchor"),
    ],
)
def test_constraints_cannot_escape_their_literal_part_or_pick_an_ambiguous_occurrence(
    constraint, code
):
    request = WorkflowRequest(query="repeat inside repeat outside")
    reply = AnchoredPlannerReply(
        language="en", parts=(anchored_part("repeat inside", constraint_quotes=(constraint,)),)
    )
    with pytest.raises(AnchorError, match=f"^{code}$"):
        resolve_anchored_plan(reply, request, "issued")


def test_duplicate_constraint_metadata_fails_instead_of_silent_deduplication():
    part = anchored_part("Keep this only.", constraint_quotes=("only", "only"))
    with pytest.raises(AnchorError, match="^duplicate_constraint_anchor$"):
        bind(part.original_text, (part,))


@pytest.mark.parametrize(
    "text,shortened",
    [
        ("Quoted scope only; do not write.", "Quoted scope only."),
        ("المعلومة فقط؛ لا تعدل السجل.", "المعلومة فقط"),
        ("بس المعلن؛ ما تحجز إشي.", "بس المعلن"),
        ("Compare X and Y before 07:00.", "Compare X and Y."),
    ],
)
def test_search_must_retain_the_whole_original_part_even_if_constraints_list_is_empty(
    text, shortened
):
    with pytest.raises(AnchorError, match="^retrieval_query_lost_original_part$"):
        bind(text, (anchored_part(text, retrieval_query=shortened),))


def test_history_can_extend_search_but_cannot_supply_the_original_anchor():
    query = "What about the published role?"
    history = ({"role": "user", "content": "Synthetic Doctor Q"},)
    _, _, bound = bind(
        query,
        (
            anchored_part(
                query,
                retrieval_query="Synthetic Doctor Q: " + query,
                reference_text="Synthetic Doctor Q",
                history_indices=(0,),
            ),
        ),
        history=history,
    )
    assert bound.retrieval_queries[0].text == "Synthetic Doctor Q: " + query
    with pytest.raises(AnchorError, match="original_text_anchor_not_found"):
        bind(query, (anchored_part("Synthetic Doctor Q"),), history=history)


def test_exact_anchors_do_not_waive_complete_coverage_or_four_part_limit():
    with pytest.raises(ValidationError, match="unaccounted_original_request_text"):
        bind("One. Two.", (anchored_part("One."),))
    with pytest.raises(ValidationError):
        AnchoredPlannerReply(language="en", parts=tuple(anchored_part("One.") for _ in range(5)))


def test_shared_literal_constraints_remain_owned_by_each_distinct_app_part():
    query = "Compare source A and source B; do not send messages."
    a = anchored_part(
        query, constraint_quotes=("do not send messages",), intended_use="doctor_role"
    )
    b = anchored_part(
        query, constraint_quotes=("do not send messages",), intended_use="profile_detail"
    )
    _, receipts, validated = bind(query, (a, b))
    assert [r.part_id for r in receipts] == [p.part_id for p in validated.assembly_request.parts]
    assert receipts[0].constraints == receipts[1].constraints
    assert len(validated.assembly_request.parts) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"document_handles": ("not-issued",)},
        {"owner_handle": "not-issued"},
        {"operation": "read_source", "retrieval_query": None},
        {
            "state": "excluded",
            "retrieval_query": None,
            "document_handles": ("d0001",),
            "reason": "Synthetic excluded request",
        },
    ],
)
def test_new_anchors_do_not_bypass_existing_scope_or_nonpublic_boundaries(changes):
    with pytest.raises(ValueError):
        bind("Synthetic request.", (anchored_part("Synthetic request.", **changes),))


def test_read_source_keeps_constraints_without_inventing_a_search_query():
    query = "Read this admitted source only; do not write."
    part = anchored_part(
        query,
        constraint_quotes=("do not write",),
        operation="read_source",
        retrieval_query=None,
        document_handles=("d0001",),
    )
    _, receipts, validated = bind(query, (part,))
    assert not validated.retrieval_queries and receipts[0].constraints[0].quote == "do not write"


def test_resolver_never_claims_semantic_classification_or_repairs_a_declared_state():
    query = "Only public information; do not book."
    part = anchored_part(
        query,
        state="excluded",
        retrieval_query=None,
        reason="Deliberately incorrect authored classification for boundary testing.",
    )
    derived, _, validated = bind(query, (part,))
    assert derived.parts[0].state == "excluded"
    assert not validated.semantic_interpretation_verified


def test_closed_new_schema_has_no_model_issued_offsets_or_part_ids():
    wire = AnchoredPlannerReply(language="en", parts=(anchored_part("Synthetic."),)).model_dump(
        mode="json"
    )
    for field in ("start", "end", "part_id"):
        changed = json.loads(json.dumps(wire))
        changed["parts"][0][field] = 0
        with pytest.raises(ValidationError):
            AnchoredPlannerReply.model_validate_json(json.dumps(changed))
    schema = output_schema(AnchoredPlannerReply)["schema"]
    for definition in (schema, schema["$defs"]["AnchoredPlannerPart"]):
        assert definition["additionalProperties"] is False
        assert set(definition["properties"]) == set(definition["required"])
