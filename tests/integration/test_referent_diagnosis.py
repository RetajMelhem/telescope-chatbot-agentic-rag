"""Synthetic consumer-boundary checks; fixtures are deliberately not semantic scores."""

import asyncio
import json
from pathlib import Path

import pytest
from test_offline_workflow import catalog
from test_source_scope_profile import source

from scripts import diagnose_referent_failures as diagnostic
from telescope_rag.graph.anchoring import AnchoredPlannerReply
from telescope_rag.graph.bindings import SourceBindings
from telescope_rag.graph.contracts import AnswerDraft, PartDraft, WorkflowRequest
from telescope_rag.knowledge.source_authority import DirectoryAuthority
from telescope_rag.providers.contracts import StructuredResult


def fixtures():
    items = (
        source(
            1,
            "Synthetic A: training Alpha.",
            document="main",
            block_type="doctor",
            doctor_id="a",
            doctor_name="Person A",
        ),
        source(
            2,
            "Synthetic B: training Beta.",
            document="main",
            block_type="doctor",
            doctor_id="b",
            doctor_name="Person B",
        ),
        source(
            3,
            "Person A",
            document="profile",
            block_type="doctor",
            doctor_id="a",
            doctor_name="Person A",
            source_issue_codes=("name_only_profile_no_specialty_or_biography_claim",),
        ),
        source(4, "Synthetic contact footer.", document="profile", block_type="section"),
        source(5, "Synthetic ServiceX method.", document="services", block_type="section"),
        source(6, "Synthetic ServiceY method.", document="services", block_type="section"),
        source(
            7,
            "ServiceZ",
            document="services",
            block_type="section",
            source_issue_codes=("damaged_description_excluded_heading_only",),
        ),
    )
    evidence = catalog(*items)
    authority = DirectoryAuthority(
        prepared_digest=evidence.prepared_digest,
        admission_policy_hash="synthetic-policy",
        primary_directory_document_ids=("main",),
    )
    bindings = SourceBindings(
        evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
    )
    handles = {document: handle for handle, document in bindings.documents.items()}
    return items, evidence, authority, handles


def part(text, document, use="service_description", **changes):
    return {
        "original_text": text,
        "constraint_quotes": [],
        "state": "public",
        "operation": "search",
        "intended_use": use,
        "retrieval_query": text,
        "document_handles": [document],
        "owner_handle": None,
        "block_types": [],
        "source_language": None,
        "reference_text": None,
        "history_indices": [],
        "reason": None,
        **changes,
    }


def wire(parts):
    return AnchoredPlannerReply.model_validate_json(json.dumps({"language": "en", "parts": parts}))


def probe(request, proposal, candidates, *, profile="referent_context", forced=None):
    _, evidence, authority, _ = fixtures()
    return asyncio.run(
        diagnostic.consumer_probe(
            request,
            proposal,
            evidence,
            authority,
            tuple(tuple(p) for p in candidates),
            profile=profile,
            identity="synthetic",
            forced_quotes=forced,
        )
    )


@pytest.mark.parametrize("profile", ["purpose_contract", "referent_context"])
@pytest.mark.parametrize(
    "texts",
    [
        ("Describe ServiceX.", "What does it combine?"),
        ("صف الخدمة ServiceX.", "ماذا تجمع؟"),
        ("احكي عن ServiceX.", "شو بتجمع؟"),
    ],
)
def test_actual_nodes_do_not_repair_missing_referent_and_full_context_reaches_draft(profile, texts):
    items, _, _, handles = fixtures()
    request = WorkflowRequest(query=" ".join(texts))
    proposal = wire([part(text, handles["services"]) for text in texts])
    original = proposal.model_dump_json()
    result = probe(request, proposal, [[items[4].chunk_id], [items[5].chunk_id]], profile=profile)
    intake = result["fixture_retrieval_calls"][0]["queries"]
    assert intake[1]["text"] == texts[1]
    body = json.loads(result["draft_messages"][1]["content"])
    assert body["original_query"] == request.query
    assert body["parts"][1]["answer_target"] == texts[1]
    assert body["parts"][1]["reference_context"]["literal_text"] is None
    assert result["result"]["parts"][1]["quotes"][0]["quote"] == items[5].retrieval_text
    assert not result["semantic_support_assessed"] and result["semantic_grade"] is None
    assert proposal.model_dump_json() == original and result["model_inference_requests"] == 0


@pytest.mark.parametrize("profile", ["purpose_contract", "referent_context"])
@pytest.mark.parametrize(
    "texts",
    [
        (
            "List Person A and Person B roles from the main directory.",
            "What training does each list?",
        ),
        ("اذكر تخصص Person A وPerson B من الدليل الرئيسي.", "وما تدريب كل منهما؟"),
        ("شو تخصص Person A وPerson B بالدليل الرئيسي؟", "وشو تدريب كل واحد؟"),
    ],
)
def test_only_explicit_authored_source_change_restores_filtered_training_without_merging_owners(
    profile, texts
):
    items, _, _, handles = fixtures()
    request = WorkflowRequest(query=" ".join(texts))
    proposal = wire(
        [
            part(texts[0], handles["main"], "doctor_role"),
            part(texts[1], handles["profile"], "profile_detail"),
        ]
    )
    selected = [[items[0].chunk_id, items[1].chunk_id], [items[0].chunk_id, items[1].chunk_id]]
    bad = probe(request, proposal, selected, profile=profile)
    assert bad["result"]["parts"][1]["status"] == "unknown"
    assert bad["assembly_receipts"][1]["candidate_status"] == "scope_filtered"
    original = proposal.model_dump_json()
    fixed = diagnostic.variant_of(
        proposal,
        (diagnostic.PartEdit(part_index=1, fields={"document_handles": [handles["main"]]}),),
    )
    good = probe(request, fixed, selected, profile=profile)
    assert {q["literal_owner_id"] for q in good["result"]["parts"][1]["quotes"]} == {"a", "b"}
    assert (
        proposal.model_dump_json() == original
        and good["result"]["semantic_grounding_verified"] is False
    )


def test_name_only_profile_does_not_establish_training_but_footer_can_still_be_irrelevant_quote():
    items, _, _, handles = fixtures()
    request = WorkflowRequest(query="What training does Person A publish?")
    proposal = wire([part(request.query, handles["profile"], "profile_detail")])
    sparse = probe(request, proposal, [[items[2].chunk_id]])
    assert sparse["allowed_quote_chunk_ids"] == [[]]
    assert sparse["result"]["parts"][0]["reason_code"] == "context_only"
    footer = probe(request, proposal, [[items[3].chunk_id]])
    assert footer["result"]["parts"][0]["quotes"][0]["quote"] == items[3].retrieval_text
    assert footer["result"]["semantic_grounding_verified"] is False


@pytest.mark.parametrize("profile", ["purpose_contract", "referent_context"])
def test_clarification_prevents_retrieval_while_public_ambiguous_plan_is_not_reinterpreted(profile):
    items, _, _, handles = fixtures()
    request = WorkflowRequest.model_validate_json(
        json.dumps(
            {
                "query": "Which doctor is meant?",
                "history": [{"role": "user", "content": "Person A and Person B"}],
            }
        )
    )
    ambiguous = wire(
        [
            part(
                request.query,
                handles["main"],
                "profile_detail",
                reference_text="Person A and Person B",
                retrieval_query=request.query + " Person A and Person B",
                history_indices=[0],
            )
        ]
    )
    result = probe(request, ambiguous, [[items[0].chunk_id, items[1].chunk_id]], profile=profile)
    assert result["result"]["parts"][0]["status"] == "candidate"
    clear = diagnostic.variant_of(
        ambiguous,
        (
            diagnostic.PartEdit(
                part_index=0,
                fields={
                    "state": "clarification_required",
                    "retrieval_query": None,
                    "document_handles": [],
                    "reason": "Two explicit historical owners, no single selected doctor.",
                },
            ),
        ),
    )
    safe = probe(request, clear, [[]], profile=profile)
    assert safe["fixture_retrieval_calls"] == [] and safe["draft_messages"] == []
    assert safe["result"]["parts"][0]["status"] == "clarification_required"


def test_punctuation_coverage_refusal_precedes_all_fixture_dependencies():
    items, _, _, handles = fixtures()
    request = WorkflowRequest(query="Describe ServiceX, and book a visit.")
    proposal = wire(
        [
            part("Describe ServiceX", handles["services"]),
            part(
                "and book a visit.",
                handles["services"],
                state="excluded",
                retrieval_query=None,
                document_handles=[],
                reason="Excluded action",
            ),
        ]
    )
    result = probe(request, proposal, [[items[4].chunk_id], []])
    assert result["error"] == "invalid_plan" and not result["consumer_entered"]
    assert result["fixture_retrieval_calls"] == result["draft_messages"] == []
    fixed = diagnostic.variant_of(
        proposal,
        (
            diagnostic.PartEdit(
                part_index=0,
                fields={
                    "original_text": "Describe ServiceX,",
                    "retrieval_query": "Describe ServiceX,",
                },
            ),
        ),
    )
    result = probe(request, fixed, [[items[4].chunk_id], []])
    assert [p["status"] for p in result["result"]["parts"]] == ["candidate", "excluded"]


def test_declared_reference_loss_fails_before_retrieval():
    items, _, _, handles = fixtures()
    request = WorkflowRequest(query="Describe ServiceX.")
    proposal = wire(
        [
            part(
                request.query,
                handles["services"],
                reference_text="ServiceX",
                retrieval_query="Describe ServiceX.",
            )
        ]
    )
    fixed_text = "Describe "
    data = proposal.model_dump(mode="json")
    data["parts"][0].update(original_text=fixed_text, retrieval_query=fixed_text)
    broken = wire(data["parts"])
    result = probe(request, broken, [[items[4].chunk_id]])
    assert result["error"] == "retrieval_query_lost_reference_context"


def test_cross_part_citation_injection_is_rejected_even_for_same_page():
    items, _, _, handles = fixtures()
    request = WorkflowRequest(query="Describe ServiceX. Describe ServiceY.")
    proposal = wire(
        [
            part("Describe ServiceX.", handles["services"]),
            part("Describe ServiceY.", handles["services"]),
        ]
    )
    result = probe(
        request,
        proposal,
        [[items[4].chunk_id], [items[5].chunk_id]],
        forced=((items[4].chunk_id,), (items[4].chunk_id,)),
    )
    assert result["error"] == "invalid_citation" and result["result"] is None


@pytest.mark.parametrize("profile", ["purpose_contract", "referent_context"])
def test_draft_cannot_reclassify_a_public_part_as_clarification_even_with_full_context(
    monkeypatch, profile
):
    items, _, _, handles = fixtures()
    request = WorkflowRequest.model_validate_json(
        json.dumps(
            {
                "query": "Which doctor's training is meant?",
                "history": [{"role": "user", "content": "Person A and Person B"}],
            }
        )
    )
    proposal = wire(
        [
            part(
                request.query,
                handles["main"],
                "profile_detail",
                reference_text="Person A and Person B",
                history_indices=[0],
                retrieval_query=request.query + " Person A and Person B",
            )
        ]
    )

    async def clarification_fixture(self, messages, output_model, **kwargs):
        self.messages = [m.model_dump(mode="json") for m in messages]
        body = json.loads(messages[1].content)
        return StructuredResult(
            AnswerDraft(
                parts=(
                    PartDraft(
                        part_id=body["parts"][0]["part_id"],
                        status="clarification_required",
                        quotes=(),
                        reason_code="ambiguous_request",
                    ),
                )
            ),
            (),
        )

    monkeypatch.setattr(diagnostic.FixtureDraft, "complete", clarification_fixture)
    result = probe(request, proposal, [[items[0].chunk_id, items[1].chunk_id]], profile=profile)
    body = json.loads(result["draft_messages"][1]["content"])
    assert body["original_query"] == request.query and body["history"]
    assert result["error"] == "invalid_draft" and result["result"] is None


@pytest.mark.parametrize(
    "state,ids", [("excluded", ["synthetic-chunk-1"]), ("public", ["missing"])]
)
def test_illegal_candidate_injection_is_rejected(state, ids):
    _, _, _, handles = fixtures()
    request = WorkflowRequest(query="Synthetic request.")
    proposal = wire(
        [
            part(
                request.query,
                handles["main"],
                state=state,
                retrieval_query=None if state == "excluded" else request.query,
                reason="Excluded synthetic action" if state == "excluded" else None,
            )
        ]
    )
    with pytest.raises(ValueError, match="candidate_membership"):
        probe(request, proposal, [ids])


@pytest.mark.parametrize("field", ["intended_use", "owner_handle", "operation", "invented"])
def test_offline_edits_cannot_change_purpose_owner_or_operation(field):
    with pytest.raises(ValueError, match="unsupported_diagnostic_edit"):
        diagnostic.PartEdit(part_index=0, fields={field: "forbidden"})


@pytest.mark.parametrize("tamper", ["digest", "late_file", "outside_root"])
def test_seal_tampering_fails_before_corpus_loading(tmp_path, monkeypatch, tamper):
    capture = tmp_path / "capture"
    capture.mkdir()
    path = tmp_path / "last.json"
    path.write_text("{}", encoding="utf-8")
    files = {"last.json": diagnostic.file_hash(path)}
    if tamper == "late_file":
        files["last.json"] = "0" * 64
    if tamper == "outside_root":
        files = {"../outside.json": "0" * 64}
    seal = capture / "evidence-seal.json"
    seal.write_text(json.dumps({"files": files}), encoding="utf-8")
    monkeypatch.setattr(diagnostic, "CAPTURE", Path("capture"))
    monkeypatch.setattr(
        diagnostic, "SEAL_SHA256", "0" * 64 if tamper == "digest" else diagnostic.file_hash(seal)
    )
    monkeypatch.setattr(
        diagnostic, "load_corpus", lambda *a: pytest.fail("Must not read corpus after tamper")
    )
    with pytest.raises(ValueError, match="referent_diagnosis_.*changed"):
        diagnostic.authenticate(tmp_path)


@pytest.mark.parametrize("late_bad_candidate", [False, True])
def test_saved_json_traces_replay_and_all_scenarios_validate_before_fixture_nodes(
    tmp_path, monkeypatch, late_bad_candidate
):
    items, evidence, authority, handles = fixtures()
    request = WorkflowRequest(query="Describe ServiceX.")
    proposal = wire([part(request.query, handles["services"])])
    bindings = SourceBindings(
        evidence, include_block_types=True, directory_authority=authority, purpose_contract=True
    )
    packets, traces = [], []
    for n in range(48):
        identity = f"synthetic-{n}"
        for arm in ("control", "referent_context"):
            path = tmp_path / "capture" / arm / identity
            path.mkdir(parents=True)
            (path / (identity + ".json")).write_text(
                json.dumps({"proposal": proposal.model_dump(mode="json")}), encoding="utf-8"
            )
            payload = {"synthetic": n}
            packets.append(
                {
                    "case_id": identity,
                    "arm": arm,
                    "request": request.model_dump(mode="json"),
                    "payload": payload,
                    "payload_sha256": diagnostic.payload_hash(payload),
                }
            )
            traces.append(
                {
                    "case_id": identity,
                    "arm": arm,
                    **diagnostic.trace_output(request, proposal, bindings, evidence, identity),
                }
            )
    (tmp_path / "capture/mechanical-source-policy-traces.json").write_text(
        json.dumps({"traces": traces}), encoding="utf-8"
    )
    specs = {
        "scenarios": [
            {
                "id": f"probe-{n}",
                "case_id": "synthetic-0",
                "arm": "referent_context",
                "purpose": "Synthetic saved-capture JSON integrity and offline dependency check.",
                "candidates_by_part": [
                    ["missing" if late_bad_candidate and n == 1 else items[4].chunk_id]
                ],
            }
            for n in range(2)
        ]
    }
    (tmp_path / "scenarios.json").write_text(json.dumps(specs), encoding="utf-8")
    monkeypatch.setattr(diagnostic, "CAPTURE", Path("capture"))
    monkeypatch.setattr(
        diagnostic, "authenticate", lambda root: ({"packets": packets}, evidence, authority, {})
    )
    monkeypatch.chdir(tmp_path)
    if late_bad_candidate:

        async def forbidden(*args, **kwargs):
            pytest.fail("All scenario memberships must validate before the first fixture")

        monkeypatch.setattr(diagnostic, "consumer_probe", forbidden)
        with pytest.raises(ValueError, match="candidate_membership"):
            asyncio.run(diagnostic.diagnose(tmp_path, tmp_path / "output", Path("scenarios.json")))
        assert not (tmp_path / "output").exists()
    else:
        asyncio.run(diagnostic.diagnose(tmp_path, tmp_path / "output", Path("scenarios.json")))
        replay = json.loads((tmp_path / "output/mechanical-replay.json").read_bytes())
        assert replay["actual_captures"] == 96
        probes = json.loads((tmp_path / "output/consumer-probes.json").read_bytes())["probes"]
        assert len(probes) == 2 and all(p["literal_valid"] for p in probes)
        with pytest.raises(FileExistsError):
            asyncio.run(diagnostic.diagnose(tmp_path, tmp_path / "output", Path("scenarios.json")))
