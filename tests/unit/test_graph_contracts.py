"""Synthetic literal/schema checks; scripts do not decide semantic scope or relevance."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import (
    AnswerDraft,
    HistoryTurn,
    PlannerPart,
    PlannerReply,
    WorkflowRequest,
)
from telescope_rag.providers.validation import output_schema


@pytest.fixture
def bindings():
    # Only handle/plan logic is under test. EvidenceCatalog source-admission
    # checks and original provenance are tested separately, using real models.
    source = SimpleNamespace(
        document_id="synthetic-document",
        canonical_url="https://telescopecenter.com/synthetic/",
        page_title="Synthetic public source",
        doctor_id="literal-a",
        doctor_name="Doctor A",
        canonical_doctor_id="canonical-a",
        canonical_doctor_name="Doctor A Canonical",
    )
    return SourceBindings(
        SimpleNamespace(chunks={"synthetic": source}, prepared_digest="synthetic")
    )


def proposal(text="Question", **changes):
    values = dict(
        start=0,
        end=len(text),
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
    values.update(changes)
    return PlannerPart(**values)


def validate(bindings, parts=None, request=None, *, language="en", max_parts=4):
    request = request or WorkflowRequest(query="Question")
    return bindings.validate(
        PlannerReply(language=language, parts=parts or (proposal(request.query),)),
        request,
        "application-issued-request",
        max_parts=max_parts,
    )


@pytest.mark.parametrize("schema", [PlannerReply, AnswerDraft])
def test_provider_wire_schemas_are_closed_and_all_nested_properties_required(schema):
    definition = output_schema(schema)
    assert definition["strict"] is True

    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["properties"]) == set(value["required"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(definition)


@pytest.mark.parametrize("field", ["reason", "owner_handle", "reference_text", "source_language"])
def test_nullable_wire_properties_cannot_be_omitted(field):
    raw = proposal().model_dump(mode="json")
    del raw[field]
    with pytest.raises(ValidationError):
        PlannerPart.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize(
    "field,value",
    [
        ("part_id", "model-issued"),
        ("source_url", "https://outside.example/"),
        ("tools", ["shell"]),
        ("budget", 999999),
    ],
)
def test_model_cannot_issue_part_ids_tools_runtime_budgets_or_arbitrary_sources(field, value):
    raw = proposal().model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValidationError):
        PlannerPart.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize("value", ["0", False, 0.0])
def test_span_indices_are_strict_integers(value):
    raw = proposal().model_dump(mode="json")
    raw["start"] = value
    with pytest.raises(ValidationError):
        PlannerPart.model_validate_json(json.dumps(raw))


def test_app_issues_part_ids_and_preserves_original_text_qualifiers_and_literal_scope(bindings):
    query = "Doctor A only; do not include Doctor B."
    owner_handle = next(
        h for h, identity in bindings.owners.items() if identity == ("literal", "literal-a")
    )
    part = proposal(
        query, document_handles=("d0001",), owner_handle=owner_handle, intended_use="doctor_role"
    )
    result = validate(bindings, (part,), WorkflowRequest(query=query))
    accepted = result.assembly_request.parts[0]
    assert accepted.part_id == "application-issued-request-p1"
    assert result.assembly_request.original_query == query
    assert accepted.scope.document_ids == ("synthetic-document",)
    assert accepted.scope.owner_kind == "literal"
    assert accepted.scope.owner_id == "literal-a"
    assert result.retrieval_queries[0].text == query
    assert result.semantic_interpretation_verified is False


def test_canonical_owner_handle_is_explicit_metadata_not_a_fuzzy_name_mapping(bindings):
    handle = next(h for h, identity in bindings.owners.items() if identity[0] == "canonical")
    result = validate(bindings, (proposal(owner_handle=handle),))
    scope = result.assembly_request.parts[0].scope
    assert (scope.owner_kind, scope.owner_id) == ("canonical", "canonical-a")


@pytest.mark.parametrize(
    "parts",
    [
        (proposal(start=1),),
        (proposal(end=100),),
        (proposal(start=0, end=3), proposal(start=4, end=8)),
    ],
)
def test_unaccounted_original_characters_or_out_of_range_spans_fail(bindings, parts):
    with pytest.raises(ValueError):
        validate(bindings, parts)


def test_four_part_limit_never_truncates_or_silently_drops_public_siblings(bindings):
    with pytest.raises(ValueError):
        validate(bindings, (proposal(), proposal(), proposal()), max_parts=2)
    accepted = validate(bindings, (proposal(), proposal(), proposal(), proposal()))
    assert len(accepted.assembly_request.parts) == 4
    assert len({p.part_id for p in accepted.assembly_request.parts}) == 4


@pytest.mark.parametrize(
    "change",
    [
        {"document_handles": ("not-issued",)},
        {"owner_handle": "literal-a"},
        {"document_handles": ("d0001", "d0001")},
        {"block_types": ("doctor", "doctor")},
        {"history_indices": (0,)},
        {"history_indices": (-1,)},
    ],
)
def test_unknown_raw_or_duplicate_source_and_history_bindings_fail(bindings, change):
    with pytest.raises(ValueError):
        validate(bindings, (proposal(**change),))


@pytest.mark.parametrize("state", ["excluded", "clarification_required"])
def test_nonpublic_parts_remain_in_original_span_accounting_without_retrieval(bindings, state):
    query = "Public; private?"
    accepted = validate(
        bindings,
        (
            proposal(query, end=7, retrieval_query="Public"),
            proposal(
                query, start=7, state=state, retrieval_query=None, reason="Synthetic boundary"
            ),
        ),
        WorkflowRequest(query=query),
    )
    assert len(accepted.assembly_request.parts) == 2
    assert accepted.assembly_request.parts[1].state == state
    assert len(accepted.retrieval_queries) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"retrieval_query": "Private text"},
        {"document_handles": ("d0001",)},
        {"owner_handle": "o0001"},
        {"block_types": ("doctor",)},
        {"source_language": "en"},
        {"reason": None},
        {"reason": " "},
    ],
)
def test_nonpublic_parts_cannot_smuggle_retrieval_or_missing_reasons(bindings, change):
    values = dict(state="excluded", retrieval_query=None, reason="Synthetic exclusion")
    values.update(change)
    with pytest.raises(ValueError):
        validate(bindings, (proposal(**values),))


@pytest.mark.parametrize("query", [None, "", " "])
def test_public_search_requires_nonblank_standalone_query(bindings, query):
    with pytest.raises(ValueError):
        validate(bindings, (proposal(retrieval_query=query),))


def test_complete_reads_require_exact_handles_and_derive_complete_catalog_scope(bindings):
    with pytest.raises(ValueError):
        validate(bindings, (proposal(operation="read_source", retrieval_query=None),))
    result = validate(
        bindings,
        (
            proposal(
                operation="read_source",
                retrieval_query=None,
                document_handles=("d0001",),
                block_types=("doctor",),
            ),
        ),
    )
    assert result.assembly_request.parts[0].scope.complete is True
    assert result.retrieval_queries == ()


@pytest.mark.parametrize("operation", ["read_source", "time_comparison"])
def test_nonsearch_operations_do_not_have_a_model_retrieval_query(bindings, operation):
    with pytest.raises(ValueError):
        validate(bindings, (proposal(operation=operation),))


def test_history_reference_must_be_literal_and_retained_in_standalone_query(bindings):
    request = WorkflowRequest(
        query="What is his role?", history=(HistoryTurn(role="user", content="Doctor A"),)
    )
    accepted = validate(
        bindings,
        (
            proposal(
                request.query,
                retrieval_query="Doctor A role",
                reference_text="Doctor A",
                history_indices=(0,),
            ),
        ),
        request,
    )
    assert accepted.retrieval_queries[0].text == "Doctor A role"
    assert request.history[0].content == "Doctor A"
    assert accepted.semantic_interpretation_verified is False
    for ref, query in [("Invented Doctor", "Invented Doctor role"), ("Doctor A", "his role")]:
        with pytest.raises(ValueError):
            validate(
                bindings,
                (
                    proposal(
                        request.query,
                        reference_text=ref,
                        retrieval_query=query,
                        history_indices=(0,),
                    ),
                ),
                request,
            )


@pytest.mark.parametrize("indices", [(0, 0), (-1,), (1,)])
def test_history_links_cannot_duplicate_or_escape_supplied_turns(bindings, indices):
    request = WorkflowRequest(
        query="What role?", history=(HistoryTurn(role="user", content="Doctor A"),)
    )
    with pytest.raises(ValueError):
        validate(bindings, (proposal(request.query, history_indices=indices),), request)


@pytest.mark.parametrize("requested,returned", [("en", "ar"), ("ar", "en")])
def test_explicit_request_language_is_preserved(bindings, requested, returned):
    with pytest.raises(ValueError):
        validate(
            bindings,
            request=WorkflowRequest(query="Question", language=requested),
            language=returned,
        )


def test_colloquial_arabic_language_label_is_preserved_without_changing_public_input_schema(
    bindings,
):
    query = "شو شغله؟"
    result = validate(
        bindings, request=WorkflowRequest(query=query, language="ar"), language="ar-JO"
    )
    assert result.language == "ar-JO"
    assert result.assembly_request.original_query == query


@pytest.mark.parametrize(
    "change",
    [
        {"query": " "},
        {"query": "x" * 4001},
        {"history": tuple(HistoryTurn(role="user", content="x") for _ in range(7))},
        {
            "history": (
                HistoryTurn(role="user", content="x" * 8000),
                HistoryTurn(role="assistant", content="x"),
            )
        },
    ],
)
def test_request_limits_reject_instead_of_silently_trimming_history_or_query(change):
    with pytest.raises(ValidationError):
        WorkflowRequest(**({"query": "Question"} | change))
