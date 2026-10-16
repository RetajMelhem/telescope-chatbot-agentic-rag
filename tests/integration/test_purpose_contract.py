"""Synthetic contract regressions; authored plans do not measure model understanding."""

import asyncio
import json
from typing import get_args

import httpx2 as httpx
import pytest
from test_anchored_workflow import part, wire
from test_offline_workflow import FakeRetriever, SyntheticCounter, catalog, source
from test_source_scope_profile import fixtures

from telescope_rag.core.settings import Settings
from telescope_rag.graph.anchoring import AnchoredPlannerReply, resolve_anchored_plan
from telescope_rag.graph.bindings import SourceBindings, SourceFilterError
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, QuoteDraft, WorkflowRequest
from telescope_rag.graph.planning import planner_messages
from telescope_rag.graph.purpose_contract import (
    INTENDED_USE_DEFINITIONS,
    purpose_contract_manifest,
)
from telescope_rag.graph.workflow import OfflineRagWorkflow, WorkflowError
from telescope_rag.providers.openrouter import OpenRouterProviders
from telescope_rag.retrieval.assembly import IntendedUse, limited_to_context


def validate(bindings, **changes):
    request = WorkflowRequest(query="Synthetic exact request.")
    proposal = AnchoredPlannerReply(language="en", parts=(part(request.query, **changes),))
    original = proposal.model_dump_json()
    numeric, _ = resolve_anchored_plan(proposal, request, "synthetic")
    try:
        return bindings.validate(numeric, request, "synthetic", max_parts=4)
    finally:
        assert proposal.model_dump_json() == original  # Never repair returned plans.


def test_contract_covers_every_existing_use_without_changing_wire_enum():
    assert set(INTENDED_USE_DEFINITIONS) == set(get_args(IntendedUse))
    value = purpose_contract_manifest()
    value["intended_use_definitions"]["general_excerpt"] = "tampered"
    assert "tampered" not in purpose_contract_manifest()["intended_use_definitions"].values()
    assert set(
        AnchoredPlannerReply.model_json_schema()["$defs"]["AnchoredPlannerPart"]["properties"][
            "intended_use"
        ]["enum"]
    ) == set(INTENDED_USE_DEFINITIONS)


def test_source_language_inventory_uses_chunks_even_with_misleading_title_and_url():
    a = source(1, document="mixed").model_copy(update={"language": "ar"})
    b = source(2, document="mixed").model_copy(update={"language": "en"})
    c = source(3, document="unknown").model_copy(update={"language": "und"})
    evidence = catalog(a, b, c)
    plain = SourceBindings(evidence, include_block_types=True)
    strict = SourceBindings(evidence, include_block_types=True, purpose_contract=True)
    old, new = (json.loads(b.manifest_json) for b in (plain, strict))
    assert [d.pop("available_source_languages") for d in new["documents"]] == [
        ["ar", "en"],
        ["und"],
    ]
    assert new.pop("purpose_contract") == purpose_contract_manifest()
    assert old == new


@pytest.mark.parametrize("profile", ["baseline", "policy_targets", "source_scoped"])
def test_old_profiles_cannot_accidentally_use_strict_contract_metadata(profile):
    _, evidence, authority = fixtures()
    strict = SourceBindings(evidence, directory_authority=authority, purpose_contract=True)
    with pytest.raises(ValueError, match="planner_purpose_contract_configuration_mismatch"):
        planner_messages(WorkflowRequest(query="Synthetic."), strict, max_parts=4, profile=profile)


@pytest.mark.parametrize("enabled,authority_present", [(False, True), (True, False)])
def test_new_prompt_requires_matching_validation_and_authority(enabled, authority_present):
    _, evidence, authority = fixtures()
    bindings = SourceBindings(
        evidence,
        directory_authority=authority if authority_present else None,
        purpose_contract=enabled,
    )
    with pytest.raises(ValueError, match="planner_purpose_contract_configuration_mismatch"):
        planner_messages(
            WorkflowRequest(query="Synthetic."), bindings, max_parts=4, profile="purpose_contract"
        )


@pytest.mark.parametrize("operation", ["search", "read_source"])
@pytest.mark.parametrize("filter_kind", ["language", "type", "owner", "combined"])
def test_empty_combined_explicit_scope_rejected_without_repair(operation, filter_kind):
    # Every component of the combined case exists on this page, but not on one chunk.
    a = source(1, document="same", doctor_id="a", doctor_name="A").model_copy(
        update={"language": "en", "block_type": "doctor"}
    )
    b = source(2, document="same").model_copy(update={"language": "ar", "block_type": "faq"})
    c = source(3, document="other", doctor_id="b", doctor_name="B")
    evidence = catalog(a, b, c)
    strict = SourceBindings(evidence, purpose_contract=True)
    handle = next(h for h, identity in strict.documents.items() if identity == "same")
    a_owner = next(h for h, identity in strict.owners.items() if identity == ("literal", "a"))
    b_owner = next(h for h, identity in strict.owners.items() if identity == ("literal", "b"))
    changes = {
        "language": {"source_language": "und"},
        "type": {"block_types": ("table",)},
        "owner": {"owner_handle": b_owner},
        "combined": {"source_language": "ar", "block_types": ("doctor",), "owner_handle": a_owner},
    }[filter_kind]
    kwargs = dict(
        document_handles=(handle,),
        operation=operation,
        retrieval_query=None if operation == "read_source" else "Synthetic exact request.",
        **changes,
    )
    with pytest.raises(SourceFilterError, match="^planner_source_filters_have_empty_intersection$"):
        validate(strict, **kwargs)
    # Retain baseline behavior to reconstruct sealed experiments.
    old = SourceBindings(evidence)
    assert old.documents == strict.documents and old.owners == strict.owners
    assert not evidence.scope_members(validate(old, **kwargs).assembly_request.parts[0].scope)


@pytest.mark.parametrize("kind", ["none", "language", "union", "canonical", "unscoped"])
def test_compatible_or_unfiltered_scope_remains_literal_and_public(kind):
    a = source(
        1,
        document="same",
        doctor_id="a",
        doctor_name="A",
        canonical_doctor_id="canonical-a",
        canonical_doctor_name="A",
    )
    b = source(2, document="other").model_copy(update={"language": "ar"})
    bindings = SourceBindings(catalog(a, b), purpose_contract=True)
    handle = next(h for h, identity in bindings.documents.items() if identity == "same")
    canonical = next(h for h, i in bindings.owners.items() if i[0] == "canonical")
    kwargs = {"document_handles": (handle,)}
    if kind == "language":
        kwargs["source_language"] = "en"
    elif kind == "union":
        kwargs.update(document_handles=tuple(bindings.documents), source_language="ar")
    elif kind == "canonical":
        kwargs["owner_handle"] = canonical
    elif kind == "unscoped":
        kwargs.update(document_handles=(), source_language="und")
    plan = validate(bindings, **kwargs)
    scope = plan.assembly_request.parts[0].scope
    assert plan.assembly_request.parts[0].state == "public"
    assert scope.language == kwargs.get("source_language")
    assert scope.document_ids == tuple(bindings.documents[h] for h in kwargs["document_handles"])


@pytest.mark.parametrize(
    "language,query",
    [
        ("en", "Report the exact published statement; do not message anyone."),
        ("ar", "انقل النص المنشور حرفياً؛ لا تراسل أحداً."),
        ("ar-JO", "انقل المكتوب زي ما هو؛ ما تبعت لحدا."),
    ],
)
@pytest.mark.parametrize("source_language", [None, "en", "ar"])
def test_real_graph_mock_wire_blocks_impossible_filter_before_retrieval_or_draft(
    language, query, source_language
):
    async def run():
        items, evidence, authority = fixtures()  # All actual synthetic source languages are en.
        settings = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        retriever = FakeRetriever(lambda i, q: (items[2].chunk_id,))
        seen = []
        flow = None

        def handler(request):
            payload = json.loads(request.read())
            body = json.loads(payload["messages"][-1]["content"])
            seen.append(body)
            assert "reasoning" not in payload
            assert body["prompt_version"] == "offline-rag-planner-purpose-contract-v8"
            if len(seen) == 1:
                assert payload["response_format"]["json_schema"]["name"] == "AnchoredPlannerReply"
                assert "purpose_contract" in body["source_manifest"]
                handle = next(h for h, i in flow._bindings.documents.items() if i == "faq")
                value = AnchoredPlannerReply(
                    language=language,
                    parts=(
                        part(
                            query,
                            document_handles=(handle,),
                            source_language=source_language,
                            constraint_quotes=(query.split("; ")[-1],) if language == "en" else (),
                        ),
                    ),
                )
            else:
                assert source_language != "ar"
                assert body["source_manifest"]["purpose_contract"] == purpose_contract_manifest()
                assert body["parts"][0]["answer_target"] == query
                assert body["parts"][0]["intended_use"] == "general_excerpt"
                value = AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=body["parts"][0]["part_id"],
                            status="candidate",
                            quotes=(
                                QuoteDraft(
                                    chunk_id=items[2].chunk_id, quote=items[2].retrieval_text
                                ),
                            ),
                            reason_code=None,
                        ),
                    )
                )
            return wire(value)

        async with OpenRouterProviders(settings, transport=httpx.MockTransport(handler)) as p:
            flow = OfflineRagWorkflow(
                settings=settings,
                chat=p.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="purpose_contract",
                directory_authority=authority,
            )
            result = await flow.run(
                WorkflowRequest(query=query, language="ar" if language == "ar-JO" else language)
            )
        if source_language == "ar":
            assert result.result.error_code == "planner_source_filters_have_empty_intersection"
            assert len(seen) == 1 and not retriever.calls and result.plan is None
            assert "retrieve_evidence" not in result.stages
        else:
            assert result.result.outcome == "draft_ready" and len(seen) == 2
            assert len(retriever.calls) == 1
            assert result.plan.assembly_request.parts[0].scope.language == source_language
            quote = result.result.parts[0].quotes[0]
            assert (
                quote.quote == items[2].retrieval_text
                and quote.source_url == items[2].canonical_url
            )
        assert not result.result.semantic_grounding_verified
        assert not result.result.luna_compatibility_verified

    asyncio.run(run())


@pytest.mark.parametrize(
    "code,restricted,report",
    [
        (
            "consultation_fee_offer_reconciliation_unverified",
            "consultation_eligibility",
            "general_excerpt",
        ),
        (
            "department_titles_non_authoritative_use_explicit_roles",
            "doctor_role",
            "general_excerpt",
        ),
        ("name_only_profile_no_specialty_or_biography_claim", "profile_detail", "general_excerpt"),
        (
            "generic_faq_specific_procedure_scope_unverified",
            "procedure_specific",
            "general_excerpt",
        ),
        ("damaged_description_excluded_heading_only", "service_description", "service_name"),
        (
            "parallel_category_membership_unresolved_no_category_assertion",
            "technique_category",
            "general_excerpt",
        ),
    ],
)
def test_contract_never_overrides_existing_source_policy(code, restricted, report):
    item = source(1, source_issue_codes=(code,))
    assert limited_to_context(item, restricted) and not limited_to_context(item, report)
    bindings = SourceBindings(catalog(item), purpose_contract=True)
    for use in (restricted, report):
        plan = validate(bindings, intended_use=use, document_handles=tuple(bindings.documents))
        assert plan.assembly_request.parts[0].intended_use == use
    # No semantic label selection is performed by this test or the application.


def test_new_workflow_remains_opt_in_and_requires_authority():
    _, evidence, _ = fixtures()
    with pytest.raises(WorkflowError, match="offline_workflow_configuration_invalid"):
        OfflineRagWorkflow(
            settings=Settings(_env_file=None, app_env="test"),
            chat=None,
            retriever=None,
            catalog=evidence,
            counter=SyntheticCounter(),
            token_basis="synthetic_test",
            planner_profile="purpose_contract",
        )


@pytest.mark.parametrize(
    "language,query",
    [
        ("en", "Compare A and B using this source only; do not book."),
        ("ar", "قارن أ وب باستخدام هذا المصدر فقط؛ لا تحجز."),
        ("ar-JO", "قارن أ وب من هالمصدر بس؛ ما تحجز."),
    ],
)
def test_joint_target_preserves_shared_constraints_and_distinct_identical_role_owners(
    language, query
):
    async def run():
        from telescope_rag.knowledge.source_authority import DirectoryAuthority

        items = [
            source(
                i,
                "Synthetic identical specialty.",
                document="main",
                doctor_id=name,
                doctor_name=name,
            ).model_copy(update={"block_type": "doctor"})
            for i, name in ((1, "A"), (2, "B"))
        ]
        evidence = catalog(*items)
        authority = DirectoryAuthority(
            prepared_digest=evidence.prepared_digest,
            admission_policy_hash="synthetic-policy",
            primary_directory_document_ids=("main",),
        )
        settings = Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-only")
        seen = []
        constraint = query[query.index(";") + 2 :] if ";" in query else query.split("؛ ")[1]

        def handler(request):
            body = json.loads(json.loads(request.read())["messages"][-1]["content"])
            seen.append(body)
            if len(seen) == 1:
                value = AnchoredPlannerReply(
                    language=language,
                    parts=(
                        part(
                            query,
                            document_handles=("d0001",),
                            intended_use="doctor_role",
                            constraint_quotes=(constraint,),
                        ),
                    ),
                )
            else:
                value = AnswerDraft(
                    parts=(
                        PartDraft(
                            part_id=body["parts"][0]["part_id"],
                            status="candidate",
                            quotes=tuple(
                                QuoteDraft(chunk_id=c.chunk_id, quote=c.retrieval_text)
                                for c in items
                            ),
                            reason_code=None,
                        ),
                    )
                )
            return wire(value)

        retriever = FakeRetriever(lambda i, q: tuple(c.chunk_id for c in items))
        async with OpenRouterProviders(settings, transport=httpx.MockTransport(handler)) as p:
            result = await OfflineRagWorkflow(
                settings=settings,
                chat=p.chat,
                retriever=retriever,
                catalog=evidence,
                counter=SyntheticCounter(),
                token_basis="synthetic_test",
                planner_profile="purpose_contract",
                directory_authority=authority,
            ).run(WorkflowRequest(query=query))
        assert result.result.outcome == "draft_ready"
        assert result.answer_targets[0].target.quote == query
        assert result.request_anchors[0].constraints[0].quote == constraint
        assert {q.literal_owner_id for q in result.result.parts[0].quotes} == {"A", "B"}
        assert result.plan.assembly_request.parts[0].scope.owner_id is None
        assert not result.result.semantic_grounding_verified

    asyncio.run(run())
